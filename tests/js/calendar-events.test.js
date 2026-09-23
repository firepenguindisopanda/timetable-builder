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

// Dragging a class to one of its alternatives

const { dropTargets, resolveDrop, toDropZones } =
  api.take('dropTargets', 'resolveDrop', 'toDropZones');

function sitting(sessionId, day, startTime, endTime, room = 'FST C1') {
  return { sessionId, day, startTime, endTime, room };
}

test('every sitting of the dragged class\'s group is somewhere it can land, its own included', () => {
  const options = [sitting(1, 'Monday', '09:00', '10:00'), sitting(2, 'Tuesday', '09:00', '10:00')];
  const placements = [{ groupId: 'g', selectedSessionId: 1 }];

  assert.deepEqual(dropTargets(options, placements, 'g', 1).map(s => s.sessionId), [1, 2]);
});

test('a sitting another placement of the group already shows is not a target', () => {
  const options = [
    sitting(1, 'Monday', '09:00', '10:00'),
    sitting(2, 'Tuesday', '09:00', '10:00'),
    sitting(3, 'Wednesday', '09:00', '10:00'),
  ];
  // An extra sitting: the group shows 1 and 2, and 1 is being dragged.
  const placements = [
    { groupId: 'g', selectedSessionId: 1 },
    { groupId: 'g', selectedSessionId: 2 },
    { groupId: 'other', selectedSessionId: 3 },
  ];

  assert.deepEqual(dropTargets(options, placements, 'g', 1).map(s => s.sessionId), [1, 3]);
});

test('a drop whose middle lands inside a sitting picks that sitting', () => {
  const targets = [sitting(1, 'Monday', '09:00', '10:00'), sitting(2, 'Wednesday', '12:00', '13:00')];

  // Dropped at 11:30 for an hour: its middle is 12:00, inside the Wednesday sitting.
  assert.equal(resolveDrop(targets, 'Wednesday', 11 * 60 + 30, 60), 2);
});

test('a drop on the right hour of the wrong day lands nowhere', () => {
  const targets = [sitting(2, 'Wednesday', '12:00', '13:00')];

  assert.equal(resolveDrop(targets, 'Thursday', 12 * 60, 60), null);
});

test('a drop between two sittings lands nowhere rather than snapping to the nearer', () => {
  const targets = [sitting(1, 'Monday', '09:00', '10:00'), sitting(2, 'Monday', '14:00', '15:00')];

  assert.equal(resolveDrop(targets, 'Monday', 11 * 60, 60), null);
});

test('a middle exactly on a sitting\'s end belongs to the next, not to it', () => {
  const targets = [sitting(1, 'Monday', '09:00', '10:00'), sitting(2, 'Monday', '10:00', '11:00')];

  assert.equal(resolveDrop(targets, 'Monday', 9 * 60 + 30, 60), 2);
});

test('two rooms running the same sitting: the first in option order, as the old zones did', () => {
  const targets = [
    sitting(1, 'Tuesday', '12:00', '13:00', 'LRC A'),
    sitting(2, 'Tuesday', '12:00', '13:00', 'LRC B'),
  ];

  assert.equal(resolveDrop(targets, 'Tuesday', 12 * 60, 60), 1);
});

test('12-hour sitting times from an uploaded PDF resolve like 24-hour ones', () => {
  const targets = [sitting('COMP-L2', 'Friday', '2:00 PM', '3:00 PM')];

  assert.equal(resolveDrop(targets, 'Friday', 14 * 60, 60), 'COMP-L2');
});

test('drop zones are background events in the anchor week, styled as drop zones', () => {
  const zones = toDropZones([sitting(2, 'Wednesday', '12:00', '13:00'), sitting(9, 'Funday', '12:00', '13:00')]);

  assert.equal(zones.length, 1);
  assert.equal(zones[0].start, '2026-09-02T12:00:00');
  assert.equal(zones[0].end, '2026-09-02T13:00:00');
  assert.equal(zones[0].display, 'background');
  assert.equal(zones[0].className, 'drop-zone');
});
