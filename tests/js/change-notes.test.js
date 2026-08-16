'use strict';

/**
 * The words a student reads when their timetable has moved underneath them.
 *
 * Wording is the part of this feature most likely to be wrong and the part
 * cheapest to pin, so the whole vocabulary is here. The cases that matter are
 * the ones where the obvious word is the wrong one: a confirmed venue is not
 * a move, and a course that lost a whole activity type has not had a class
 * moved, it has a hole the app cannot fill.
 */

const test = require('node:test');
const assert = require('node:assert');
const { load } = require('./harness');

const { describeChange, summariseChanges } =
  load('change-notes.js').take('describeChange', 'summariseChanges');

function slot(over) {
  return Object.assign({
    day: 'Monday', startTime: '09:00', endTime: '10:00',
    room: 'FST CSL1', weeks: 'W1-W12',
  }, over || {});
}

function change(over) {
  return Object.assign({
    code: 'COMP 1601', title: 'Computer Programming I',
    changeType: 'class_moved', displayKind: 'class_moved',
    activityType: 'Lecture', streamLabel: null, lastOfType: false,
    before: [slot()], after: [slot({ day: 'Friday' })],
  }, over || {});
}

// Moves


test('a class on a different day says where it went', () => {
  const line = describeChange(change());
  assert.equal(line.code, 'COMP 1601');
  assert.equal(line.text, 'Lecture Mon 09:00 → Fri 09:00');
  assert.equal(line.severity, 'act');
});

test('a class that only changed room is not described by its day', () => {
  const line = describeChange(change({
    before: [slot()], after: [slot({ room: 'TLC TR3' })],
  }));
  assert.equal(line.text, 'Lecture moved to TLC TR3');
});

test('a class that only changed weeks says so', () => {
  const line = describeChange(change({
    before: [slot()], after: [slot({ weeks: 'W1, W3, W5, W7, W9, W11' })],
  }));
  assert.equal(line.text, 'Lecture now runs W1, W3, W5, W7, W9, W11');
});

test('a class with several sittings changed does not pick one to report', () => {
  const line = describeChange(change({
    before: [slot(), slot({ startTime: '10:00' })],
    after: [slot({ room: 'TLC TR3' }), slot({ startTime: '10:00', room: 'TLC TR4' })],
  }));
  assert.equal(line.text, 'Lecture timetable changed');
});

// The two that must not read as moves


test('a confirmed venue is good news, not a move', () => {
  const line = describeChange(change({
    displayKind: 'class_venue_confirmed',
    before: [slot({ room: 'Venue to be advised' })],
    after: [slot({ room: 'FHE 314 A' })],
  }));
  assert.equal(line.text, 'Lecture venue confirmed: FHE 314 A');
  assert.equal(line.severity, 'info');
});

test('a course that lost a whole class type is told to ask the department', () => {
  const line = describeChange(change({
    displayKind: 'class_removed', lastOfType: true,
    code: 'FREN 3401', before: [slot()], after: [],
  }));
  assert.equal(
    line.text,
    'no longer has a published Lecture — check with your department'
  );
  assert.equal(line.severity, 'act');
});

test('a removal that leaves other sittings does not claim the type is gone', () => {
  const line = describeChange(change({
    displayKind: 'class_removed', lastOfType: false, before: [slot()], after: [],
  }));
  assert.equal(line.text, 'Lecture removed');
});

// Sittings gained and lost


test('an extra sitting is not called a move', () => {
  const line = describeChange(change({
    displayKind: 'sitting_added', before: [], after: [slot({ day: 'Tuesday' })],
  }));
  assert.equal(line.text, 'extra Lecture — Tue 09:00');
  assert.equal(line.severity, 'info');
});

test('a dropped sitting says which one it was', () => {
  const line = describeChange(change({
    displayKind: 'sitting_removed', before: [slot({ day: 'Tuesday' })], after: [],
  }));
  assert.equal(line.text, 'one Lecture sitting dropped — was Tue 09:00');
  assert.equal(line.severity, 'act');
});

// Courses


test('a withdrawn course says so plainly', () => {
  const line = describeChange({
    code: 'LING 2304', displayKind: 'course_dropped', before: [], after: [],
  });
  assert.equal(line.text, 'is no longer published');
  assert.equal(line.severity, 'act');
});

test('a renamed course is filed under the code the student is holding', () => {
  /* Their timetable says EDMA 11**. Filing it under EDMA 1142 would show
     them a line about a course they do not recognise. */
  const line = describeChange({
    code: 'EDMA 1142', previousCode: 'EDMA 11**',
    displayKind: 'course_renamed', before: [], after: [],
  });
  assert.equal(line.code, 'EDMA 11**');
  assert.equal(line.text, 'is now published as EDMA 1142');
  assert.equal(line.severity, 'info');
});

// Missing pieces must not produce "undefined"


test('a class with no activity type still reads as a sentence', () => {
  const line = describeChange(change({ activityType: null }));
  assert.equal(line.text, 'class Mon 09:00 → Fri 09:00');
});

test('a confirmation with no room named does not print undefined', () => {
  const line = describeChange(change({
    displayKind: 'class_venue_confirmed',
    before: [slot({ room: null })], after: [slot({ room: null })],
  }));
  assert.ok(!/undefined/.test(line.text), line.text);
});

test('an unrecognised change type still says something true', () => {
  const line = describeChange(change({ displayKind: 'something_new' }));
  assert.equal(line.text, 'Lecture changed');
});

// The summary


test('nothing changed is a useful answer, not an empty one', () => {
  const summary = summariseChanges([]);
  assert.equal(summary.total, 0);
  assert.equal(summary.headline, 'None of your classes moved');
  assert.deepEqual(summary.lines, []);
});

test('the summary counts what it lists', () => {
  const summary = summariseChanges([change(), change({ code: 'ECCD 0110' })]);
  assert.equal(summary.total, 2);
  assert.equal(summary.headline, '2 of your classes changed');
});

test('what costs the student something is listed first', () => {
  /* A student who reads one line should read the one that matters. */
  const summary = summariseChanges([
    change({ displayKind: 'class_venue_confirmed', after: [slot({ room: 'FHE 314 A' })] }),
    change({ displayKind: 'class_removed', lastOfType: true, code: 'FREN 3401' }),
  ]);
  assert.equal(summary.lines[0].code, 'FREN 3401');
  assert.equal(summary.lines[0].severity, 'act');
  assert.equal(summary.actionable, 1);
});

test('a null change list is treated as no changes', () => {
  assert.equal(summariseChanges(null).total, 0);
});
