'use strict';

/**
 * Recognising the same class in a newer publication.
 *
 * The cases live in tests/fixtures/slot_resolution.json, which the Python
 * suite reads too: the browser and the subscription feed must agree on what
 * a student's choice means after a republish.
 */

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const { load } = require('./harness.js');

const api = load('slot-identity.js');
const { slotKey, slotHash, resolveSlot, fnv1aHex } = api.take(
  'slotKey', 'slotHash', 'resolveSlot', 'fnv1aHex'
);

const FIXTURE = JSON.parse(fs.readFileSync(
  path.join(__dirname, '..', 'fixtures', 'slot_resolution.json'), 'utf8'
));

test('FNV-1a matches the published test vectors', () => {
  // From the FNV reference: "" and "a" under the 32-bit offset basis.
  assert.equal(fnv1aHex(''), '811c9dc5');
  assert.equal(fnv1aHex('a'), 'e40c292c');
});

for (const { session, key, hash } of FIXTURE.hashes) {
  test(`slot hash of ${key}`, () => {
    assert.equal(slotKey(session), key);
    assert.equal(slotHash(session), hash);
  });
}

test('the session id and lecturer are not part of a slot', () => {
  const [{ session }] = FIXTURE.hashes;
  const renumbered = { ...session, sessionId: 99999, staff: ['Someone Else'] };
  assert.equal(slotHash(renumbered), slotHash(session));
});

for (const c of FIXTURE.cases) {
  test(`resolve: ${c.name}`, () => {
    const got = resolveSlot(c.old, c.oldOfType, c.newOfType);
    assert.equal(got ? c.newOfType.indexOf(got) : null, c.expected);
  });
}
