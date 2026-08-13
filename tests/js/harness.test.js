'use strict';

/**
 * The harness itself, because every other JS test is only as trustworthy as
 * its ability to load the real scripts and the real fixture.
 */

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
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

test('no two scripts declare the same top-level name', () => {
  /**
   * Sharing one scope is what lets these files call each other without a
   * module system, and it is also the trap: the page loads them in order, so
   * a name declared twice silently becomes whichever file loaded last, with
   * no error anywhere.
   *
   * That is not hypothetical. print-view.js and print-model.js both defined
   * `_entry`, and the view's HTML builder quietly replaced the model's field
   * builder, so every printed class came out with unformatted weeks and no
   * lecturer.
   *
   * Top-level declarations are the ones at column zero, which is the house
   * style throughout `assets/js`.
   */
  const dir = path.join(__dirname, '..', '..', 'assets', 'js');
  const declaredIn = new Map();

  for (const file of fs.readdirSync(dir).filter((f) => f.endsWith('.js'))) {
    const source = fs.readFileSync(path.join(dir, file), 'utf8');
    const declarations = source.matchAll(
      /^(?:function|const|let|var|class)\s+([A-Za-z_$][\w$]*)/gm
    );
    for (const [, name] of declarations) {
      if (!declaredIn.has(name)) declaredIn.set(name, []);
      declaredIn.get(name).push(file);
    }
  }

  const clashes = [...declaredIn]
    .filter(([, files]) => files.length > 1)
    .map(([name, files]) => `${name} in ${files.join(' and ')}`);

  assert.deepEqual(clashes, [], `top-level names declared more than once`);
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
