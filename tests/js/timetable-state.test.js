'use strict';

/**
 * The timetable a student is building, and the two sources it comes from.
 */

const test = require('node:test');
const assert = require('node:assert');
const { load, warehouse, course } = require('./harness.js');

const api = load(
  'calendar-utils.js',
  'option-groups.js',
  'placement.js',
  'timetable-state.js'
);
const TimetableState = api.get('TimetableState');
const courseCodeFromTitle = api.get('courseCodeFromTitle');

/** A warehouse response holding just these courses. */
function response(...codes) {
  return {
    publicationId: warehouse.publicationId,
    courses: codes.map(course),
    notFound: [],
  };
}

function stateOf(...codes) {
  const sourceData = TimetableState.fromWarehouseResponse(response(...codes));
  const state = new TimetableState(sourceData);
  state.placeMissing();
  return state;
}

/** An extract response of the shape POST /extract returns. */
function extractResponse(courseTitle, entries) {
  return {
    results: [
      {
        course_title: courseTitle,
        source_file: 'm104178.pdf',
        entries: entries.map((e) => ({
          type: e.type,
          day: e.day,
          start_time: e.start,
          end_time: e.end,
          room: e.room || null,
          staff: e.staff || null,
          group_label: e.label || null,
          weeks: e.weeks || 'W1-W12',
        })),
      },
    ],
  };
}

// Identity across the two sources


test('a course code is read out of an uploaded title', () => {
  assert.equal(
    courseCodeFromTitle('COMP 2601, Computer Architecture'),
    'COMP 2601'
  );
});

test('a parenthetical qualifier is part of the code, not noise', () => {
  // UWI publishes these as two different courses.
  assert.equal(
    courseCodeFromTitle('FOUN 1001 (FULL & PART-TIME), Caribbean Civilisation'),
    'FOUN 1001 (FULL & PART-TIME)'
  );
});

test('a title with a lecturer glued on is not mistaken for a code', () => {
  // "IENG 3017 LALLA,TERRENCE" splits on the comma into something that starts
  // like a code. Keying a course on it would invent a course nobody published.
  assert.equal(courseCodeFromTitle('IENG 3017 LALLA,TERRENCE'), null);
});

test('a title with no code at all falls back rather than guessing', () => {
  assert.equal(courseCodeFromTitle('Timetable for the week'), null);
});

test('the same class from both sources computes the same stream id', () => {
  const fromWarehouse = TimetableState.fromWarehouseResponse(
    response('COMP 1601')
  ).courses[0];
  const lecture = fromWarehouse.sessions.find(
    (s) => s.type === 'Lecture' && s.day === 'Monday' && s.startTime === '12:00'
  );

  const fromUpload = TimetableState.fromExtractResponse(
    extractResponse('COMP 1601, Computer Programming I', [
      { type: 'Lecture', day: 'Monday', start: '12:00', end: '13:00', room: 'TLC LT A1' },
    ])
  ).courses[0];

  assert.equal(fromUpload.courseKey, fromWarehouse.courseKey);
  assert.equal(fromUpload.sessions[0].streamId, lecture.streamId);
});

test('an uploaded course is marked as such, and so is a warehouse one', () => {
  const uploaded = TimetableState.fromExtractResponse(
    extractResponse('COMP 1601, Computer Programming I', [
      { type: 'Lecture', day: 'Monday', start: '12:00', end: '13:00' },
    ])
  );
  const fetched = TimetableState.fromWarehouseResponse(response('COMP 1601'));

  assert.equal(uploaded.courses[0].origin, 'upload');
  assert.equal(fetched.courses[0].origin, 'warehouse');
});

test('uploaded weeks stay printed text, so uploads clash as they always did', () => {
  const uploaded = TimetableState.fromExtractResponse(
    extractResponse('COMP 1601, Computer Programming I', [
      { type: 'Lecture', day: 'Monday', start: '12:00', end: '13:00', weeks: 'W1-W12' },
    ])
  );
  const session = uploaded.courses[0].sessions[0];

  assert.equal(session.weeks, null, 'null reads as every week');
  assert.equal(session.weeksRaw, 'W1-W12');
});

// Placing


test('adding a course places one class per option group', () => {
  const state = stateOf('COMP 1601');

  assert.equal(state.placements.length, state.optionGroups.length);
  assert.equal(state.getPlacedEvents().length, state.optionGroups.length);
});

test('a five course load is placed without a clash', () => {
  const state = stateOf(
    'COMP 1601',
    'COMP 1602',
    'MATH 1115',
    'FOUN 1101',
    'PSYC 1001'
  );

  assert.deepEqual(state.getConflicts(), []);
  assert.ok(state.placements.length <= 25);
});

test('adding a course leaves the others where they were', () => {
  const state = stateOf('COMP 1601');
  const before = JSON.parse(JSON.stringify(state.placements));

  const psyc = TimetableState.fromWarehouseResponse(response('PSYC 1001'))
    .courses[0];
  state.addCourse(psyc);

  for (const original of before) {
    assert.deepEqual(
      state.placements.find((p) => p.groupId === original.groupId),
      original
    );
  }
});

test('adding a course already on the timetable changes nothing', () => {
  const state = stateOf('COMP 1601');
  const before = JSON.parse(JSON.stringify(state.placements));

  const again = TimetableState.fromWarehouseResponse(response('COMP 1601'))
    .courses[0];
  const result = state.addCourse(again);

  assert.deepEqual(result.added, []);
  assert.deepEqual(result.alreadyPresent, ['COMP 1601']);
  assert.deepEqual(state.placements, before);
});

test('removing a course leaves every other placement put', () => {
  const state = stateOf('COMP 1601', 'PSYC 1001');
  const keep = state.placements.filter((p) => p.courseKey === 'COMP 1601');

  state.removeCourse('PSYC 1001');

  assert.deepEqual(state.placements, keep);
  assert.ok(!state.getPlacedEvents().some((e) => e.courseKey === 'PSYC 1001'));
});

test('a removed course can be added back without fetching it again', () => {
  const state = stateOf('COMP 1601', 'PSYC 1001');
  state.removeCourse('PSYC 1001');

  const pooled = state.getCourse('PSYC 1001');
  assert.ok(pooled, 'the course data is kept so undo and re-add are free');
  state.addCourse(pooled);

  assert.ok(state.getPlacedEvents().some((e) => e.courseKey === 'PSYC 1001'));
});

// Pinning


test('choosing an option by hand pins it', () => {
  const state = stateOf('COMP 1601');
  const menu = state.optionGroups.find((g) => g.sessions.length > 1);
  const target = menu.sessions[4].sessionId;

  state.moveEvent(menu.groupId, target);

  const placement = state.placements.find((p) => p.groupId === menu.groupId);
  assert.equal(placement.selectedSessionId, target);
  assert.equal(placement.pinned, true);
});

test('re-optimising does not move what the student pinned', () => {
  const state = stateOf('COMP 1601', 'PSYC 1001');
  const menu = state.optionGroups.find((g) => g.sessions.length > 1);
  const target = menu.sessions[4].sessionId;
  state.moveEvent(menu.groupId, target);

  state.reoptimise();

  const placement = state.placements.find((p) => p.groupId === menu.groupId);
  assert.equal(placement.selectedSessionId, target);
  assert.equal(placement.pinned, true);
});

test('re-optimising still places everything', () => {
  const state = stateOf('COMP 1601', 'MATH 1115');
  const groups = state.optionGroups.length;

  state.reoptimise();

  assert.equal(state.placements.length, groups);
});

// The student's override


test('an override regroups the course and replaces its placements', () => {
  const state = stateOf('AGBU 1005');
  const lectures = () =>
    state.optionGroups.filter((g) => g.type === 'Lecture');
  assert.equal(lectures().length, 2);

  state.setOptionGroupOverride('AGBU 1005', 'Lecture', 'menu');

  assert.equal(lectures().length, 1);
  const placed = state.placements.filter((p) =>
    p.groupId.startsWith('AGBU 1005|Lecture')
  );
  assert.equal(placed.length, 1);
  assert.ok(state.getPlacedEventDetails(placed[0].groupId));
});

test('an override leaves no placement pointing at a group that is gone', () => {
  const state = stateOf('AGBU 1005');

  state.setOptionGroupOverride('AGBU 1005', 'Lecture', 'menu');

  const ids = new Set(state.optionGroups.map((g) => g.groupId));
  assert.ok(state.placements.every((p) => ids.has(p.groupId)));
});

// History


test('undo takes back a whole course, not one class', () => {
  const state = stateOf('COMP 1601');
  const before = JSON.parse(JSON.stringify(state.placements));

  const psyc = TimetableState.fromWarehouseResponse(response('PSYC 1001'))
    .courses[0];
  state.addCourse(psyc);
  assert.ok(state.placements.length > before.length);

  state.undo();

  assert.deepEqual(state.placements, before);
  assert.ok(!state.courseKeys.includes('PSYC 1001'));
});

test('undo takes back a bulk add in one step', () => {
  const state = stateOf('COMP 1601');
  const before = state.placements.length;

  const added = ['PSYC 1001', 'MATH 1115'].map(
    (c) => TimetableState.fromWarehouseResponse(response(c)).courses[0]
  );
  state.addCourses(added);
  assert.ok(state.placements.length > before);

  state.undo();

  assert.equal(state.placements.length, before);
  assert.deepEqual(state.courseKeys, ['COMP 1601']);
});

test('undo puts a removed course back', () => {
  const state = stateOf('COMP 1601', 'PSYC 1001');
  const before = JSON.parse(JSON.stringify(state.placements));

  state.removeCourse('PSYC 1001');
  state.undo();

  assert.deepEqual(state.placements, before);
  assert.ok(state.courseKeys.includes('PSYC 1001'));
});

test('redo puts back what undo took away', () => {
  const state = stateOf('COMP 1601');
  const psyc = TimetableState.fromWarehouseResponse(response('PSYC 1001'))
    .courses[0];
  state.addCourse(psyc);
  const after = JSON.parse(JSON.stringify(state.placements));

  state.undo();
  state.redo();

  assert.deepEqual(state.placements, after);
});

test('nothing to undo is answered honestly', () => {
  const state = stateOf('COMP 1601');
  assert.equal(state.canRedo(), false);
  while (state.canUndo()) state.undo();
  assert.equal(state.undo(), false);
});

// Clashes, and what can be done about them


test('the siblings of a group are the rest of its course and type', () => {
  const state = stateOf('AGBU 1005');
  const lectures = state.optionGroups.filter((g) => g.type === 'Lecture');
  assert.equal(lectures.length, 2);

  const siblings = state.getSiblingGroups(lectures[0].groupId);

  assert.deepEqual(
    siblings.map((g) => g.groupId),
    [lectures[1].groupId]
  );
});

test('a group with nothing beside it has no siblings to merge with', () => {
  const state = stateOf('FOUN 1101');
  const [menu] = state.optionGroups.filter((g) => g.type === 'Tutorial');

  assert.deepEqual(state.getSiblingGroups(menu.groupId), []);
});

test('a clash-free timetable classifies to no clashes at all', () => {
  const state = stateOf('COMP 1601', 'COMP 1602');

  assert.deepEqual(state.getClassifiedConflicts(), []);
});

test('applying a fix moves the class and pins it there', () => {
  const state = stateOf('COMP 1601');
  const menu = state.optionGroups.find((g) => g.sessions.length > 1);
  const target = menu.sessions[3].sessionId;

  const applied = state.applyFix({ groupId: menu.groupId, sessionId: target });

  assert.equal(applied, true);
  const placement = state.placements.find((p) => p.groupId === menu.groupId);
  assert.equal(placement.selectedSessionId, target);
  assert.equal(placement.pinned, true, 'a fix is the student choosing');
});

test('applying nothing does nothing', () => {
  const state = stateOf('COMP 1601');
  const before = JSON.parse(JSON.stringify(state.placements));

  assert.equal(state.applyFix(null), false);
  assert.deepEqual(state.placements, before);
});

// The warehouse moving underneath a saved timetable


test('only warehouse courses are offered for refresh', () => {
  const state = stateOf('COMP 1601');
  const uploaded = TimetableState.fromExtractResponse(
    extractResponse('ZZZZ 9999, Something Unpublished', [
      { type: 'Lecture', day: 'Monday', start: '08:00', end: '09:00' },
    ])
  );
  state.addCourse(uploaded.courses[0]);

  assert.deepEqual(state.warehouseCourseKeys, ['COMP 1601']);
});

test('a refresh keeps a placement that still resolves', () => {
  const state = stateOf('COMP 1601');
  const before = JSON.parse(JSON.stringify(state.placements));

  const again = TimetableState.fromWarehouseResponse(response('COMP 1601'));
  state.refreshFromWarehouse(again.courses, [], 2);

  assert.deepEqual(state.placements, before);
  assert.equal(state.publicationId, 2);
});

test('a placement whose class is gone is refilled, not left dangling', () => {
  const state = stateOf('COMP 1601');
  const lectureGroup = state.optionGroups.find(
    (g) => g.type === 'Lecture' && g.sessions.length === 1
  );

  // The new publication drops that one lecture.
  const trimmed = TimetableState.fromWarehouseResponse(response('COMP 1601'));
  const goneId = lectureGroup.sessions[0].sessionId;
  trimmed.courses[0].sessions = trimmed.courses[0].sessions.filter(
    (s) => s.sessionId !== goneId
  );

  const result = state.refreshFromWarehouse(trimmed.courses, [], 2);

  assert.equal(result.moved, 1);
  const ids = new Set(state.optionGroups.map((g) => g.groupId));
  assert.ok(state.placements.every((p) => ids.has(p.groupId)));
});

test('a refresh does not disturb anything the student pinned', () => {
  const state = stateOf('COMP 1601');
  const menu = state.optionGroups.find((g) => g.sessions.length > 1);
  const chosen = menu.sessions[4].sessionId;
  state.moveEvent(menu.groupId, chosen);

  const again = TimetableState.fromWarehouseResponse(response('COMP 1601'));
  state.refreshFromWarehouse(again.courses, [], 2);

  const placement = state.placements.find((p) => p.groupId === menu.groupId);
  assert.equal(placement.selectedSessionId, chosen);
  assert.equal(placement.pinned, true);
});

test('a course the new publication drops is kept and marked stale', () => {
  /**
   * A withdrawn code is far likelier than a student abandoning the course,
   * and emptying part of their timetable would be the worse mistake.
   */
  const state = stateOf('COMP 1601', 'PSYC 1001');
  const still = TimetableState.fromWarehouseResponse(response('COMP 1601'));

  const result = state.refreshFromWarehouse(still.courses, ['PSYC 1001'], 2);

  assert.deepEqual(result.stale, ['PSYC 1001']);
  assert.equal(state.getCourse('PSYC 1001').stale, true);
  assert.ok(state.courseKeys.includes('PSYC 1001'));
  assert.ok(state.getPlacedEvents().some((e) => e.courseKey === 'PSYC 1001'));
});

test('a refresh can be undone like anything else', () => {
  const state = stateOf('COMP 1601');
  const before = JSON.parse(JSON.stringify(state.placements));

  const again = TimetableState.fromWarehouseResponse(response('COMP 1601'));
  again.courses[0].sessions = again.courses[0].sessions.slice(0, 3);
  state.refreshFromWarehouse(again.courses, [], 2);
  state.undo();

  assert.deepEqual(state.placements, before);
});

// Detail panel


test('a placed class reports everything the detail panel shows', () => {
  const state = stateOf('BIOL 1262');
  const groupId = state.placements[0].groupId;

  const details = state.getPlacedEventDetails(groupId);

  assert.equal(details.courseTitle, 'Living Organisms I');
  assert.equal(details.origin, 'warehouse');
  assert.ok(details.day);
  assert.ok(Array.isArray(details.staff));
  assert.ok(details.optionCount >= 1);
  assert.equal(typeof details.pinned, 'boolean');
});

test('asking about a class that is not placed returns nothing, not a crash', () => {
  const state = stateOf('COMP 1601');
  assert.equal(state.getPlacedEventDetails('NOPE|Lecture|all'), null);
});
