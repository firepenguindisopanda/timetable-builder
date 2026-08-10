'use strict';

/**
 * What counts as one class.
 *
 * A student attends one lecture, one lab and one tutorial per course per week,
 * so every sitting of a type is a choice rather than an obligation. That rule
 * is institutional and not visible in the data, which is exactly why it is
 * pinned here against real courses from the publication of 6 August 2026.
 */

const test = require('node:test');
const assert = require('node:assert');
const { load, course, sessionsOfType } = require('./harness.js');

const api = load('calendar-utils.js', 'option-groups.js');
const deriveOptionGroups = api.get('deriveOptionGroups');
const isMenu = api.get('isMenu');

/** A fixture course in the shape the state layer hands to the grouper. */
function pick(code, ...types) {
  const found = course(code);
  const sessions = types.length
    ? found.sessions.filter((s) => types.includes(s.type))
    : found.sessions;
  return { courseKey: code, title: found.title, sessions };
}

function groupsFor(code, ...types) {
  return deriveOptionGroups(pick(code, ...types));
}

// One of each per week


test('a course with one sitting of a type gets one placement', () => {
  const groups = groupsFor('COMP 3613', 'Lecture');

  assert.equal(groups.length, 1);
  assert.equal(groups[0].reason, 'single');
  assert.equal(isMenu(groups[0]), false);
});

test('several lectures a week are one choice, not several obligations', () => {
  /**
   * The case a student reported from the deployed app. COMP 1601 publishes
   * five lecture sittings; reading them as four separate classes put
   * seventeen blocks on a five-course timetable that should hold ten.
   */
  const lectures = sessionsOfType('COMP 1601', 'Lecture');
  assert.equal(lectures.length, 5);

  const groups = groupsFor('COMP 1601', 'Lecture');

  assert.equal(groups.length, 1);
  assert.equal(groups[0].sessions.length, 5);
  assert.equal(groups[0].reason, 'sittings');
  assert.equal(isMenu(groups[0]), true);
});

test('a Monday and Wednesday lecture pair is one choice of two sittings', () => {
  const groups = groupsFor('AGBU 1005', 'Lecture');

  assert.equal(groups.length, 1);
  assert.deepEqual(
    groups[0].sessions.map((s) => s.day),
    ['Monday', 'Wednesday']
  );
});

test('a large cohort is one choice too, however many sittings it has', () => {
  const tutorials = sessionsOfType('FOUN 1101', 'Tutorial');
  assert.equal(tutorials.length, 33);

  const groups = groupsFor('FOUN 1101', 'Tutorial');

  assert.equal(groups.length, 1);
  assert.equal(groups[0].sessions.length, 33);
});

test('stream labels do not split a type into separate classes', () => {
  // BIOL 2061 labels its five tutorials T1 to T5. They were already one
  // choice; the point is that partial labelling cannot change that either.
  assert.equal(groupsFor('BIOL 2061', 'Tutorial').length, 1);
  assert.equal(groupsFor('CHEM 2470', 'Tutorial').length, 1);
});

test('each activity type is its own placement', () => {
  const groups = groupsFor('COMP 1601');

  assert.deepEqual(groups.map((g) => g.type), ['Lab', 'Lecture']);
  assert.equal(groups.length, 2);
});

test('a whole course reduces to one block per type', () => {
  // Two types each, so two blocks each, which is what a student expects.
  const perCourse = ['COMP 1601', 'COMP 1602', 'AGBU 1005']
    .map((code) => groupsFor(code).length);

  assert.deepEqual(perCourse, [2, 2, 2]);
});

// Group identity


test('group ids do not depend on the order sessions arrived in', () => {
  const forward = groupsFor('COMP 1601');
  const shuffled = deriveOptionGroups({
    courseKey: 'COMP 1601',
    sessions: [...course('COMP 1601').sessions].reverse(),
  });

  assert.deepEqual(
    shuffled.map((g) => g.groupId).sort(),
    forward.map((g) => g.groupId).sort()
  );
});

test('every group id in a course is distinct', () => {
  for (const code of ['COMP 1601', 'BIOL 1262', 'MATH 1115', 'PSYC 1001']) {
    const ids = groupsFor(code).map((g) => g.groupId);
    assert.equal(new Set(ids).size, ids.length, code);
  }
});

test('a group id names the course and the activity type', () => {
  const [group] = groupsFor('FOUN 1101', 'Tutorial');

  assert.equal(group.groupId, 'FOUN 1101|Tutorial|all');
  assert.equal(group.courseKey, 'FOUN 1101');
  assert.equal(group.type, 'Tutorial');
});

// Awkward data


test('an unpublished activity type does not lose the session', () => {
  // Five sessions campus-wide arrive with no activity type at all.
  const [first, ...rest] = course('COMP 1602').sessions;
  const groups = deriveOptionGroups({
    courseKey: 'COMP 1602',
    sessions: [{ ...first, type: null }, ...rest],
  });

  const placed = groups.flatMap((g) => g.sessions);
  assert.equal(placed.length, course('COMP 1602').sessions.length);
  assert.ok(groups.some((g) => g.type === 'Unspecified'));
});

test('an activity type outside the familiar six is carried, not flattened', () => {
  // PSYC 1001 publishes "Lecture Relocated" and
  // "Tutorial (make-up/relocated)" alongside the ordinary ones.
  const types = new Set(groupsFor('PSYC 1001').map((g) => g.type));

  assert.ok(types.has('Lecture Relocated'));
  assert.ok(types.has('Tutorial (make-up/relocated)'));
});

test('a course with no sessions produces no groups', () => {
  assert.deepEqual(deriveOptionGroups({ courseKey: 'X', sessions: [] }), []);
  assert.deepEqual(deriveOptionGroups({ courseKey: 'X' }), []);
});

// The student's override


test('a student can say this course runs several of these a week', () => {
  const before = groupsFor('FOUN 1101', 'Tutorial');
  assert.equal(before.length, 1);

  const after = deriveOptionGroups(pick('FOUN 1101', 'Tutorial'), {
    'FOUN 1101|Tutorial': 'split',
  });

  assert.equal(after.length, 33);
});

test('splitting still keeps sittings that overlap as one choice', () => {
  // COMP 1601 runs two Tuesday 12:00 lectures in different rooms. Even split
  // apart, nobody can attend both.
  const after = deriveOptionGroups(pick('COMP 1601', 'Lecture'), {
    'COMP 1601|Lecture': 'split',
  });

  assert.equal(after.length, 4);
  const tuesday = after.find((g) => g.sessions[0].day === 'Tuesday');
  assert.equal(tuesday.sessions.length, 2);
  assert.equal(tuesday.reason, 'overlap');
});

test('an override for one type leaves the others alone', () => {
  const groups = deriveOptionGroups(pick('COMP 1601'), {
    'COMP 1601|Lecture': 'split',
  });

  assert.ok(groups.filter((g) => g.type === 'Lecture').length > 1);
  assert.equal(groups.filter((g) => g.type === 'Lab').length, 1);
  assert.equal(groups.filter((g) => g.type === 'Lab')[0].reason, 'sittings');
});
