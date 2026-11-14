'use strict';

/**
 * How long a break has to be before a run of class is over.
 *
 * Classes end fifteen minutes early so students can reach the next room, so
 * 8-10 followed by 10-12 is four hours of class with no real rest. A free
 * hour is one. Decided 13 Nov 2026.
 */
const RUN_BREAK_MINS = 60;

/** Week numbers named by any event, ascending. Empty when none names one. */
function _weeksNamed(events) {
  const weeks = new Set();
  for (const event of events) {
    if (Array.isArray(event.weeks)) {
      for (const week of event.weeks) weeks.add(week);
    }
  }
  return [...weeks].sort((a, b) => a - b);
}

/**
 * Whether an event is present in a week. An event with no weeks is in every
 * one, which is what an uploaded PDF gives. `week` is null for the single
 * undated week, where everything is present.
 */
function _runsInWeek(event, week) {
  if (week === null) return true;
  if (!Array.isArray(event.weeks) || event.weeks.length === 0) return true;
  return event.weeks.includes(week);
}

/**
 * The hardest week a set of classes makes: its longest unbroken run of class
 * and its number of days with class.
 *
 * Scored on the worst week because classes do not all run every week, and a
 * student has to get through each one of them.
 */
function weekQuality(events) {
  let runMins = 0;
  let days = 0;
  const named = _weeksNamed(events);
  const weeks = named.length > 0 ? named : [null];
  for (const week of weeks) {
    const byDay = new Map();
    for (const event of events) {
      if (!_runsInWeek(event, week)) continue;
      if (!byDay.has(event.day)) byDay.set(event.day, []);
      byDay.get(event.day).push([
        timeToMins(event.startTime),
        timeToMins(event.endTime),
      ]);
    }
    days = Math.max(days, byDay.size);
    for (const spans of byDay.values()) {
      spans.sort((a, b) => a[0] - b[0]);
      let [start, reach] = spans[0];
      for (const [from, to] of spans.slice(1)) {
        if (from - reach < RUN_BREAK_MINS) {
          reach = Math.max(reach, to);
        } else {
          runMins = Math.max(runMins, reach - start);
          start = from;
          reach = to;
        }
      }
      runMins = Math.max(runMins, reach - start);
    }
  }
  return { runMins, days };
}

/**
 * How many partial arrangements one search may visit before it stops.
 *
 * Set 13 Nov 2026 against the 600 realistic loads of spec 9.4
 * (`node docs/ideas/week-quality-headroom-all.js solver`, three runs). All
 * 600 come back proven; the most any needs is 66,616 nodes, and the slowest
 * placeCoursesBest call took 42 ms, median 1 ms. A search that spends the
 * whole budget, which the hardest of the 200 cross-faculty test loads do,
 * took about 90 ms on the same machine. So 100,000 leaves half again the
 * nodes the worst realistic load needs, and well over twice the time a full
 * budget takes before the 250 ms limit, for slower machines than the one it
 * was measured on. Raising it to 200,000 would prove all 200 test loads too
 * (the hardest needs 199,430) but a full budget then took 181 ms, too close
 * to the limit. The most any case in week_loads.json needs is 1,988.
 */
const NODE_BUDGET = 100000;

/** Plain string order, the same in every browser. Spec 3.4. */
function _compareIds(a, b) {
  const x = String(a);
  const y = String(b);
  if (x < y) return -1;
  if (x > y) return 1;
  return 0;
}

/**
 * Groups in canonical order, each with its sittings in timetable order.
 * Spec 3.4: fewest candidates first, then group id as a plain string.
 *
 * A group with no sittings is dropped, the way reoptimise() drops one: there
 * is nothing to choose, and keeping it would leave no arrangement at all.
 */
function _canonicalGroups(groups) {
  return groups
    .filter((g) => g.sessions && g.sessions.length > 0)
    .map((g) => ({ groupId: g.groupId, sessions: sessionsInTimetableOrder(g.sessions) }))
    .sort((a, b) => a.sessions.length - b.sessions.length || _compareIds(a.groupId, b.groupId));
}

/**
 * The candidate index each group takes in a reference, or null when the
 * reference does not name a sitting of every group. Names of other groups are
 * ignored, so a reference may describe more than this search is choosing.
 */
function _referencePicks(reference, ordered) {
  if (!reference || typeof reference !== 'object') return null;
  const picks = [];
  for (const group of ordered) {
    if (!Object.prototype.hasOwnProperty.call(reference, group.groupId)) return null;
    const at = group.sessions.findIndex((s) => s.sessionId === reference[group.groupId]);
    if (at < 0) return null;
    picks.push(at);
  }
  return picks;
}

/** Whether a held entry is at least as good as (runMins, days) on both. */
function _matched(front, runMins, days) {
  return front.some((e) => e.runMins <= runMins && e.days <= days);
}

/**
 * What the search needs to know about each event, worked out once instead of
 * at every node.
 *
 * Week classes: two weeks in which exactly the same events of the instance
 * are present score the same for any arrangement, so only one week of each
 * class is scored, and a class contained in another is dropped (below). On
 * the 600 realistic loads that leaves one class for 566 of them and at most
 * five for any, where scoring every week cost about 0.2 ms a node.
 *
 * The weeks looked at are those named by any event of the instance, where
 * weekQuality looks only at those named by the events it is given. The extra
 * weeks cannot change the answer: in a week none of the given events names,
 * only their weekless events are present, and those are present in every
 * week they do name, so such a week never scores higher. When none of them
 * names a week, every week holds all of them, which is the undated week.
 *
 * Clashes are worked out once per pair with eventsCollide: `fixedHits` on a
 * candidate counts its clashes with the fixed events, and `later` names the
 * candidates of later groups it clashes with.
 */
function _searchModel(fixed, candidates) {
  const all = [...fixed];
  for (const options of candidates) all.push(...options);
  const named = _weeksNamed(all);
  const weeks = named.length > 0 ? named : [null];
  const signatures = new Map();
  for (const week of weeks) {
    let signature = '';
    for (const event of all) signature += _runsInWeek(event, week) ? '1' : '0';
    if (!signatures.has(signature)) signatures.set(signature, week);
  }
  // A class whose events are all present in another class as well never
  // scores higher than it, because adding events never shortens a run or
  // takes away a day. Only the classes no other one contains are kept, and
  // every event still lands in at least one of them.
  const within = (a, b) => {
    for (let i = 0; i < a.length; i++) {
      if (a[i] === '1' && b[i] !== '1') return false;
    }
    return true;
  };
  const kept = [...signatures.keys()].filter(
    (a) => ![...signatures.keys()].some((b) => b !== a && within(a, b))
  );
  const classWeeks = kept.map((signature) => signatures.get(signature));

  // Keyed as weekQuality keys its days, so two days are one exactly when it
  // would put them in one bucket.
  const dayIndex = new Map();
  for (const event of all) {
    if (!dayIndex.has(event.day)) dayIndex.set(event.day, dayIndex.size);
  }

  const describe = (event) => {
    const classes = [];
    classWeeks.forEach((week, k) => {
      if (_runsInWeek(event, week)) classes.push(k);
    });
    return {
      event,
      day: dayIndex.get(event.day),
      from: timeToMins(event.startTime),
      to: timeToMins(event.endTime),
      classes,
    };
  };
  const fixedInfo = fixed.map(describe);
  const candidateInfo = candidates.map((options) => options.map(describe));

  // eventsCollide needs the same day and overlapping times before it looks
  // at weeks. Different day buckets mean different days, and the minutes are
  // the ones timesOverlap would compute, so both checks only skip calls that
  // would return false.
  const collide = (a, b) =>
    a.day === b.day && a.from < b.to && b.from < a.to && eventsCollide(a.event, b.event);
  candidateInfo.forEach((options, depth) => {
    for (const info of options) {
      info.fixedHits = 0;
      for (const other of fixedInfo) {
        if (collide(info, other)) info.fixedHits += 1;
      }
      info.later = [];
    }
  });
  // `later` on a candidate lists, as (depth, index) pairs, the sittings of
  // later groups it clashes with. Clashes are few, so this is short.
  candidateInfo.forEach((options, depth) => {
    for (const info of options) {
      for (let d = depth + 1; d < candidateInfo.length; d++) {
        candidateInfo[d].forEach((other, at) => {
          if (collide(other, info)) info.later.push(d, at);
        });
      }
    }
  });

  return {
    classCount: classWeeks.length,
    dayCount: dayIndex.size,
    fixed: fixedInfo,
    candidates: candidateInfo,
  };
}

/**
 * For every candidate not yet chosen, how many clashes it would bring with
 * the fixed events and the sittings placed so far, kept up to date one
 * sitting at a time, so the search reads a child's new clashes off
 * `hits[depth][at]` instead of checking it against everything chosen.
 */
function _clashState(model) {
  const hits = model.candidates.map((options) => Int32Array.from(options, (info) => info.fixedHits));
  return {
    hits,
    // `step` is 1 to place the candidate and -1 to take it away again.
    place(info, step) {
      const later = info.later;
      for (let i = 0; i < later.length; i += 2) hits[later[i]][later[i + 1]] += step;
    },
  };
}

/**
 * The longest run in one day of one week, the way weekQuality finds it.
 * `from` and `to` are already in start order, ties in the order the events
 * were added, which is the order weekQuality's stable sort leaves them in.
 */
function _cellRun(from, to) {
  let start = from[0];
  let reach = to[0];
  let run = 0;
  for (let i = 1; i < from.length; i++) {
    if (from[i] - reach < RUN_BREAK_MINS) {
      reach = Math.max(reach, to[i]);
    } else {
      run = Math.max(run, reach - start);
      start = from[i];
      reach = to[i];
    }
  }
  return Math.max(run, reach - start);
}

/**
 * The week of the events placed so far, kept up to date one sitting at a time.
 *
 * A sitting only changes its own day in the week classes it runs in, so only
 * those cells are rescored, and taking it away puts back what was there. The
 * result is weekQuality of the placed events, without walking all of them at
 * every node of the search.
 */
function _weekState(model) {
  const days = model.dayCount;
  const cellCount = model.classCount * days;
  const cellFrom = [];
  const cellTo = [];
  for (let c = 0; c < cellCount; c++) {
    cellFrom.push([]);
    cellTo.push([]);
  }
  const cellRun = new Array(cellCount).fill(0);
  const classDays = new Array(model.classCount).fill(0);
  const state = { runMins: 0, days: 0 };

  // `saved` collects (cell, run before, position) for unplace. Adding an
  // event never shortens a run or empties a day: it either joins the run it
  // lands in, which keeps that run's start and can only push its reach out,
  // or starts a new one. So the week's longest run and days only need
  // comparing with the cells just rescored. The search's own pruning rests on
  // the same fact.
  state.place = (info, saved) => {
    for (const k of info.classes) {
      const cell = k * days + info.day;
      const from = cellFrom[cell];
      const to = cellTo[cell];
      let at = from.length;
      while (at > 0 && from[at - 1] > info.from) at--;
      from.splice(at, 0, info.from);
      to.splice(at, 0, info.to);
      const before = cellRun[cell];
      const now = _cellRun(from, to);
      cellRun[cell] = now;
      if (now > state.runMins) state.runMins = now;
      if (from.length === 1) {
        classDays[k] += 1;
        if (classDays[k] > state.days) state.days = classDays[k];
      }
      saved.push(cell, before, at);
    }
  };

  state.unplace = (saved, runMins, daysBefore) => {
    for (let i = saved.length - 3; i >= 0; i -= 3) {
      const cell = saved[i];
      const from = cellFrom[cell];
      from.splice(saved[i + 2], 1);
      cellTo[cell].splice(saved[i + 2], 1);
      cellRun[cell] = saved[i + 1];
      if (from.length === 0) classDays[Math.floor(cell / days)] -= 1;
    }
    state.runMins = runMins;
    state.days = daysBefore;
  };

  return state;
}

/**
 * The best weeks one sitting per group can make around the fixed events.
 *
 * `fixedEvents` have day, startTime, endTime and weeks. `groups` are option
 * groups as placement.js holds them: { groupId, sessions }, each session with
 * a sessionId. `references` is an ordered list of arrangements, each a plain
 * object from group id to session id; one that does not name a valid sitting
 * of every group is ignored. `budget` is a count of partial arrangements
 * visited, NODE_BUDGET when omitted.
 *
 * Returns { clashes, front, proven, nodes }. `clashes` is the fewest clashing
 * pairs any arrangement has, counted as findConflicts counts them, so clashes
 * among the fixed events are included. `front` is every (runMins, days) not
 * beaten on both by another at that count (spec 3.3), sorted by runMins, each
 * with `sessionIds` naming the session chosen for every group. The
 * arrangement that stands for an entry is the earliest reference reaching it,
 * otherwise the first in canonical order (spec 3.4).
 *
 * The references are scored before the search, so an unproven result is never
 * worse than they are. With no valid reference the budget is not enforced
 * until one complete arrangement is held: the first dive always finishes, so
 * the result is the canonical-first arrangement at worst and never empty.
 * That can overrun the budget by at most one node per group.
 *
 * No clock, date or random number: the same input gives the same week on any
 * machine, which a share link relies on. Spec 3.5.
 */
function bestWeeks(fixedEvents, groups, references, budget) {
  const limit = budget === undefined || budget === null ? NODE_BUDGET : budget;
  const ordered = _canonicalGroups(groups || []);
  const fixed = fixedEvents || [];
  const n = ordered.length;
  const candidates = ordered.map((g) => g.sessions.map((s) => _candidateEvent(g, s)));

  let bestClashes = Infinity;
  let held = [];

  // Spec 3.4: an entry already held is never displaced by an equal one, so
  // the first to reach (runMins, days) stands for it.
  function offer(clashes, runMins, days, picks) {
    if (clashes > bestClashes) return;
    if (clashes < bestClashes) {
      bestClashes = clashes;
      held = [];
    } else if (_matched(held, runMins, days)) {
      return;
    }
    held = held.filter((e) => !(runMins <= e.runMins && days <= e.days));
    held.push({ runMins, days, picks: [...picks] });
  }

  for (const reference of references || []) {
    const picks = _referencePicks(reference, ordered);
    if (!picks) continue;
    const events = [...fixed, ...picks.map((at, i) => candidates[i][at])];
    const q = weekQuality(events);
    offer(findConflicts(events).length, q.runMins, q.days, picks);
  }

  const fixedClashes = findConflicts(fixed).length;
  const model = _searchModel(fixed, candidates);
  const week = _weekState(model);
  for (const info of model.fixed) week.place(info, []);
  const pending = _clashState(model);
  const picks = [];
  let nodes = 0;
  let stopped = false;

  // clashes, run and days only grow as sittings are added, so a partial that
  // is already matched or beaten cannot lead to a new front entry. Pruning on
  // matched, not only beaten, keeps the first arrangement to reach an entry.
  function visit(depth, clashes) {
    if (held.length > 0 && nodes >= limit) {
      stopped = true;
      return;
    }
    nodes += 1;
    if (clashes > bestClashes) return;
    if (clashes === bestClashes && _matched(held, week.runMins, week.days)) return;
    if (depth === n) {
      offer(clashes, week.runMins, week.days, picks);
      return;
    }
    const options = model.candidates[depth];
    const hitsHere = pending.hits[depth];
    for (let at = 0; at < options.length && !stopped; at++) {
      const info = options[at];
      const total = clashes + hitsHere[at];
      // A child already over the best clash count is abandoned on entry
      // without looking at its week, so it is counted here the same way and
      // its sitting never placed.
      if (total > bestClashes) {
        if (held.length > 0 && nodes >= limit) {
          stopped = true;
          break;
        }
        nodes += 1;
        continue;
      }
      const runMins = week.runMins;
      const days = week.days;
      const saved = [];
      picks.push(at);
      week.place(info, saved);
      pending.place(info, 1);
      visit(depth + 1, total);
      pending.place(info, -1);
      week.unplace(saved, runMins, days);
      picks.pop();
    }
  }
  visit(0, fixedClashes);

  // Reported in the caller's group order, which reads better than canonical.
  const front = held
    .slice()
    .sort((a, b) => a.runMins - b.runMins)
    .map((e) => {
      const sessionIds = {};
      for (const g of groups || []) {
        const i = ordered.findIndex((o) => o.groupId === g.groupId);
        if (i >= 0) sessionIds[g.groupId] = ordered[i].sessions[e.picks[i]].sessionId;
      }
      return { runMins: e.runMins, days: e.days, sessionIds };
    });
  return { clashes: bestClashes, front, proven: !stopped, nodes };
}

/**
 * Add courses the way placeCourses does, then look for the best week the new
 * classes can make. Spec 4 and 5.1.
 *
 * Same arguments and return shape as placeCourses, which runs first and is
 * kept as the reference, so the answer is never worse than today's and stays
 * put when it is already the best. Every placement in `existing` is fixed:
 * it comes back as the same value in the same position, pinned or not, and
 * only `selectedSessionId` of the newly placed groups can differ.
 *
 * The loose groups are exactly the ones placeCourses placed, so a group it
 * skipped for having no sittings is skipped here too. The result is the front's
 * first entry, the shortest longest run. `summary` gains `quality` (of the
 * whole final week), `proven`, and `options`: the front in order, each with
 * the full placements list for that entry.
 *
 * `clashing`, `unavoidable` and `conflictsAfter` are recounted against the
 * final arrangement, because placeCourses counted them as the groups went
 * down. `unavoidable` keeps its meaning, a group with one sitting that
 * clashes, now judged on the final week. `conflicts` and `noClearOption` on
 * each entry are placeCourses's own placement-time figures and are left as
 * they were.
 *
 * `extraReferences` is optional: arrangements of the new groups, each a plain
 * object from group id to session id, tried in the order given and before
 * placeCourses's answer. Re-arrange passes the week on the grid, so a week
 * that is already one of the best comes back with nothing moved (spec 3.4).
 * One that does not name a valid sitting of every new group is ignored.
 */
function placeCoursesBest(existing, courseGroups, index, extraReferences) {
  const base = placeCourses(existing, courseGroups, index);
  const looseAt = existing.length;
  const loose = base.placements.slice(looseAt);

  const byId = new Map();
  for (const course of courseGroups) {
    for (const group of course.groups) byId.set(group.groupId, group);
  }
  const groups = loose.map((p) => byId.get(p.groupId));

  // Two loose placements of one group id cannot be told apart by a search
  // that picks one sitting per group id, so that case keeps placeCourses's
  // answer rather than guess.
  const distinct = new Set(loose.map((p) => p.groupId)).size === loose.length;
  const reference = {};
  for (const p of loose) reference[p.groupId] = p.selectedSessionId;

  let front;
  let proven = true;
  if (distinct && groups.every(Boolean)) {
    const extra = Array.isArray(extraReferences) ? extraReferences : [];
    const found = bestWeeks(eventsFor(existing, index), groups, [...extra, reference]);
    front = found.front;
    proven = found.proven;
  } else {
    front = [{ ...weekQuality(eventsFor(base.placements, index)), sessionIds: reference }];
  }

  const arranged = (entry) => [
    ...existing,
    ...loose.map((p) => ({ ...p, selectedSessionId: entry.sessionIds[p.groupId] })),
  ];
  const options = front.map((entry) => ({
    runMins: entry.runMins,
    days: entry.days,
    placements: arranged(entry),
  }));
  const placements = options[0].placements;

  const events = eventsFor(placements, index);
  const clashingGroups = new Set();
  const conflicts = findConflicts(events);
  for (const conflict of conflicts) {
    clashingGroups.add(conflict.a.groupId);
    clashingGroups.add(conflict.b.groupId);
  }
  // base.placed follows the order of the new placements, so the position says
  // which one an entry is. Looking it up by group id would find an existing
  // placement of the same group first.
  const placed = base.placed.map((p, i) => {
    const clashing = clashingGroups.has(p.groupId);
    return {
      ...p,
      selectedSessionId: placements[looseAt + i].selectedSessionId,
      clashing,
      unavoidable: clashing && p.options === 1,
    };
  });

  return {
    ...base,
    placements,
    placed,
    summary: {
      ...base.summary,
      conflictsAfter: conflicts.length,
      unavoidable: placed.filter((p) => p.unavoidable).map((p) => p.groupId),
      quality: weekQuality(events),
      proven,
      options,
    },
  };
}

/**
 * Whether two lists of placements put the same classes in the same places.
 *
 * Order is not part of it: placeCoursesBest lists the fixed placements first,
 * so a week re-arrange leaves alone can come back in a different order from
 * the grid's. The pin is part of it, read as eventForPlacement reads it, so a
 * missing flag is unpinned. Each placement has to be matched once, because a
 * group with an extra sitting holds two.
 */
function sameArrangement(a, b) {
  if (!Array.isArray(a) || !Array.isArray(b) || a.length !== b.length) return false;
  const key = (p) => placementKey(p.groupId, p.selectedSessionId) + ' ' + Boolean(p.pinned);
  const counts = new Map();
  for (const p of a) counts.set(key(p), (counts.get(key(p)) || 0) + 1);
  for (const p of b) {
    const left = counts.get(key(p)) || 0;
    if (left === 0) return false;
    counts.set(key(p), left - 1);
  }
  return true;
}
