# The week-quality model of WEEK-OPTIMISER-SPEC.md section 3, written as an
# integer program with JuMP and HiGHS.
#
# This file only defines functions, so a notebook or a script can include it.
# It is a study written independently of the browser solver: agreement between
# the two, and with the brute-force answers in the fixture, is the check.

using JuMP
using HiGHS
using JSON

# A run ends at a gap of this many minutes or more. This is the break used when
# a case names no preference; a case can ask for a longer one (breakMins).
const RUN_BREAK_MINS = 60

# One class on the timetable. weeks is empty when the class has no week data,
# which means it is present in every week considered.
struct Event
    label::String
    day::String
    start_mins::Int
    end_mins::Int
    weeks::Vector{Int}
end

struct Group
    group_id::String
    session_ids::Vector{Any}
    sittings::Vector{Event}
end

struct Case
    name::String
    fixed::Vector{Event}
    groups::Vector{Group}
    free_days::Vector{String}
    break_mins::Int
    expected_clashes::Int
    expected_blocked::Int
    expected_front::Vector{Tuple{Int,Int}}
end

# ---------------------------------------------------------------------------
# Reading the fixture
# ---------------------------------------------------------------------------

function time_to_mins(text)
    parts = split(text, ":")
    return parse(Int, parts[1]) * 60 + parse(Int, parts[2])
end

# null and [] both mean "no week data", as in sharedWeeks.
function read_weeks(value)
    if value === nothing
        return Int[]
    end
    return Int[w for w in value]
end

function read_event(raw, label)
    event = Event(label, raw["day"], time_to_mins(raw["startTime"]),
                  time_to_mins(raw["endTime"]), read_weeks(raw["weeks"]))
    # A class that ends when it starts would fill no time slot, and the slot
    # model below would lose it, so refuse it rather than score it wrongly.
    if event.end_mins <= event.start_mins
        error("event $label ends at or before its start")
    end
    return event
end

function read_case(raw)
    fixed = Event[read_event(f, f["label"]) for f in raw["fixed"]]
    groups = Group[]
    for g in raw["groups"]
        sittings = Event[read_event(s, string(s["sessionId"])) for s in g["sittings"]]
        session_ids = Any[s["sessionId"] for s in g["sittings"]]
        push!(groups, Group(g["groupId"], session_ids, sittings))
    end
    front = Tuple{Int,Int}[(e["runMins"], e["days"]) for e in raw["expected"]["front"]]

    # A case without preferences keeps no day free and a one-hour break.
    free_days = String[]
    break_mins = RUN_BREAK_MINS
    prefs = get(raw, "preferences", nothing)
    if prefs !== nothing
        free_days = String[d for d in prefs["freeDays"]]
        break_mins = prefs["breakMins"]
    end
    expected = raw["expected"]
    return Case(raw["name"], fixed, groups, free_days, break_mins,
                expected["clashes"], expected["blocked"], front)
end

# All cases in the fixture file.
function load_cases(path)
    data = JSON.parsefile(path)
    if data["runBreakMins"] != RUN_BREAK_MINS
        error("fixture uses runBreakMins = $(data["runBreakMins"]), this model assumes $RUN_BREAK_MINS")
    end
    return Case[read_case(raw) for raw in data["cases"]]
end

# One case, by its name or by its position (1-based) in the file.
function load_case(path, which)
    cases = load_cases(path)
    if which isa Integer
        return cases[which]
    end
    for c in cases
        if c.name == which
            return c
        end
    end
    error("no case named $which in $path")
end

# ---------------------------------------------------------------------------
# The clash rule, matching eventsCollide in assets/js/calendar-utils.js
# ---------------------------------------------------------------------------

function times_overlap(a::Event, b::Event)
    return a.start_mins < b.end_mins && b.start_mins < a.end_mins
end

# Two events meet in some week if either has no week data, or they name a
# common week.
function weeks_meet(a::Event, b::Event)
    if isempty(a.weeks) || isempty(b.weeks)
        return true
    end
    return !isempty(intersect(a.weeks, b.weeks))
end

function events_collide(a::Event, b::Event)
    return a.day == b.day && times_overlap(a, b) && weeks_meet(a, b)
end


# ---------------------------------------------------------------------------
# Weeks, days and time slots of a case
# ---------------------------------------------------------------------------

# Every event of the case that could be on the timetable: F, then every
# candidate. Candidates count even when not chosen, because the weeks
# considered are every week any event names (spec 3.2).
function all_events(case::Case)
    events = copy(case.fixed)
    for g in case.groups
        append!(events, g.sittings)
    end
    return events
end

# Week 0 stands for the single undated week used when no event names a week.
function is_present(event::Event, week::Int)
    return isempty(event.weeks) || week in event.weeks
end

# The weeks to score. Two weeks in which exactly the same events are present
# get exactly the same occupancy, runs and days for every arrangement, so only
# the first week of each distinct set of present events is kept. This is exact,
# and it keeps the model small: most classes run in all twelve weeks.
function weeks_to_score(case::Case)
    events = all_events(case)
    named = sort(unique(vcat([e.weeks for e in events]...)))
    if isempty(named)
        return [0]
    end
    kept = Int[]
    seen = Set{Vector{Bool}}()
    for w in named
        signature = [is_present(e, w) for e in events]
        if !(signature in seen)
            push!(seen, signature)
            push!(kept, w)
        end
    end
    return kept
end

# The largest slot length in minutes that divides the case's break and every
# start and end time, so every class covers whole slots and the break is a
# whole number of slots.
function slot_length(case::Case)
    size = case.break_mins
    for e in all_events(case)
        size = gcd(size, e.start_mins, e.end_mins)
    end
    return size
end

# Slot t covers minutes [t * slot, (t + 1) * slot) of the day.
function slots_of(event::Event, slot::Int)
    return div(event.start_mins, slot):(div(event.end_mins, slot) - 1)
end

# ---------------------------------------------------------------------------
# The model
# ---------------------------------------------------------------------------

# Builds the JuMP model for one case. Variables and expressions are reachable
# by name: model[:x], model[:C], model[:B], model[:R], model[:D]. The candidate keys
# (group index, sitting index) are in model[:candidates].
#
# Only x, c, y, z and D are integer. Occupancy o and coverage b are continuous
# in [0, 1]: once x is integer their lower bounds are 0 or 1, and nothing gains
# from raising them above those bounds, so at an optimum they take those values.
function build_model(case::Case)
    model = Model(HiGHS.Optimizer)
    set_silent(model)

    groups = case.groups
    candidates = Tuple{Int,Int}[]
    for g in eachindex(groups), s in eachindex(groups[g].sittings)
        push!(candidates, (g, s))
    end
    sitting(gs) = groups[gs[1]].sittings[gs[2]]
    model[:candidates] = candidates

    # x[g,s] = 1 when sitting s of group g is chosen.
    @variable(model, x[candidates], Bin)

    # Exactly one sitting per group.
    @constraint(model, [g in eachindex(groups)],
                sum(x[(g, s)] for s in eachindex(groups[g].sittings)) == 1)

    # ---- Clashes C ----

    # Clashes between two candidates of different groups. c >= x[a] + x[b] - 1
    # forces c to 1 when both are chosen. It only forces c up, which is enough:
    # C is minimised, then held at its minimum, so c is never above the true
    # count when C is read. Two sittings of one group are never both chosen.
    pairs = Tuple{Tuple{Int,Int},Tuple{Int,Int}}[]
    for i in eachindex(candidates), j in (i + 1):length(candidates)
        a = candidates[i]
        b = candidates[j]
        if a[1] != b[1] && events_collide(sitting(a), sitting(b))
            push!(pairs, (a, b))
        end
    end
    @variable(model, c[pairs], Bin)
    @constraint(model, [p in pairs], c[p] >= x[p[1]] + x[p[2]] - 1)

    # A candidate that collides with k fixed events adds k clashes when chosen.
    fixed_hits = Dict(a => count(f -> events_collide(sitting(a), f), case.fixed)
                      for a in candidates)

    # Clashes inside F happen whatever is chosen, so they are a constant.
    fixed_clashes = 0
    for i in eachindex(case.fixed), j in (i + 1):length(case.fixed)
        if events_collide(case.fixed[i], case.fixed[j])
            fixed_clashes += 1
        end
    end

    @expression(model, C, fixed_clashes + sum(c[p] for p in pairs; init = 0) +
                          sum(fixed_hits[a] * x[a] for a in candidates))

    # ---- Classes on free days B ----

    # The number of chosen sittings that fall on a day the student wants free.
    # Fixed events are left out: they cannot move, so they are no part of the
    # choice. B only grows as sittings are added, like C.
    blocked = [a for a in candidates if sitting(a).day in case.free_days]
    @expression(model, B, sum(x[a] for a in blocked; init = 0))

    # ---- Occupancy ----

    weeks = weeks_to_score(case)
    slot = slot_length(case)
    days = unique([e.day for e in all_events(case)])
    model[:weeks] = weeks
    model[:slot] = slot

    # Who may fill each (week, day, slot): the fixed events and the candidates
    # present that week whose time covers the slot.
    fixed_cover = Set{Tuple{Int,String,Int}}()
    cand_cover = Dict{Tuple{Int,String,Int},Vector{Tuple{Int,Int}}}()
    for w in weeks
        for f in case.fixed
            if is_present(f, w)
                for t in slots_of(f, slot)
                    push!(fixed_cover, (w, f.day, t))
                end
            end
        end
        for a in candidates
            e = sitting(a)
            if is_present(e, w)
                for t in slots_of(e, slot)
                    push!(get!(cand_cover, (w, e.day, t), Tuple{Int,Int}[]), a)
                end
            end
        end
    end
    # A slot nobody can fill is always empty and gets no variable.
    occ_keys = sort(unique(vcat(collect(fixed_cover), collect(keys(cand_cover)))))

    # o[w,d,t] is 1 when something is on in that slot. It is forced up by every
    # event that covers the slot and never forced down. That is enough: o only
    # feeds lower bounds on b, and R is only ever minimised or held at its
    # minimum, so nothing gains from o above the truth.
    @variable(model, 0 <= o[occ_keys] <= 1)
    for k in occ_keys
        if k in fixed_cover
            @constraint(model, o[k] >= 1)
        end
        for a in get(cand_cover, k, Tuple{Int,Int}[])
            @constraint(model, o[k] >= x[a])
        end
    end

    # ---- Bridging short gaps ----

    # A run goes on across a free stretch shorter than the case's break. So slot
    # t counts towards a run (b = 1) when it is occupied, or when it lies
    # between two occupied slots i < t < j with fewer than break_mins minutes
    # between them. Whatever is on between i and j, every free stretch there is
    # shorter still, so the whole of i..j is one run. As with o, b is only
    # forced up, and only R reads it.
    max_gap_slots = div(case.break_mins - 1, slot)  # largest k with k * slot < break
    bridge_rows = Tuple{Tuple{Int,String,Int},Tuple{Int,String,Int},Tuple{Int,String,Int}}[]
    cover_set = Set(occ_keys)
    for w in weeks, d in days
        ts = sort([k[3] for k in occ_keys if k[1] == w && k[2] == d])
        for i in ts, j in ts
            gap = j - i - 1
            if gap >= 1 && gap <= max_gap_slots
                for t in (i + 1):(j - 1)
                    push!(bridge_rows, ((w, d, t), (w, d, i), (w, d, j)))
                    push!(cover_set, (w, d, t))
                end
            end
        end
    end
    cover_keys = sort(collect(cover_set))
    @variable(model, 0 <= b[cover_keys] <= 1)
    @constraint(model, [k in occ_keys], b[k] >= o[k])
    @constraint(model, [r in bridge_rows], b[r[1]] >= o[r[2]] + o[r[3]] - 1)

    # ---- Longest run R ----

    # Group the coverable slots of each (week, day) into stretches of
    # consecutive slots. A run can only lie inside one stretch.
    stretches = Tuple{Int,String,Vector{Int}}[]
    for w in weeks, d in days
        ts = sort([k[3] for k in cover_keys if k[1] == w && k[2] == d])
        current = Int[]
        for t in ts
            if !isempty(current) && t != current[end] + 1
                push!(stretches, (w, d, current))
                current = Int[]
            end
            push!(current, t)
        end
        if !isempty(current)
            push!(stretches, (w, d, current))
        end
    end
    longest = maximum([length(s[3]) for s in stretches]; init = 0)

    # y[m] must be 1 when some window of m consecutive slots is all covered:
    # y[m] >= (sum of b over the window) - (m - 1). A covered run of n slots
    # contains a covered window of every length 1..n, so y[1..n] are all
    # forced to 1 and the sum of y is at least the longest run in slots. It is
    # only forced up; minimising R brings the sum down to exactly the longest
    # run, and holding R at that minimum keeps it there.
    @variable(model, y[1:longest], Bin)
    for (w, d, ts) in stretches
        n = length(ts)
        for first in 1:n, m in 1:(n - first + 1)
            window = ts[first:(first + m - 1)]
            @constraint(model, y[m] >= sum(b[(w, d, t)] for t in window) - (m - 1))
        end
    end
    @expression(model, R, slot * sum(y[m] for m in 1:longest; init = 0))

    # ---- Days D ----

    # z[w,d] is 1 when anything is on day d in week w: forced to 1 by a fixed
    # event, and up by each candidate there. D is at least the number of days
    # in every week, so at least the largest. z and D are only forced up, and
    # D is only minimised or capped by the day limit, so a solution never
    # needs them above the truth.
    day_keys = Tuple{Int,String}[]
    for w in weeks, d in days
        if any(e -> e.day == d && is_present(e, w), all_events(case))
            push!(day_keys, (w, d))
        end
    end
    @variable(model, z[day_keys], Bin)
    for (w, d) in day_keys
        if any(f -> f.day == d && is_present(f, w), case.fixed)
            @constraint(model, z[(w, d)] >= 1)
        end
        for a in candidates
            e = sitting(a)
            if e.day == d && is_present(e, w)
                @constraint(model, z[(w, d)] >= x[a])
            end
        end
    end
    @variable(model, D >= 0, Int)
    for w in weeks
        @constraint(model, D >= sum(z[k] for k in day_keys if k[1] == w; init = 0))
    end

    return model
end

# Rounds an objective value read from the solver to the nearest integer.
whole(value) = round(Int, value)

# Solves for the current objective and returns its rounded value, or nothing
# when the model has no solution.
function solve_for(model)
    optimize!(model)
    status = termination_status(model)
    if status == INFEASIBLE || status == INFEASIBLE_OR_UNBOUNDED
        return nothing
    end
    if status != OPTIMAL
        error("solver ended with $status")
    end
    return whole(objective_value(model))
end

# The sitting chosen in each group in the model's current solution, as
# group id => session id.
function chosen_sittings(case::Case, model)
    x = model[:x]
    chosen = Dict{String,Any}()
    for (g, s) in model[:candidates]
        if value(x[(g, s)]) > 0.5
            chosen[case.groups[g].group_id] = case.groups[g].session_ids[s]
        end
    end
    return chosen
end

# The entries (R, D, choice) whose pair is not matched or beaten on both by a
# different pair, without repeats, sorted by R. A repeated pair keeps the
# first choice found for it.
function pareto_front(found)
    front = []
    for (i, entry) in enumerate(found)
        r, d = entry[1], entry[2]
        beaten = any(other -> (other[1], other[2]) != (r, d) &&
                              other[1] <= r && other[2] <= d, found)
        repeated = any(j -> (found[j][1], found[j][2]) == (r, d), 1:(i - 1))
        if !beaten && !repeated
            push!(front, entry)
        end
    end
    return sort(front; by = e -> e[1])
end

# Minimises clashes only and returns C*.
function solve_clashes(case::Case)
    model = build_model(case)
    @objective(model, Min, model[:C])
    clashes = solve_for(model)
    if clashes === nothing
        error("clash model for $(case.name) has no solution")
    end
    return clashes
end

# The best weeks of a case (spec 3.3). Returns
#   (clashes = C*, blocked = B*, front = [(runMins, days), ...],
#    choices = [Dict, ...])
# where choices[i] is one arrangement reaching front[i], group id => session id.
# It is whichever arrangement the solver found, not the one the site would
# report under spec 3.4.
function solve_case(case::Case)
    model = build_model(case)
    C, B, R, D = model[:C], model[:B], model[:R], model[:D]

    # 1. Fewest clashes, then hold C at that minimum. Clashes come before free
    #    days: a missed class is worse than a class on a day the student
    #    wanted off, so a free day never causes a clash.
    @objective(model, Min, C)
    clashes = solve_for(model)
    if clashes === nothing
        error("clash model for $(case.name) has no solution")
    end
    @constraint(model, C <= clashes)

    # 2. Among those, fewest classes on free days, then hold B there.
    @objective(model, Min, B)
    blocked = solve_for(model)
    @constraint(model, B <= blocked)

    # 3. For each day limit: the shortest longest run with D at most the limit,
    #    then the fewest days with R held at that run.
    found = []
    for limit in 1:7
        day_cap = @constraint(model, D <= limit)
        @objective(model, Min, R)
        run = solve_for(model)
        if run !== nothing
            run_cap = @constraint(model, R <= run)
            @objective(model, Min, D)
            day_count = solve_for(model)
            push!(found, (run, day_count, chosen_sittings(case, model)))
            delete(model, run_cap)
        end
        delete(model, day_cap)
    end

    # 4. Drop dominated and repeated pairs.
    front = pareto_front(found)
    return (clashes = clashes,
            blocked = blocked,
            front = Tuple{Int,Int}[(e[1], e[2]) for e in front],
            choices = [e[3] for e in front])
end

# Number of variables and constraints in a case's model, for reporting.
function model_size(case::Case)
    model = build_model(case)
    return (variables = num_variables(model),
            constraints = num_constraints(model; count_variable_in_set_constraints = false))
end
