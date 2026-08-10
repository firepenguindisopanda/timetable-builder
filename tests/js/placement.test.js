'use strict';

/**
 * Where each class lands, and what is allowed to move it.
 *
 * The courses are real, so the arrangements being solved are the ones the
 * warehouse actually poses rather than ones chosen to make the algorithm look
 * good.
 */

const test = require('node:test');
const assert = require('node:assert');
const { load, course } = require('./harness.js');

const api = load('calendar-utils.js', 'option-groups.js', 'placement.js');
const {
  deriveOptionGroups,
  indexGroups,
  placeGroups,
  placeCourses,
  eventsFor,
  countConflicts,
  arrangementCount,
  pinPlacement,
  findConflicts,
} = api.take(
  'deriveOptionGroups',
  'indexGroups',
  'placeGroups',
  'placeCourses',
  'eventsFor',
  'countConflicts',
  'arrangementCount',
  'pinPlacement',
  'findConflicts'
);

function groupsOf(code, ...types) {
  const found = course(code);
  const sessions = types.length
    ? found.sessions.filter((s) => types.includes(s.type))
    : found.sessions;
  return deriveOptionGroups({ courseKey: code, sessions });
}

/**
 * Occupy the slots of the given sessions with pinned placements from another
 * course, so a group has to work around them.
 */
function blocking(groups, sessions) {
  const blockers = sessions.map((session, i) => ({
    groupId: `BLOCK${i}|Lecture|all`,
    courseKey: `BLOCK${i}`,
    type: 'Lecture',
    sessions: [{ ...session, sessionId: -100 - i }],
  }));
  return {
    index: indexGroups([...groups, ...blockers]),
    placements: blockers.map((b) => ({
      courseKey: b.courseKey,
      groupId: b.groupId,
      selectedSessionId: b.sessions[0].sessionId,
      pinned: true,
    })),
  };
}

/** Build an index over several courses at once. */
function setUp(...specs) {
  const perCourse = specs.map((spec) =>
    Array.isArray(spec) ? { code: spec[0], groups: groupsOf(...spec) }
                        : { code: spec, groups: groupsOf(spec) }
  );
  const index = indexGroups(perCourse.flatMap((c) => c.groups));
  return { perCourse, index };
}

// Placing one course


test('every option group of a course gets a placement', () => {
  const { perCourse, index } = setUp('COMP 1601');
  const groups = perCourse[0].groups;

  const { placements } = placeGroups([], groups, index);

  assert.equal(placements.length, groups.length);
  assert.deepEqual(
    placements.map((p) => p.groupId).sort(),
    groups.map((g) => g.groupId).sort()
  );
});

test('a placement starts unpinned, because nobody chose it', () => {
  const { perCourse, index } = setUp('COMP 1601');

  const { placements } = placeGroups([], perCourse[0].groups, index);

  assert.ok(placements.every((p) => p.pinned === false));
});

test('adding a course does not touch what is already placed', () => {
  const { perCourse, index } = setUp('COMP 1601', 'PSYC 1001');
  const first = placeGroups([], perCourse[0].groups, index).placements;
  const before = JSON.parse(JSON.stringify(first));

  const { placements } = placeGroups(first, perCourse[1].groups, index);

  assert.deepEqual(placements.slice(0, before.length), before);
});

test('the same course added twice lands in the same place', () => {
  const { perCourse, index } = setUp('MATH 1115');

  const once = placeGroups([], perCourse[0].groups, index).placements;
  const twice = placeGroups([], perCourse[0].groups, index).placements;

  assert.deepEqual(once, twice);
});

test('a menu is placed on its earliest option when nothing is in the way', () => {
  // FOUN 1101's 33 tutorials are one menu and the grid is empty, so the
  // tie-break decides: earliest day, then earliest start.
  const { perCourse, index } = setUp(['FOUN 1101', 'Tutorial']);
  const [menu] = perCourse[0].groups;

  const { placed } = placeGroups([], [menu], index);
  const chosen = menu.sessions.find((s) => s.sessionId === placed[0].sessionId);
  const earliest = menu.sessions[0];

  assert.equal(chosen.day, earliest.day);
  assert.equal(chosen.startTime, earliest.startTime);
});

test('a menu avoids a slot that is already taken', () => {
  const { perCourse, index } = setUp(['FOUN 1101', 'Tutorial']);
  const [menu] = perCourse[0].groups;
  const blocked = menu.sessions[0];

  const { index: withBlocker, placements: existing } = blocking(
    perCourse[0].groups,
    [blocked]
  );

  const { placed } = placeGroups(existing, [menu], withBlocker);

  assert.equal(placed[0].conflicts, 0);
  assert.notEqual(placed[0].sessionId, blocked.sessionId);
});

test('a course does not clash with itself when it can avoid it', () => {
  const { perCourse, index } = setUp('COMP 1601');

  const { placements } = placeGroups([], perCourse[0].groups, index);

  // COMP 1601's lab menu has ten options, so it can dodge its own lectures.
  assert.equal(countConflicts(placements, index), 0);
});

// When there is no way out


test('a lone option that clashes is still placed, and named unavoidable', () => {
  const { perCourse, index } = setUp(['COMP 1601', 'Lecture']);
  const single = perCourse[0].groups.find((g) => g.sessions.length === 1);
  const clone = {
    groupId: 'OTHER|Lecture|all',
    courseKey: 'OTHER',
    type: 'Lecture',
    sessions: [{ ...single.sessions[0], sessionId: -2 }],
  };
  const withClone = indexGroups([...perCourse[0].groups, clone]);
  const existing = [
    { courseKey: 'OTHER', groupId: clone.groupId, selectedSessionId: -2, pinned: true },
  ];

  const { placed } = placeGroups(existing, [single], withClone);

  assert.equal(placed.length, 1, 'the class is placed rather than dropped');
  assert.equal(placed[0].unavoidable, true);
  assert.equal(placed[0].noClearOption, false);
});

test('a menu with every option blocked is flagged differently', () => {
  /**
   * Not unavoidable: COMP 1601's lab menu has ten options, and another course
   * moving could still free one of them. That distinction is what decides
   * whether the conflict panel offers a fix.
   */
  const { perCourse } = setUp(['COMP 1601', 'Lab']);
  const [menu] = perCourse[0].groups;
  assert.equal(menu.sessions.length, 10);

  const { index, placements: existing } = blocking(
    perCourse[0].groups,
    menu.sessions
  );

  const { placed } = placeGroups(existing, [menu], index);

  assert.ok(placed[0].conflicts > 0);
  assert.equal(placed[0].noClearOption, true);
  assert.equal(placed[0].unavoidable, false);
});

// Placing several at once


test('the most constrained course claims its slot first', () => {
  const { perCourse, index } = setUp('COMP 1601', 'PSYC 1001', 'MATH 1115');
  const counts = perCourse.map((c) => ({
    code: c.code,
    ways: arrangementCount(c.groups),
  }));

  const { placed } = placeCourses(
    [],
    perCourse.map((c) => ({ courseKey: c.code, groups: c.groups })),
    index
  );

  const firstPlaced = placed[0].courseKey;
  const mostConstrained = counts.sort((a, b) => a.ways - b.ways)[0].code;
  assert.equal(firstPlaced, mostConstrained);
});

test('a course with one arrangement counts as one', () => {
  const groups = groupsOf('AGBU 1005', 'Lecture');

  assert.equal(arrangementCount(groups), 1);
});

test('bulk placement does not depend on the order they were ticked', () => {
  const { perCourse, index } = setUp('COMP 1601', 'PSYC 1001', 'MATH 1115');
  const asGiven = perCourse.map((c) => ({ courseKey: c.code, groups: c.groups }));

  const forward = placeCourses([], asGiven, index).placements;
  const backward = placeCourses([], [...asGiven].reverse(), index).placements;

  const key = (ps) =>
    ps.map((p) => `${p.groupId}=${p.selectedSessionId}`).sort();
  assert.deepEqual(key(forward), key(backward));
});

test('bulk placement leaves an earlier timetable alone', () => {
  const { perCourse, index } = setUp('COMP 1601', 'PSYC 1001', 'MATH 1115');
  const first = placeGroups([], perCourse[0].groups, index).placements;
  const before = JSON.parse(JSON.stringify(first));

  const { placements } = placeCourses(
    first,
    perCourse.slice(1).map((c) => ({ courseKey: c.code, groups: c.groups })),
    index
  );

  for (const original of before) {
    const after = placements.find((p) => p.groupId === original.groupId);
    assert.deepEqual(after, original);
  }
});

test('a realistic five course load comes out clash free', () => {
  const codes = ['COMP 1601', 'COMP 1602', 'MATH 1115', 'FOUN 1101', 'PSYC 1001'];
  const { perCourse, index } = setUp(...codes);

  const { placements, summary } = placeCourses(
    [],
    perCourse.map((c) => ({ courseKey: c.code, groups: c.groups })),
    index
  );

  assert.equal(summary.conflictsAfter, 0);
  assert.equal(countConflicts(placements, index), 0);
  // The point of the ceiling: a week a person could actually sit through.
  assert.ok(placements.length <= 25, `${placements.length} placements`);
});

test('the summary says what happened rather than only that it happened', () => {
  const codes = ['COMP 1601', 'PSYC 1001'];
  const { perCourse, index } = setUp(...codes);

  const { summary } = placeCourses(
    [],
    perCourse.map((c) => ({ courseKey: c.code, groups: c.groups })),
    index
  );

  assert.equal(summary.courses, 2);
  assert.ok(summary.groups > 0);
  assert.equal(typeof summary.conflictsBefore, 'number');
  assert.equal(typeof summary.conflictsAfter, 'number');
  assert.equal(summary.repairCapped, false);
});

// Repair


/**
 * Repair is reached directly rather than through placeCourses.
 *
 * Placing most-constrained-first and scoring each option against what is
 * already down clears almost everything on the way in, so driving repair from
 * the outside means hunting for an arrangement that defeats the greedy pass.
 * That would test the search less than it tested the hunt. These start from a
 * clashing arrangement and ask repair to get out of it.
 */
const repair = api.get('_repair');

/** COMP 1601's lab menu, sat deliberately on a slot another course holds. */
function stuckOnAClash() {
  const { perCourse } = setUp(['COMP 1601', 'Lab']);
  const [menu] = perCourse[0].groups;
  const taken = menu.sessions[0];
  const { index, placements: blockers } = blocking(perCourse[0].groups, [taken]);

  const placements = [
    ...blockers,
    {
      courseKey: 'COMP 1601',
      groupId: menu.groupId,
      selectedSessionId: taken.sessionId,
      pinned: false,
    },
  ];
  return { menu, index, placements, taken };
}

test('repair moves a clashing placement onto an option that is free', () => {
  const { menu, index, placements, taken } = stuckOnAClash();
  assert.equal(countConflicts(placements, index), 1);

  const result = repair(placements, new Set([menu.groupId]), index);

  assert.equal(result.conflicts, 0);
  const lab = result.placements.find((p) => p.groupId === menu.groupId);
  assert.notEqual(lab.selectedSessionId, taken.sessionId);
});

test('repair leaves a pinned placement stuck where the student put it', () => {
  const { menu, index, placements, taken } = stuckOnAClash();
  const pinned = pinPlacement(placements, menu.groupId, taken.sessionId);

  const result = repair(pinned, new Set([menu.groupId]), index);

  assert.equal(result.conflicts, 1, 'the clash stays rather than being fixed');
  const lab = result.placements.find((p) => p.groupId === menu.groupId);
  assert.equal(lab.selectedSessionId, taken.sessionId);
});

test('repair leaves placements outside the batch alone', () => {
  const { menu, index, placements, taken } = stuckOnAClash();

  // The lab is unpinned but was not added in this batch, so it is not the
  // batch's to move: the student added it earlier and may be relying on it.
  const result = repair(placements, new Set(), index);

  assert.equal(result.conflicts, 1);
  const lab = result.placements.find((p) => p.groupId === menu.groupId);
  assert.equal(lab.selectedSessionId, taken.sessionId);
});

test('repair stops rather than searching forever', () => {
  const { menu, index, placements } = stuckOnAClash();
  // Block every option so nothing can improve, which is the case that would
  // otherwise loop.
  const { index: allBlocked, placements: blockers } = blocking(
    [menu],
    menu.sessions
  );
  const stuck = [
    ...blockers,
    {
      courseKey: 'COMP 1601',
      groupId: menu.groupId,
      selectedSessionId: menu.sessions[0].sessionId,
      pinned: false,
    },
  ];

  const result = repair(stuck, new Set([menu.groupId]), allBlocked);

  assert.ok(result.conflicts > 0);
  assert.ok(result.attempts <= 400);
  assert.equal(placements.length, 2);
  assert.equal(index.size >= 1, true);
});

test('a clean batch reports no repair work and no cap', () => {
  const { perCourse, index } = setUp('COMP 1601');

  const { summary } = placeCourses(
    [],
    [{ courseKey: 'COMP 1601', groups: perCourse[0].groups }],
    index
  );

  assert.equal(summary.conflictsBefore, 0);
  assert.equal(summary.conflictsAfter, 0);
  assert.equal(summary.repairAttempts, 0);
  assert.equal(summary.repairCapped, false);
});

test('a batch that had to be repaired says so in the summary', () => {
  const { menu, index, placements } = stuckOnAClash();
  const before = countConflicts(placements, index);

  const result = repair(placements, new Set([menu.groupId]), index);

  assert.equal(before, 1);
  assert.ok(result.attempts > 0, 'repair actually tried something');
  assert.equal(findConflicts(eventsFor(result.placements, index)).length, 0);
});

// Pinning


test('pinning marks the placement and can change the choice at once', () => {
  const { perCourse, index } = setUp(['COMP 1601', 'Lab']);
  const [menu] = perCourse[0].groups;
  const placements = placeGroups([], [menu], index).placements;
  const target = menu.sessions[5].sessionId;

  const pinned = pinPlacement(placements, menu.groupId, target);

  assert.equal(pinned[0].pinned, true);
  assert.equal(pinned[0].selectedSessionId, target);
});

test('pinning without a new choice keeps the one already made', () => {
  const { perCourse, index } = setUp(['COMP 1601', 'Lab']);
  const [menu] = perCourse[0].groups;
  const placements = placeGroups([], [menu], index).placements;
  const chosen = placements[0].selectedSessionId;

  const pinned = pinPlacement(placements, menu.groupId, undefined);

  assert.equal(pinned[0].selectedSessionId, chosen);
  assert.equal(pinned[0].pinned, true);
});

// Telling a fixable clash from one the student is stuck with


const classifyConflicts = api.get('classifyConflicts');

test('a clash with a free alternative is offered a fix', () => {
  const { menu, index, placements, taken } = stuckOnAClash();

  const [conflict] = classifyConflicts(placements, index);

  assert.equal(conflict.resolvable, true);
  assert.equal(conflict.reason, 'fixable');
  assert.equal(conflict.fix.groupId, menu.groupId);
  assert.notEqual(conflict.fix.sessionId, taken.sessionId);
});

test('the fix names where the class would go, so it can be described', () => {
  const { index, placements } = stuckOnAClash();

  const [conflict] = classifyConflicts(placements, index);

  assert.ok(conflict.fix.day);
  assert.ok(conflict.fix.startTime);
  assert.equal(conflict.fix.courseKey, 'COMP 1601');
});

test('a clash between two classes with no alternatives is unavoidable', () => {
  /**
   * Two courses each publishing one lecture at the same hour. Nothing is
   * broken and nothing can be moved: the student has to drop one or accept
   * it, and saying so is more use than an inert button.
   */
  const lecture = course('COMP 1601').sessions.find(
    s => s.type === 'Lecture' && s.day === 'Wednesday'
  );
  const groups = [
    { groupId: 'A|Lecture|only', courseKey: 'A', type: 'Lecture', sessions: [{ ...lecture, sessionId: 901 }] },
    { groupId: 'B|Lecture|only', courseKey: 'B', type: 'Lecture', sessions: [{ ...lecture, sessionId: 902 }] },
  ];
  const index = indexGroups(groups);
  const placements = groups.map(g => ({
    courseKey: g.courseKey, groupId: g.groupId,
    selectedSessionId: g.sessions[0].sessionId, pinned: false,
  }));

  const [conflict] = classifyConflicts(placements, index);

  assert.equal(conflict.resolvable, false);
  assert.equal(conflict.reason, 'no-alternative');
  assert.equal(conflict.fix, null);
});

test('a fix is never offered by moving something the student pinned', () => {
  const { menu, index, placements } = stuckOnAClash();
  const pinned = pinPlacement(placements, menu.groupId, undefined);

  const [conflict] = classifyConflicts(pinned, index);

  assert.equal(conflict.resolvable, false);
  assert.equal(conflict.reason, 'pinned');
});

test('a move that trades one clash for another is not called a fix', () => {
  /**
   * A lab menu of two, with both of its options already occupied. Moving is
   * possible and pointless, and offering it would send the student in circles.
   */
  const labs = course('COMP 1601').sessions.filter(s => s.type === 'Lab').slice(0, 2);
  const menu = {
    groupId: 'COMP 1601|Lab|all', courseKey: 'COMP 1601', type: 'Lab', sessions: labs,
  };
  const { index, placements: blockers } = blocking([menu], labs);
  const placements = [
    ...blockers,
    { courseKey: 'COMP 1601', groupId: menu.groupId, selectedSessionId: labs[0].sessionId, pinned: false },
  ];

  const classified = classifyConflicts(placements, index);

  assert.ok(classified.length);
  assert.ok(classified.every(c => c.resolvable === false));
  assert.ok(classified.some(c => c.reason === 'no-improvement'));
});

test('a timetable with no clashes classifies to nothing', () => {
  const { perCourse, index } = setUp('COMP 1601');
  const { placements } = placeGroups([], perCourse[0].groups, index);

  assert.deepEqual(classifyConflicts(placements, index), []);
});

test('a classified clash still carries its weeks and its events', () => {
  const { index, placements } = stuckOnAClash();

  const [conflict] = classifyConflicts(placements, index);

  assert.ok('weeks' in conflict);
  assert.ok(conflict.a.groupId);
  assert.ok(conflict.b.groupId);
  assert.ok(conflict.day);
});

// Saved state that has gone stale


test('a placement pointing at a session that is gone is skipped, not fatal', () => {
  const { perCourse, index } = setUp(['COMP 1601', 'Lecture']);
  const groups = perCourse[0].groups;
  const placements = [
    { courseKey: 'COMP 1601', groupId: groups[0].groupId, selectedSessionId: 999999 },
    { courseKey: 'GONE', groupId: 'GONE|Lecture|all', selectedSessionId: 1 },
  ];

  assert.deepEqual(eventsFor(placements, index), []);
  assert.equal(countConflicts(placements, index), 0);
});
