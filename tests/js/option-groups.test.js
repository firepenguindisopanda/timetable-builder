'use strict';

/**
 * What counts as one class.
 *
 * Every fixture below is a real course from the publication of 6 August 2026,
 * because the whole question these rules answer is what the university
 * actually publishes, and invented data would only test the rules against
 * themselves.
 */

const test = require('node:test');
const assert = require('node:assert');
const { load, course, sessionsOfType } = require('./harness.js');

const api = load('calendar-utils.js', 'option-groups.js');
const deriveOptionGroups = api.get('deriveOptionGroups');
const isMenu = api.get('isMenu');
const MENU_CEILING_HOURS = api.get('MENU_CEILING_HOURS');

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

function hoursOf(sessions) {
  const timeToMins = api.get('timeToMins');
  return (
    sessions.reduce(
      (t, s) => t + timeToMins(s.endTime) - timeToMins(s.startTime),
      0
    ) / 60
  );
}

// Nothing to decide


test('a course with one session of a type gets one group holding it', () => {
  const groups = groupsFor('COMP 1602', 'Lecture').filter(
    (g) => g.sessions.length === 1
  );

  assert.ok(groups.length >= 1);
  assert.equal(groups[0].reason, 'single');
  assert.equal(isMenu(groups[0]), false);
});

// The ceiling


test('a cohort too large to attend becomes one menu', () => {
  // FOUN 1101 publishes 33 unlabelled tutorial sessions. Read as obligations
  // they are 33 hours of tutorial for one course.
  const tutorials = sessionsOfType('FOUN 1101', 'Tutorial');
  assert.equal(tutorials.length, 33);

  const groups = groupsFor('FOUN 1101', 'Tutorial');

  assert.equal(groups.length, 1);
  assert.equal(groups[0].reason, 'ceiling');
  assert.equal(groups[0].sessions.length, 33);
});

test('the ceiling keeps a large cohort to one block on the grid', () => {
  const groups = groupsFor('PSYC 1001', 'Tutorial');

  assert.equal(groups.length, 1);
  assert.equal(hoursOf(groups.map((g) => g.sessions[0])), 1);
});

test('a group is measured by its hours, not its session count', () => {
  // BIOL 1262's eight four-hour labs are 32 hours; its eight one-hour
  // tutorials are 8. Both are over, and both become menus.
  for (const type of ['Lab', 'Tutorial']) {
    const groups = groupsFor('BIOL 1262', type);
    assert.equal(groups.length, 1, type);
    assert.equal(groups[0].reason, 'ceiling', type);
  }
});

test('the ceiling is the one the warehouse justifies', () => {
  assert.equal(MENU_CEILING_HOURS, 6.0);
});

// Stream labels


test('fully labelled sessions are alternatives, not five tutorials', () => {
  const tutorials = sessionsOfType('BIOL 2061', 'Tutorial');
  assert.deepEqual(
    tutorials.map((s) => s.streamLabel).sort(),
    ['T1', 'T2', 'T3', 'T4', 'T5']
  );

  const groups = groupsFor('BIOL 2061', 'Tutorial');

  assert.equal(groups.length, 1);
  assert.equal(groups[0].reason, 'labelled');
  assert.equal(isMenu(groups[0]), true);
});

test('a partly labelled group keeps its labelled sessions together', () => {
  // CHEM 2470 labels five of its six tutorials and lands exactly on the
  // ceiling, so the label rule rather than the ceiling decides it.
  const tutorials = sessionsOfType('CHEM 2470', 'Tutorial');
  assert.equal(hoursOf(tutorials), MENU_CEILING_HOURS);

  const groups = groupsFor('CHEM 2470', 'Tutorial');
  const labelled = groups.find((g) => g.reason === 'labelled');

  assert.equal(labelled.sessions.length, 5);
  assert.ok(labelled.sessions.every((s) => s.streamLabel));
});

test('one stray label does not turn a course lectures into a single choice', () => {
  /**
   * COMP 1601 is the case the spec worked through. Five lectures, one marked
   * "G2". Reading every one of them as an alternative would place a single
   * hour where the student owes three.
   */
  const groups = groupsFor('COMP 1601', 'Lecture');

  assert.equal(groups.length, 4);
  const labelled = groups.find((g) => g.reason === 'labelled');
  assert.equal(labelled.sessions.length, 1);
  assert.equal(labelled.sessions[0].streamLabel, 'G2');
});

// Overlap clustering


test('two sessions at the same hour in different rooms are a room choice', () => {
  // COMP 1601 runs Tuesday 12:00 in both LRC A and LRC B.
  const groups = groupsFor('COMP 1601', 'Lecture');
  const tuesday = groups.find(
    (g) => g.sessions[0].day === 'Tuesday' && g.sessions[0].startTime === '12:00'
  );

  assert.equal(tuesday.sessions.length, 2);
  assert.equal(tuesday.reason, 'overlap');
  assert.deepEqual(
    tuesday.sessions.map((s) => s.room).sort(),
    ['LRC A', 'LRC B']
  );
});

test('a Monday and Wednesday lecture pair stays two lectures', () => {
  /**
   * The warehouse holds 297 of these, and they are the reason the default is
   * to attend everything rather than to pick one. Collapsing them would hide
   * a real lecture every week.
   */
  const groups = groupsFor('AGBU 1005', 'Lecture');

  assert.equal(groups.length, 2);
  assert.deepEqual(
    groups.map((g) => g.sessions[0].day),
    ['Monday', 'Wednesday']
  );
  assert.ok(groups.every((g) => !isMenu(g)));
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


test('a student can say these are alternatives after all', () => {
  const before = groupsFor('AGBU 1005', 'Lecture');
  assert.equal(before.length, 2);

  const after = deriveOptionGroups(pick('AGBU 1005', 'Lecture'), {
    'AGBU 1005|Lecture': 'menu',
  });

  assert.equal(after.length, 1);
  assert.equal(after[0].reason, 'override');
  assert.equal(after[0].sessions.length, 2);
});

test('a student can say these are not alternatives after all', () => {
  const before = groupsFor('FOUN 1101', 'Tutorial');
  assert.equal(before.length, 1);

  const after = deriveOptionGroups(pick('FOUN 1101', 'Tutorial'), {
    'FOUN 1101|Tutorial': 'split',
  });

  assert.equal(after.length, 33);
});

test('splitting also sets aside the labels, since that is what it means', () => {
  const after = deriveOptionGroups(pick('BIOL 2061', 'Tutorial'), {
    'BIOL 2061|Tutorial': 'split',
  });

  assert.equal(after.length, 5);
  assert.ok(after.every((g) => g.reason === 'single'));
});

test('an override for one type leaves the others alone', () => {
  const groups = deriveOptionGroups(pick('COMP 1601'), {
    'COMP 1601|Lecture': 'menu',
  });

  assert.equal(groups.filter((g) => g.type === 'Lecture').length, 1);
  assert.equal(groups.filter((g) => g.type === 'Lab')[0].reason, 'ceiling');
});
