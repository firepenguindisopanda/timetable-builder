'use strict';

/**
 * Blocks that share an hour must share the width instead of stacking.
 */

const test = require('node:test');
const assert = require('node:assert');
const { load } = require('./harness.js');

const api = load('calendar-utils.js', 'grid-layout.js');
const layoutDayEvents = api.get('layoutDayEvents');

function ev(groupId, startTime, endTime) {
  return { groupId, day: 'Monday', startTime, endTime };
}

test('an event overlapping nothing renders full width', () => {
  const [record] = layoutDayEvents([ev('a', '09:00', '10:00')]);
  assert.equal(record.col, 0);
  assert.equal(record.cols, 1);
});

test('two events at the same hour split the column between them', () => {
  const events = [ev('a', '09:00', '10:00'), ev('b', '09:00', '10:00')];
  const records = layoutDayEvents(events);

  assert.deepEqual(records.map(r => r.cols), [2, 2]);
  assert.deepEqual(records.map(r => r.col).sort(), [0, 1]);
});

test('records come back in the order the events went in', () => {
  const events = [ev('b', '10:00', '11:00'), ev('a', '09:00', '10:00')];
  const records = layoutDayEvents(events);

  assert.equal(records[0].event, events[0]);
  assert.equal(records[1].event, events[1]);
});

test('back to back events do not split, because they never overlap', () => {
  const events = [ev('a', '09:00', '10:00'), ev('b', '10:00', '11:00')];
  const records = layoutDayEvents(events);

  assert.deepEqual(records.map(r => r.cols), [1, 1]);
  assert.deepEqual(records.map(r => r.col), [0, 0]);
});

test('a run shares its widest column count, so a pile-up lines up', () => {
  // The long block spans both shorter ones. All three are one run: the
  // short pair must not widen back to full width while the long one is
  // still beside them.
  const events = [
    ev('long', '09:00', '12:00'),
    ev('early', '09:00', '10:00'),
    ev('late', '10:00', '11:00'),
  ];
  const records = layoutDayEvents(events);

  assert.deepEqual(records.map(r => r.cols), [2, 2, 2]);
  // The shorter blocks reuse one lane; the long one keeps the other.
  assert.equal(records[1].col, records[2].col);
  assert.notEqual(records[0].col, records[1].col);
});

test('a new run starts once every open column has ended', () => {
  const events = [
    ev('a', '09:00', '10:00'),
    ev('b', '09:00', '10:00'),
    ev('afternoon', '14:00', '15:00'),
  ];
  const records = layoutDayEvents(events);

  assert.equal(records[2].cols, 1);
  assert.equal(records[2].col, 0);
});

test('the longer of two same-start blocks takes the leftmost lane', () => {
  const events = [
    ev('short', '09:00', '10:00'),
    ev('long', '09:00', '11:00'),
  ];
  const records = layoutDayEvents(events);

  const long = records.find(r => r.event.groupId === 'long');
  const short = records.find(r => r.event.groupId === 'short');
  assert.equal(long.col, 0);
  assert.equal(short.col, 1);
});

test('three-deep overlap yields three lanes', () => {
  const events = [
    ev('a', '09:00', '11:00'),
    ev('b', '09:30', '10:30'),
    ev('c', '10:00', '11:00'),
  ];
  const records = layoutDayEvents(events);

  assert.deepEqual(records.map(r => r.cols), [3, 3, 3]);
  assert.deepEqual(records.map(r => r.col).sort(), [0, 1, 2]);
});

test('layout is deterministic for identical twin blocks', () => {
  // Two sittings at the same day and time in different rooms are real
  // (overflow rooms). The group id breaks the tie the same way every render.
  const events = [
    { groupId: 'x|Lab|all', day: 'Monday', startTime: '09:00', endTime: '10:00' },
    { groupId: 'y|Lab|all', day: 'Monday', startTime: '09:00', endTime: '10:00' },
  ];
  const once = layoutDayEvents(events).map(r => r.col);
  const twice = layoutDayEvents(events).map(r => r.col);

  assert.deepEqual(once, twice);
});
