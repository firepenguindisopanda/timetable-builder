'use strict';

/**
 * When two classes really collide.
 *
 * The interesting cases all come from teaching weeks, so the fixtures are real
 * sessions with real week arrays rather than invented times.
 */

const test = require('node:test');
const assert = require('node:assert');
const { load, course, sessionsOfType } = require('./harness.js');

const api = load('calendar-utils.js');
const findConflicts = api.get('findConflicts');
const sharedWeeks = api.get('sharedWeeks');

/** A placed event, as the calendar hands them to the conflict finder. */
function event(session, courseKey) {
  return {
    courseKey,
    courseTitle: courseKey,
    day: session.day,
    startTime: session.startTime,
    endTime: session.endTime,
    room: session.room,
    weeks: session.weeks,
  };
}

function sessionAt(code, type, day, startTime) {
  const found = sessionsOfType(code, type).filter(
    (s) => s.day === day && s.startTime === startTime
  );
  if (!found.length) throw new Error(`no ${code} ${type} on ${day} ${startTime}`);
  return found;
}

// Teaching weeks


test('classes in the same slot but different weeks do not clash', () => {
  /**
   * BIOL 1262 lectures on Thursday at 16:00 in weeks 2, 4, 6, 8 and 12. The
   * relocated lecture takes the same slot in week 10. They look identical on a
   * grid and the student never has to choose.
   */
  const lecture = sessionAt('BIOL 1262', 'Lecture', 'Thursday', '16:00')[0];
  const relocated = sessionAt(
    'BIOL 1262',
    'Lecture Relocated',
    'Thursday',
    '16:00'
  )[0];
  assert.deepEqual(lecture.weeks, [2, 4, 6, 8, 12]);
  assert.deepEqual(relocated.weeks, [10]);

  const conflicts = findConflicts([
    event(lecture, 'BIOL 1262'),
    event(relocated, 'BIOL 1262'),
  ]);

  assert.deepEqual(conflicts, []);
});

test('classes in the same slot that do share weeks clash', () => {
  // The same lecture runs in two rooms, both in weeks 2, 4, 6, 8 and 12.
  const [first, second] = sessionAt('BIOL 1262', 'Lecture', 'Thursday', '16:00');

  const conflicts = findConflicts([
    event(first, 'BIOL 1262'),
    event(second, 'BIOL 1262'),
  ]);

  assert.equal(conflicts.length, 1);
  assert.deepEqual(conflicts[0].weeks, [2, 4, 6, 8, 12]);
});

test('a clash reports only the weeks both classes run in', () => {
  const fortnightly = { weeks: [2, 4, 6, 8, 10, 12] };
  const weekly = { weeks: [1, 2, 3, 4, 5] };

  assert.deepEqual(sharedWeeks(fortnightly, weekly), [2, 4]);
});

test('the shared weeks come back in order whatever order they arrived in', () => {
  assert.deepEqual(sharedWeeks({ weeks: [12, 2, 6] }, { weeks: [6, 12, 2] }), [
    2, 6, 12,
  ]);
});

// Events with no week data, which is every uploaded PDF


test('two classes with no week data clash exactly as they used to', () => {
  const conflicts = findConflicts([
    { courseId: 'A', day: 'Monday', startTime: '09:00', endTime: '10:00' },
    { courseId: 'B', day: 'Monday', startTime: '09:30', endTime: '10:30' },
  ]);

  assert.equal(conflicts.length, 1);
  assert.equal(conflicts[0].weeks, null, 'null means every week, not no weeks');
});

test('an uploaded class clashes with a warehouse one across its whole run', () => {
  const uploaded = { courseId: 'UPLOAD', day: 'Monday', startTime: '09:00', endTime: '10:00' };
  const known = { courseKey: 'WAREHOUSE', day: 'Monday', startTime: '09:00', endTime: '10:00', weeks: [3, 4] };

  const [conflict] = findConflicts([uploaded, known]);

  assert.deepEqual(conflict.weeks, [3, 4]);
});

test('an empty week array is treated as unknown, not as never', () => {
  const conflicts = findConflicts([
    { courseId: 'A', day: 'Monday', startTime: '09:00', endTime: '10:00', weeks: [] },
    { courseId: 'B', day: 'Monday', startTime: '09:00', endTime: '10:00', weeks: [5] },
  ]);

  assert.equal(conflicts.length, 1);
});

// A course clashing with itself


test('a course whose own two classes collide is told so', () => {
  /**
   * The old finder skipped any pair sharing a course id. Under option grouping
   * a course places several sessions, so this is a clash a student has to act
   * on rather than one to hide.
   */
  const lecture = sessionAt('COMP 1601', 'Lecture', 'Monday', '12:00')[0];
  const lab = sessionAt('COMP 1601', 'Lab', 'Monday', '10:00')[0];
  assert.equal(lab.endTime, '12:00');

  const overlapping = { ...lab, endTime: '13:00' };
  const conflicts = findConflicts([
    event(lecture, 'COMP 1601'),
    event(overlapping, 'COMP 1601'),
  ]);

  assert.equal(conflicts.length, 1);
  assert.equal(conflicts[0].sameCourse, true);
});

test('a clash between two courses is marked as such', () => {
  const a = sessionAt('COMP 1601', 'Lecture', 'Monday', '12:00')[0];

  const [conflict] = findConflicts([
    event(a, 'COMP 1601'),
    event(a, 'PSYC 1001'),
  ]);

  assert.equal(conflict.sameCourse, false);
  assert.equal(conflict.courseA, 'COMP 1601');
  assert.equal(conflict.courseB, 'PSYC 1001');
});

// Ordinary non-clashes


test('classes on different days never clash', () => {
  const monday = sessionAt('COMP 1601', 'Lecture', 'Monday', '12:00')[0];
  const wednesday = sessionAt('COMP 1601', 'Lecture', 'Wednesday', '12:00')[0];

  assert.deepEqual(
    findConflicts([event(monday, 'A'), event(wednesday, 'B')]),
    []
  );
});

test('back to back classes do not clash', () => {
  const first = sessionAt('COMP 1601', 'Lecture', 'Monday', '12:00')[0];
  const second = sessionAt('COMP 1601', 'Lecture', 'Monday', '13:00')[0];
  assert.equal(first.endTime, second.startTime);

  assert.deepEqual(findConflicts([event(first, 'A'), event(second, 'B')]), []);
});

test('every colliding pair is reported once, not twice', () => {
  const session = sessionAt('COMP 1601', 'Lecture', 'Monday', '12:00')[0];
  const three = ['A', 'B', 'C'].map((key) => event(session, key));

  assert.equal(findConflicts(three).length, 3);
});

test('nothing placed means nothing to report', () => {
  assert.deepEqual(findConflicts([]), []);
});

test('a conflict carries the events themselves, for the fix button', () => {
  const session = sessionAt('COMP 1601', 'Lecture', 'Monday', '12:00')[0];

  const [conflict] = findConflicts([
    event(session, 'A'),
    event(session, 'B'),
  ]);

  assert.equal(conflict.a.courseKey, 'A');
  assert.equal(conflict.b.courseKey, 'B');
  assert.equal(conflict.day, 'Monday');
  assert.equal(conflict.timeA, '12:00-13:00');
});
