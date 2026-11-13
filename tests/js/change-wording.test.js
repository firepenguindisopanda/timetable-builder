'use strict';

/**
 * The builder's half of the contract with the publication diff.
 *
 * The entries in tests/fixtures/change_wording.json are what the API really
 * sends for each kind of change; tests/test_change_wording.py checks that the
 * diff still produces them. Here each must still produce its line. On
 * 12 Nov 2026 the API began sending 'weeks_changed', this file did not
 * exist, and students read "Postgraduate changed" with no weeks.
 */

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const { load } = require('./harness');

const { describeChange } =
  load('calendar-utils.js', 'change-notes.js').take('describeChange');

const FIXTURE = JSON.parse(fs.readFileSync(
  path.join(__dirname, '..', 'fixtures', 'change_wording.json'), 'utf8'
));

for (const { name, entry, line } of FIXTURE.cases) {
  test(`${name}: ${line.text}`, () => {
    const got = describeChange(entry);
    assert.deepEqual(
      { code: got.code, text: got.text, severity: got.severity }, line
    );
  });

  test(`${name}: worded, not the fallback`, () => {
    // The switch's default branch prints "<type> changed". A kind reaching
    // it is a kind the builder has no words for.
    const type = entry.activityType || 'class';
    assert.notEqual(describeChange(entry).text, type + ' changed');
  });
}
