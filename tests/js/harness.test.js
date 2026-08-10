'use strict';

/**
 * The harness itself, because every other JS test is only as trustworthy as
 * its ability to load the real scripts and the real fixture.
 */

const test = require('node:test');
const assert = require('node:assert');
const { load, warehouse, course, sessionsOfType } = require('./harness.js');

test('the calendar scripts load and expose their functions', () => {
  const utils = load('calendar-utils.js');

  assert.equal(typeof utils.get('timeToMins'), 'function');
  assert.equal(utils.get('timeToMins')('09:30'), 570);
});

test('constants declared with const are readable too', () => {
  const utils = load('calendar-utils.js');

  assert.deepEqual(utils.get('DAYS').slice(0, 2), ['Monday', 'Tuesday']);
});

test('scripts loaded together share one scope, as they do in the page', () => {
  // option-groups.js calls timeToMins, which calendar-utils.js declares.
  const api = load('calendar-utils.js', 'option-groups.js');

  assert.equal(typeof api.get('deriveOptionGroups'), 'function');
});

test('the fixture is the warehouse response, not something invented', () => {
  assert.ok(warehouse.publicationId);
  assert.ok(warehouse.courses.length >= 10);

  const session = course('COMP 1601').sessions[0];
  assert.deepEqual(Object.keys(session).sort(), [
    'day',
    'endTime',
    'room',
    'sessionId',
    'sourceCount',
    'staff',
    'startTime',
    'streamLabel',
    'type',
    'weeks',
    'weeksRaw',
  ]);
});

test('asking for a course nobody captured says so', () => {
  assert.throws(() => course('NOPE 9999'), /no fixture for NOPE 9999/);
});

test('COMP 1601 still has the lab menu the grouping rules turn on', () => {
  assert.equal(sessionsOfType('COMP 1601', 'Lab').length, 10);
  assert.equal(
    sessionsOfType('COMP 1601', 'Lab').filter((s) => s.streamLabel).length,
    1
  );
});
