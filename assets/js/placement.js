'use strict';

/**
 * Choosing which option of each group to put on the calendar.
 *
 * Three operations that look similar and are not. Adding one course has to
 * leave everything already on the grid exactly where it is. Adding several at
 * once cannot just add them one at a time, because greedy insertion is order
 * dependent. Re-optimising is allowed to move things and therefore has to be
 * asked for rather than happening on its own.
 *
 * The rule underneath all three: a placement the student made by hand is
 * pinned, and nothing here may move a pinned placement. That is what makes
 * adding a seventh course safe after they have spent ten minutes arranging the
 * first six.
 */

/**
 * How many alternative arrangements the repair pass may try.
 *
 * Repair is a hill climb over a space that is exponential in the number of
 * menus, so it needs a stop. A few hundred keeps the worst realistic batch
 * under a frame and still clears every clash that one swap can clear.
 */
const REPAIR_ATTEMPT_CAP = 400;

/** Look up option groups by id. */
function indexGroups(groups) {
  return new Map(groups.map((g) => [g.groupId, g]));
}

/**
 * Names one placement, not one group.
 *
 * A group used to hold exactly one placement, so the group id was enough to
 * say which class was meant. Extra sittings ended that: a student who attends
 * two sittings of the same class has two placements in one group, and the
 * session each one shows is what tells them apart.
 */
function placementKey(groupId, sessionId) {
  return String(groupId) + ' ' + String(sessionId);
}

/**
 * The calendar event a placement resolves to, or null if the saved placement
 * points at a group or session the warehouse no longer publishes.
 */
function eventForPlacement(placement, index) {
  const group = index.get(placement.groupId);
  if (!group) return null;
  const session = group.sessions.find(
    (s) => s.sessionId === placement.selectedSessionId
  );
  if (!session) return null;

  return {
    courseKey: group.courseKey,
    groupId: group.groupId,
    type: group.type,
    sessionId: session.sessionId,
    day: session.day,
    startTime: session.startTime,
    endTime: session.endTime,
    room: session.room,
    staff: session.staff,
    streamLabel: session.streamLabel,
    weeks: session.weeks,
    pinned: Boolean(placement.pinned),
  };
}

function eventsFor(placements, index) {
  return placements.map((p) => eventForPlacement(p, index)).filter(Boolean);
}

function countConflicts(placements, index) {
  return findConflicts(eventsFor(placements, index)).length;
}

function _candidateEvent(group, session) {
  return {
    courseKey: group.courseKey,
    groupId: group.groupId,
    day: session.day,
    startTime: session.startTime,
    endTime: session.endTime,
    weeks: session.weeks,
  };
}

/**
 * Pick the option of a group that fits best around what is already there.
 *
 * Ties break on the timetable order the sessions already carry, which is
 * earliest day and then earliest start. Deterministic on purpose: the same
 * course added twice has to land in the same place, or a shared timetable
 * stops being reproducible.
 */
function _chooseSession(group, against) {
  let best = null;
  let bestScore = Infinity;

  for (const session of sessionsInTimetableOrder(group.sessions)) {
    const candidate = _candidateEvent(group, session);
    let score = 0;
    for (const placed of against) {
      if (eventsCollide(candidate, placed)) score += 1;
    }
    // Strictly less than, so the first session at a given score wins and the
    // tie-break stays the timetable order.
    if (score < bestScore) {
      bestScore = score;
      best = session;
      if (score === 0) break;
    }
  }

  return { session: best, conflicts: bestScore };
}

/**
 * Add option groups to a timetable without disturbing it.
 *
 * Existing placements are never read for anything but collision checking and
 * never written, so a student's arrangement survives every add. Spec 8.1.
 */
function placeGroups(existing, incoming, index) {
  const placements = [...existing];
  const placed = [];

  for (const group of incoming) {
    // Scored against everything placed so far, including earlier groups of the
    // same course, so a course does not clash with itself.
    const against = eventsFor(placements, index);
    const { session, conflicts } = _chooseSession(group, against);
    if (!session) continue;

    const placement = {
      courseKey: group.courseKey,
      groupId: group.groupId,
      selectedSessionId: session.sessionId,
      pinned: false,
    };
    placements.push(placement);
    placed.push({
      groupId: group.groupId,
      courseKey: group.courseKey,
      type: group.type,
      sessionId: session.sessionId,
      conflicts,
      options: group.sessions.length,
      // One option and it clashes: the student has to accept it or drop the
      // course, and no amount of rearranging will help.
      unavoidable: conflicts > 0 && group.sessions.length === 1,
      // Every option clashed. Another course moving might still free it, which
      // is what the repair pass in addCourses tries.
      noClearOption: conflicts > 0 && group.sessions.length > 1,
    });
  }

  return { placements, placed };
}

/**
 * How many ways a course could be arranged.
 *
 * Bulk placement puts the most constrained course first, and this is the
 * measure of constraint: a course with a single possible lab has to claim its
 * slot before a course with four, or it will find the slot taken.
 */
function arrangementCount(groups) {
  return groups.reduce((total, g) => total * Math.max(1, g.sessions.length), 1);
}

/**
 * Try other options for this batch's placements until the clashes stop.
 *
 * Only placements added in this batch are moved, and never a pinned one, so
 * repair cannot undo a choice the student made by hand or disturb a course
 * they added earlier.
 */
function _repair(placements, movableGroupIds, index) {
  let current = placements;
  let best = countConflicts(current, index);
  let attempts = 0;

  while (best > 0 && attempts < REPAIR_ATTEMPT_CAP) {
    let improved = false;

    for (const placement of current) {
      if (!movableGroupIds.has(placement.groupId) || placement.pinned) continue;
      const group = index.get(placement.groupId);
      if (!group || group.sessions.length < 2) continue;

      // Sittings the group's other placements show. A group can hold a
      // pinned extra beside the placement being repaired, and moving onto
      // its sitting would collapse the two into a duplicate.
      const occupied = new Set(
        current
          .filter((p) => p !== placement && p.groupId === placement.groupId)
          .map((p) => p.selectedSessionId)
      );

      for (const session of sessionsInTimetableOrder(group.sessions)) {
        if (session.sessionId === placement.selectedSessionId) continue;
        if (occupied.has(session.sessionId)) continue;
        if (attempts >= REPAIR_ATTEMPT_CAP) break;
        attempts += 1;

        // Only this placement moves, never its group-mates: the group id
        // stopped naming a single placement once extra sittings existed.
        const trial = current.map((p) =>
          p === placement
            ? { ...p, selectedSessionId: session.sessionId }
            : p
        );
        const score = countConflicts(trial, index);
        if (score < best) {
          best = score;
          current = trial;
          improved = true;
          break;
        }
      }
      if (best === 0 || attempts >= REPAIR_ATTEMPT_CAP) break;
    }

    if (!improved) break;
  }

  return { placements: current, conflicts: best, attempts };
}

/**
 * Add several courses at once. Spec 8.2.
 *
 * `courseGroups` is a list of { courseKey, groups }. Looping 8.1 over them
 * would make the result depend on the order the student happened to tick the
 * boxes in, so they are sorted by how constrained they are first, and a
 * bounded repair pass cleans up afterwards.
 */
function placeCourses(existing, courseGroups, index) {
  const ordered = [...courseGroups].sort((a, b) => {
    const diff = arrangementCount(a.groups) - arrangementCount(b.groups);
    if (diff !== 0) return diff;
    // Alphabetical last, so two equally constrained courses always place in
    // the same order and a shared timetable reproduces.
    return String(a.courseKey).localeCompare(String(b.courseKey));
  });

  let placements = existing;
  const placed = [];
  for (const course of ordered) {
    const result = placeGroups(placements, course.groups, index);
    placements = result.placements;
    placed.push(...result.placed);
  }

  const batch = new Set(placed.map((p) => p.groupId));
  const before = countConflicts(placements, index);
  const repaired = _repair(placements, batch, index);

  // The per-group counts above were taken as each group went down, so they are
  // stale once repair has moved things. Recount against the final arrangement.
  const finalPlacements = repaired.placements;
  const conflicts = findConflicts(eventsFor(finalPlacements, index));
  const clashingGroups = new Set();
  for (const conflict of conflicts) {
    clashingGroups.add(conflict.a.groupId);
    clashingGroups.add(conflict.b.groupId);
  }

  return {
    placements: finalPlacements,
    placed: placed.map((p) => ({
      ...p,
      selectedSessionId: finalPlacements.find((q) => q.groupId === p.groupId)
        ?.selectedSessionId,
      clashing: clashingGroups.has(p.groupId),
    })),
    summary: {
      courses: ordered.length,
      groups: placed.length,
      conflictsBefore: before,
      conflictsAfter: repaired.conflicts,
      repairAttempts: repaired.attempts,
      repairCapped: repaired.attempts >= REPAIR_ATTEMPT_CAP,
      unavoidable: placed.filter((p) => p.unavoidable).map((p) => p.groupId),
    },
  };
}

/**
 * Work out whether a clash can be got rid of, and how.
 *
 * The distinction the student needs is not how many clashes there are but
 * which ones they can do something about. A clash between two courses that
 * each publish one lecture at the same hour is not a mistake to be corrected,
 * it is a choice between courses.
 *
 * A fix is only offered when moving one side genuinely lowers the total number
 * of clashes, not merely this one: shuffling a lab out of a Monday collision
 * and into a Tuesday one has helped nobody. Pinned placements are never
 * offered as the thing to move, because the student put them there.
 */
function classifyConflicts(placements, index) {
  const conflicts = findConflicts(eventsFor(placements, index));
  if (!conflicts.length) return [];

  const total = conflicts.length;
  // Pinning is per placement, not per group: a student can pin an extra
  // sitting while auto-placement still owns the group's first one.
  const pinned = new Set(
    placements
      .filter(p => p.pinned)
      .map(p => placementKey(p.groupId, p.selectedSessionId))
  );

  return conflicts.map(conflict => {
    let fix = null;
    let alternativesExist = false;

    for (const side of [conflict.a, conflict.b]) {
      if (fix) break;
      const group = index.get(side.groupId);
      if (!group || group.sessions.length < 2) continue;
      alternativesExist = true;
      if (pinned.has(placementKey(side.groupId, side.sessionId))) continue;

      // Sessions the group's other placements already show. Moving onto one
      // of those would collapse two attended sittings into a duplicate.
      const occupied = new Set(
        placements
          .filter(p => p.groupId === side.groupId
            && p.selectedSessionId !== side.sessionId)
          .map(p => p.selectedSessionId)
      );

      for (const session of sessionsInTimetableOrder(group.sessions)) {
        if (session.sessionId === side.sessionId) continue;
        if (occupied.has(session.sessionId)) continue;
        const trial = placements.map(p =>
          p.groupId === side.groupId && p.selectedSessionId === side.sessionId
            ? { ...p, selectedSessionId: session.sessionId }
            : p
        );
        if (countConflicts(trial, index) < total) {
          fix = {
            groupId: side.groupId,
            courseKey: side.courseKey,
            type: side.type,
            sessionId: session.sessionId,
            // Which of the group's placements moves, since there can now be
            // more than one.
            fromSessionId: side.sessionId,
            day: session.day,
            startTime: session.startTime,
            endTime: session.endTime,
            room: session.room,
          };
          break;
        }
      }
    }

    return {
      ...conflict,
      resolvable: Boolean(fix),
      fix,
      // Why there is no button, so the panel can say something more useful
      // than declining to offer one.
      reason: fix
        ? 'fixable'
        : !alternativesExist
          ? 'no-alternative'
          : [conflict.a, conflict.b].every(
              s => pinned.has(placementKey(s.groupId, s.sessionId))
            )
            ? 'pinned'
            : 'no-improvement',
    };
  });
}

/**
 * Mark a placement as the student's own, so nothing moves it again.
 *
 * Called when they drag a class to another slot or pick an option by hand.
 * `fromSessionId` says which of the group's placements moves; a group holds
 * more than one once extra sittings exist. Left undefined, the group's first
 * placement is meant, which is the only one older callers could have.
 */
function pinPlacement(placements, groupId, selectedSessionId, fromSessionId) {
  let moved = false;
  return placements.map((p) => {
    if (moved || p.groupId !== groupId) return p;
    if (fromSessionId !== undefined && p.selectedSessionId !== fromSessionId) {
      return p;
    }
    moved = true;
    return {
      ...p,
      selectedSessionId:
        selectedSessionId === undefined
          ? p.selectedSessionId
          : selectedSessionId,
      pinned: true,
    };
  });
}
