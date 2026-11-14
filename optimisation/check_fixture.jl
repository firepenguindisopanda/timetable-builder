# Runs every case in the fixture through the integer program and compares the
# answers with the brute-force ones stored there.
#
#   julia --project=optimisation optimisation/check_fixture.jl [fixture.json]
#
# Exits 0 only if every C* and every front matches, otherwise 1.

include(joinpath(@__DIR__, "week_model.jl"))

# Writes a front as "120/3 180/2": run minutes / days.
show_front(front) = join(["$(r)/$(d)" for (r, d) in front], " ")

function main(args)
    default_path = joinpath(@__DIR__, "..", "tests", "fixtures", "week_loads.json")
    path = normpath(isempty(args) ? default_path : args[1])
    cases = load_cases(path)
    println("Fixture: ", path)
    println("Each line: C* and front (run minutes/days), expected then got.")
    println()

    failed = String[]
    total = @elapsed for case in cases
        seconds = @elapsed got = solve_case(case)
        ok = got.clashes == case.expected_clashes && got.front == case.expected_front
        if !ok
            push!(failed, case.name)
        end
        println(rpad(case.name, 36),
                " expected C=", case.expected_clashes, " ", rpad(show_front(case.expected_front), 16),
                " got C=", got.clashes, " ", rpad(show_front(got.front), 16),
                ok ? "match   " : "MISMATCH", " ", round(seconds; digits = 2), "s")
    end

    println()
    println(length(cases) - length(failed), " of ", length(cases), " cases match (",
            round(total; digits = 1), "s)")
    if !isempty(failed)
        println("Did not match: ", join(failed, ", "))
        exit(1)
    end
    exit(0)
end

main(ARGS)
