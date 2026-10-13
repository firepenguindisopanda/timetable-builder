'use strict';

/**
 * Exams and other one-offs, listed by date instead of placed weekly.
 */

const test = require('node:test');
const assert = require('node:assert');
const { load } = require('./harness.js');

const api = load('calendar-utils.js', 'calendar-events.js', 'coming-up.js');
const dateOfTeachingDay = api.get('dateOfTeachingDay');
const comingUpItems = api.get('comingUpItems');
const comingUpHtml = api.get('comingUpHtml');
const comingUpDateLabel = api.get('comingUpDateLabel');

function exam(fields) {
  return {
    courseKey: 'COMP 2601',
    courseTitle: 'Computer Architecture',
    type: 'Examination',
    day: 'Thursday',
    startTime: '09:00',
    endTime: '11:00',
    room: 'ENG MD3',
    weeks: [7],
    ...fields,
  };
}

// Dates

test('week 1 is the week of Mon 31 Aug 2026', () => {
  assert.equal(dateOfTeachingDay(1, 'Monday'), '2026-08-31');
  assert.equal(dateOfTeachingDay(1, 'Sunday'), '2026-09-06');
});

test('week 7 Thursday is 15 Oct, across a month boundary', () => {
  assert.equal(dateOfTeachingDay(7, 'Thursday'), '2026-10-15');
  assert.equal(dateOfTeachingDay(5, 'Wednesday'), '2026-09-30');
  assert.equal(dateOfTeachingDay(5, 'Thursday'), '2026-10-01');
});

test('a week or day that is not one has no date', () => {
  assert.equal(dateOfTeachingDay(0, 'Monday'), null);
  assert.equal(dateOfTeachingDay(3, 'Funday'), null);
  assert.equal(dateOfTeachingDay(null, 'Monday'), null);
});

test('the date label is read from the date, not a clock', () => {
  assert.equal(comingUpDateLabel('2026-10-15', 'Thursday'), 'Thu 15 Oct');
});

// The list

test('an exam is listed once per week it runs, with its date and week', () => {
  const { items } = comingUpItems([exam({ weeks: [7, 9] })], '2026-10-12');
  assert.deepEqual(items.map((i) => [i.date, i.week, i.label]), [
    ['2026-10-15', 7, 'Exam'],
    ['2026-10-29', 9, 'Exam'],
  ]);
});

test('an exam split across rooms is one entry naming every room', () => {
  /**
   * COMP 2601's week-7 exam is published in ENG MD3, JFK LT and "Venue to be
   * advised" at once. The detail view used to offer those as sittings to
   * choose between; the student sits one exam and must check which room.
   */
  const { items } = comingUpItems([
    exam({ room: 'JFK LT' }),
    exam({ room: 'ENG MD3' }),
    exam({ room: 'Venue to be advised' }),
  ], '2026-10-12');

  assert.equal(items.length, 1);
  assert.deepEqual(items[0].rooms, ['ENG MD3', 'JFK LT', 'Venue to be advised']);
  assert.match(comingUpHtml({ items }), /ENG MD3 \/ JFK LT \/ Venue to be advised \(check which is yours\)/);
});

test('rooms the server already joined from one block are split back out', () => {
  const { items } = comingUpItems([exam({ room: 'ENG MD3; JFK AUD' })], '2026-10-12');
  assert.deepEqual(items[0].rooms, ['ENG MD3', 'JFK AUD']);
});

test('sittings that have gone by are counted, not listed', () => {
  const result = comingUpItems([exam({ weeks: [3, 7] })], '2026-10-12');
  assert.equal(result.items.length, 1);
  assert.equal(result.past, 1);
});

test('today itself is still coming up', () => {
  const result = comingUpItems([exam({ day: 'Monday' })], '2026-10-12');
  assert.equal(result.items.length, 1);
});

test('entries come in date then time order, whatever order they arrived in', () => {
  const sessions = [
    exam({ courseKey: 'MATH 2401', day: 'Friday' }),
    exam({ courseKey: 'COMP 2602', type: 'Lecture Relocated', day: 'Monday', weeks: [8] }),
    exam({ startTime: '08:00', endTime: '09:00' }),
    exam({}),
  ];
  const forward = comingUpItems(sessions, '2026-10-12').items;
  const backward = comingUpItems([...sessions].reverse(), '2026-10-12').items;

  assert.deepEqual(forward, backward);
  assert.deepEqual(forward.map((i) => `${i.date} ${i.startTime} ${i.courseKey}`), [
    '2026-10-15 08:00 COMP 2601',
    '2026-10-15 09:00 COMP 2601',
    '2026-10-16 09:00 MATH 2401',
    '2026-10-19 09:00 COMP 2602',
  ]);
});

test('a class with no published weeks cannot be dated, so it is left out', () => {
  assert.deepEqual(comingUpItems([exam({ weeks: null })], '2026-10-12').items, []);
});

test('types are named as a student would say them', () => {
  const { items } = comingUpItems([
    exam({ type: 'Lecture Relocated' }),
    exam({ type: 'Tutorial (make-up/relocated)', startTime: '12:00' }),
  ], '2026-10-12');
  assert.deepEqual(items.map((i) => i.label), ['Lecture moved', 'Make-up or moved tutorial']);
});

test('a missing room says so rather than leaving a gap', () => {
  const { items } = comingUpItems([exam({ room: null })], '2026-10-12');
  assert.match(comingUpHtml({ items }), /Room not published/);
});

test('nothing to list renders nothing', () => {
  assert.equal(comingUpHtml({ items: [], past: 3 }), '');
});

test('course text is escaped', () => {
  const { items } = comingUpItems([exam({ courseKey: '<b>X</b>' })], '2026-10-12');
  const html = comingUpHtml({ items });
  assert.ok(!html.includes('<b>X</b>'));
  assert.ok(html.includes('&lt;b&gt;X&lt;/b&gt;'));
});
