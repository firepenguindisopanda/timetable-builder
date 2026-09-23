'use strict';

/**
 * Placed classes as FullCalendar events.
 *
 * FullCalendar itself never loads here; these are the decisions the page
 * hands it, which is everything that can be wrong without a browser.
 */

const test = require('node:test');
const assert = require('node:assert');
const { load } = require('./harness.js');

const api = load('calendar-utils.js', 'calendar-events.js');
const {
  toCalendarEvents, visibleRange, eventKeyOf, typeClassOf, ANCHOR_MONDAY,
} = api.take('toCalendarEvents', 'visibleRange', 'eventKeyOf', 'typeClassOf', 'ANCHOR_MONDAY');

function placed(overrides) {
  return {
    courseKey: 'COMP 1601',
    groupId: 'COMP 1601|Lecture|all',
    type: 'Lecture',
    sessionId: 101,
    day: 'Monday',
    startTime: '12:00',
    endTime: '13:00',
    room: 'TLC LT A1',
    pinned: false,
    ...overrides,
  };
}

test('the generic week is drawn in teaching week 1, which begins Monday 31 August 2026', () => {
  assert.equal(ANCHOR_MONDAY, '2026-08-31');
});

test('each weekday lands on its own date in the anchor week', () => {
  const days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
  const events = toCalendarEvents(days.map((day, i) => placed({ day, sessionId: i })), new Set());

  assert.deepEqual(events.map(e => e.start.slice(0, 10)), [
    '2026-08-31', '2026-09-01', '2026-09-02', '2026-09-03',
    '2026-09-04', '2026-09-05', '2026-09-06',
  ]);
});

test('start and end are local wall-clock times with no offset', () => {
  const [event] = toCalendarEvents([placed({ day: 'Tuesday', startTime: '09:00', endTime: '10:30' })], new Set());

  assert.equal(event.start, '2026-09-01T09:00:00');
  assert.equal(event.end, '2026-09-01T10:30:00');
});

test('12-hour times from an uploaded PDF are read as 24-hour', () => {
  const [event] = toCalendarEvents([placed({ startTime: '2:00 PM', endTime: '3:00 PM' })], new Set());

  assert.equal(event.start, '2026-08-31T14:00:00');
  assert.equal(event.end, '2026-08-31T15:00:00');
});

test('a class that ends when it starts still gets a slot, so it cannot vanish', () => {
  const [event] = toCalendarEvents([placed({ startTime: '12:00', endTime: '12:00' })], new Set());

  assert.equal(event.end, '2026-08-31T12:30:00');
});

test('a day the grid does not know is left out rather than drawn somewhere wrong', () => {
  const events = toCalendarEvents([placed({ day: 'Funday' }), placed({ sessionId: 2 })], new Set());

  assert.equal(events.length, 1);
  assert.equal(events[0].extendedProps.sessionId, 2);
});

test('the id is the page-wide event key of group and session', () => {
  const [event] = toCalendarEvents([placed()], new Set());

  assert.equal(event.id, eventKeyOf('COMP 1601|Lecture|all', 101));
});

test('the class names carry the block, its type, and nothing else when unremarkable', () => {
  const [event] = toCalendarEvents([placed({ type: 'Lab' })], new Set());

  assert.equal(event.className, 'calendar-event lab');
});

test('an activity type outside the three coloured ones is drawn as other', () => {
  const [event] = toCalendarEvents([placed({ type: 'Field Trip' })], new Set());

  assert.equal(event.className, 'calendar-event other');
});

test('a class in a genuine clash is marked, and so is one the student placed', () => {
  const clashing = placed();
  const [event] = toCalendarEvents(
    [{ ...clashing, pinned: true }],
    new Set([eventKeyOf(clashing.groupId, clashing.sessionId)]));

  assert.equal(event.className, 'calendar-event lecture clash pinned');
  assert.equal(event.extendedProps.clash, true);
  assert.equal(event.extendedProps.pinned, true);
});

test('warehouse and uploaded session ids come back as the type they went in as', () => {
  const events = toCalendarEvents([
    placed({ sessionId: 101 }),
    placed({ sessionId: 'COMP-1601-L1', groupId: 'upload|Lecture|all' }),
  ], new Set());

  assert.strictEqual(events[0].extendedProps.sessionId, 101);
  assert.strictEqual(events[1].extendedProps.sessionId, 'COMP-1601-L1');
});

test('the block keeps the times as published, not FullCalendar\'s 12-hour text', () => {
  const [event] = toCalendarEvents([placed()], new Set());

  assert.equal(event.extendedProps.startTime, '12:00');
  assert.equal(event.extendedProps.endTime, '13:00');
});

test('the label is the course code, falling back to the title', () => {
  const events = toCalendarEvents([
    placed({ code: 'COMP 1601', courseKey: 'comp-key' }),
    placed({ courseKey: 'COMP 1602', sessionId: 2 }),
    placed({ courseKey: '', courseTitle: 'Computing I', sessionId: 3 }),
  ], new Set());

  assert.deepEqual(events.map(e => e.extendedProps.label), ['COMP 1601', 'COMP 1602', 'Computing I']);
});

test('typeClassOf ignores case and folds the rest into other', () => {
  assert.equal(typeClassOf('TUTORIAL'), 'tutorial');
  assert.equal(typeClassOf('Seminar'), 'other');
  assert.equal(typeClassOf(undefined), 'other');
});

test('with nothing unusual the grid shows 08:00 to 22:00, as it always has', () => {
  assert.deepEqual(visibleRange([placed()]), { slotMinTime: '08:00', slotMaxTime: '22:00' });
  assert.deepEqual(visibleRange([]), { slotMinTime: '08:00', slotMaxTime: '22:00' });
});

test('an early class widens the grid to the hour it starts in, instead of being cut off', () => {
  const range = visibleRange([placed({ startTime: '07:30', endTime: '08:30' })]);

  assert.equal(range.slotMinTime, '07:00');
});

test('a late class widens the grid to the hour after it ends', () => {
  const range = visibleRange([placed({ startTime: '21:00', endTime: '22:30' })]);

  assert.equal(range.slotMaxTime, '23:00');
});

test('a class ending exactly on the hour does not add an empty hour', () => {
  const range = visibleRange([placed({ startTime: '21:00', endTime: '23:00' })]);

  assert.equal(range.slotMaxTime, '23:00');
});
