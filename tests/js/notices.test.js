'use strict';

/**
 * One notice per event above the grid (REDESIGN-SPEC.md 5.3).
 */

const test = require('node:test');
const assert = require('node:assert');
const { load } = require('./harness.js');

const api = load('notices.js');
const noticesToShow = api.get('noticesToShow');

const shown = (wants) => Array.from(noticesToShow(wants));

test('nothing wanted, nothing shown', () => {
  assert.deepStrictEqual(shown({}), []);
  assert.deepStrictEqual(shown(null), []);
});

test('an update on offer hides the last update\'s list of the same changes', () => {
  // Undoing "Update my courses" brought both back at once.
  assert.deepStrictEqual(shown({ republish: 'offer', changes: true }), ['republish']);
});

test('"Not now" hides the offer without bringing the older list back', () => {
  assert.deepStrictEqual(shown({ republish: 'dismissed', changes: true }), []);
  assert.deepStrictEqual(shown({ republish: 'dismissed', subscription: true }), ['subscription']);
});

test('after updating, the list of what changed shows', () => {
  assert.deepStrictEqual(shown({ changes: true }), ['changes']);
});

test('most urgent first, and never more than two', () => {
  assert.deepStrictEqual(
    shown({ subscription: true, republish: 'offer', storage: true }),
    ['storage', 'republish'],
  );
  assert.deepStrictEqual(
    shown({ subscription: true, changes: true }),
    ['changes', 'subscription'],
  );
});

test('an unknown notice is ignored rather than shown', () => {
  assert.deepStrictEqual(shown({ banner: true, storage: true }), ['storage']);
});
