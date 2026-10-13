'use strict';

/**
 * One time format on screen.
 *
 * Blocks and the class list printed 24-hour, the axis 12-hour, the detail
 * view "2:00 PM": the same class read three ways on one page.
 */

const test = require('node:test');
const assert = require('node:assert');
const { load } = require('./harness.js');

const api = load('calendar-utils.js');
const displayTime = api.get('displayTime');
const displayTimeRange = api.get('displayTimeRange');

test('times read as a student says them', () => {
  assert.equal(displayTime('09:00'), '9am');
  assert.equal(displayTime('14:00'), '2pm');
  assert.equal(displayTime('14:30'), '2:30pm');
  assert.equal(displayTime('08:05'), '8:05am');
});

test('noon and midnight are 12pm and 12am', () => {
  assert.equal(displayTime('12:00'), '12pm');
  assert.equal(displayTime('00:00'), '12am');
  assert.equal(displayTime('24:00'), '12am');
});

test('a 12-hour time from an uploaded PDF reads the same', () => {
  assert.equal(displayTime('2:00 PM'), '2pm');
  assert.equal(displayTime('9:30 AM'), '9:30am');
});

test('no time is no text', () => {
  assert.equal(displayTime(null), '');
  assert.equal(displayTime(''), '');
});

test('a range says am or pm once when both ends share it', () => {
  assert.equal(displayTimeRange('09:00', '11:00'), '9–11am');
  assert.equal(displayTimeRange('14:00', '16:00'), '2–4pm');
  assert.equal(displayTimeRange('14:30', '16:00'), '2:30–4pm');
});

test('a range across noon says both', () => {
  assert.equal(displayTimeRange('11:00', '12:30'), '11am–12:30pm');
  assert.equal(displayTimeRange('12:00', '13:00'), '12–1pm');
});

test('a range with a missing end shows what it has', () => {
  assert.equal(displayTimeRange('09:00', null), '9am');
  assert.equal(displayTimeRange(null, null), '');
});
