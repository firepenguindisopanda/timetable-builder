'use strict';

/**
 * The download and the subscription feed write the same calendar.
 *
 * The browser builds the download; the server builds the feed in Python
 * (timetable_extractor/ics.py), because calendar servers run no JavaScript.
 * Both must turn tests/fixtures/ics_golden_input.json into ics_golden.ics
 * exactly, so a class cannot read one way in a downloaded file and another
 * way in a subscribed calendar. tests/test_ics.py checks the Python side.
 */

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const { load } = require('./harness.js');

const api = load('calendar-utils.js', 'calendar-events.js', 'slot-identity.js', 'ics-export.js');
const buildIcsCalendar = api.get('buildIcsCalendar');

const FIXTURES = path.join(__dirname, '..', 'fixtures');
const INPUT = JSON.parse(fs.readFileSync(path.join(FIXTURES, 'ics_golden_input.json'), 'utf8'));
const GOLDEN = path.join(FIXTURES, 'ics_golden.ics');

test('the download matches the golden calendar both writers share', () => {
  const { meta } = INPUT;
  const result = buildIcsCalendar(INPUT.placed, INPUT.dated, { ...meta, now: new Date(meta.now) });
  assert.ok(result.ok);
  if (process.env.UPDATE_GOLDEN) fs.writeFileSync(GOLDEN, result.text);
  assert.equal(result.text, fs.readFileSync(GOLDEN, 'utf8'));
});
