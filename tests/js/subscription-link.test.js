'use strict';

/**
 * The calendar subscription link the page makes.
 *
 * tests/fixtures/subscription_token.json is a token this file makes, which
 * tests/test_subscription.py decodes: the browser writes links and the
 * server reads them, so the two are held to one fixture. Regenerate it with
 * UPDATE_GOLDEN=1 only on purpose; links already in students' calendars are
 * in the old format.
 */

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const { load, course } = require('./harness.js');

const api = load(
  'calendar-utils.js',
  'option-groups.js',
  'placement.js',
  'slot-identity.js',
  'timetable-state.js',
  'subscription-link.js'
);
const {
  TimetableState, base64Url, subscriptionToken, subscriptionBody, subscriptionUrls,
  subscriptionOutOfDate, carrySubscription, subscribableCourses, slotHash,
} = api.take('TimetableState', 'base64Url', 'subscriptionToken', 'subscriptionBody',
  'subscriptionUrls', 'subscriptionOutOfDate', 'carrySubscription', 'subscribableCourses', 'slotHash');

const FIXTURE = path.join(__dirname, '..', 'fixtures', 'subscription_token.json');

function stateOf(publicationId, ...codes) {
  const source = TimetableState.fromWarehouseResponse({ publicationId, courses: codes.map(course) });
  const state = new TimetableState(source, null);
  state.placeMissing();
  return state;
}

function decode(token) {
  return Buffer.from(token, 'base64url').toString('utf8');
}

test('base64url matches the platform encoder, multi-byte text included', () => {
  for (const text of ['', 'a', 'ab', 'abc', '1|11|FOUN 1001 (FULL & PART-TIME):00ff', 'Salle É — 😀']) {
    assert.equal(base64Url(text), Buffer.from(text, 'utf8').toString('base64url'));
  }
});

test('a token lists each course, its placed slots and its removed types', () => {
  const state = stateOf(11, 'COMP 2611', 'FOUN 1001 (FULL & PART-TIME)');
  const tutorials = state.optionGroups.find((g) => g.courseKey.startsWith('FOUN') && g.type === 'Tutorial');
  state.removePlacement(tutorials.groupId);

  const { token } = subscriptionToken(state);
  const [version, publication, body] = decode(token).split('|');
  assert.equal(version, '1');
  assert.equal(publication, '11');

  const courses = body.split(';');
  assert.deepEqual(courses.map((c) => c.split(':')[0]), ['COMP 2611', 'FOUN 1001 (FULL & PART-TIME)']);
  assert.ok(courses[1].endsWith('!Tutorial'));

  const comp = state.placements.filter((p) => p.courseKey === 'COMP 2611');
  const sessions = new Map(state.getCourse('COMP 2611').sessions.map((s) => [s.sessionId, s]));
  const expected = [...new Set(comp.map((p) => slotHash(sessions.get(p.selectedSessionId))))].sort();
  assert.equal(courses[0], 'COMP 2611:' + expected.join(','));

  const fixture = {
    _about: 'Made by tests/js/subscription-link.test.js, decoded by tests/test_subscription.py.',
    token,
    publicationId: 11,
    courses: courses.map((part) => {
      const [code, rest] = [part.slice(0, part.indexOf(':')), part.slice(part.indexOf(':') + 1)];
      const [picks, dismissed] = rest.split('!');
      return { code, picks: picks ? picks.split(',') : [], dismissed: dismissed ? dismissed.split(',') : [] };
    }),
  };
  if (process.env.UPDATE_GOLDEN) fs.writeFileSync(FIXTURE, JSON.stringify(fixture, null, 2) + '\n');
  assert.deepEqual(JSON.parse(fs.readFileSync(FIXTURE, 'utf8')), fixture);
});

test('uploaded and withdrawn courses are left out and named', () => {
  const state = stateOf(11, 'COMP 2611', 'COMP 1601');
  state.getCourse('COMP 1601').stale = true;
  state.sourceData.courses.push({ courseKey: 'MATH-UPLOAD', origin: 'upload', code: null, sessions: [] });
  state.courseKeys.push('MATH-UPLOAD');

  const { included, left } = subscribableCourses(state);
  assert.deepEqual(included.map((c) => c.courseKey), ['COMP 2611']);
  assert.deepEqual(left.sort(), ['COMP 1601', 'MATH-UPLOAD']);
  assert.ok(!decode(subscriptionToken(state).token).includes('COMP 1601'));
});

test('no link without a published course, or without a publication', () => {
  const empty = new TimetableState({ courses: [] }, null);
  assert.equal(subscriptionToken(empty).token, null);
  assert.match(subscriptionToken(empty).reason, /published timetable/);

  const unknown = stateOf(null, 'COMP 2611');
  assert.equal(subscriptionToken(unknown).token, null);
  assert.match(subscriptionToken(unknown).reason, /Update your courses/);
});

test('each app gets the address in the form it accepts', () => {
  const urls = subscriptionUrls('https://example.test', 'abc_-');
  assert.equal(urls.https, 'https://example.test/api/timetable/calendar.ics?t=abc_-');
  assert.equal(urls.webcal, 'webcal://example.test/api/timetable/calendar.ics?t=abc_-');
  assert.ok(urls.outlook.includes(encodeURIComponent(urls.https)));
  assert.ok(urls.google.startsWith('https://calendar.google.com/'));
});

test('changing the timetable puts a subscription out of date, and undo restores it', () => {
  const state = stateOf(11, 'COMP 2611');
  state.subscribedBody = subscriptionBody(state);
  assert.equal(subscriptionOutOfDate(state), false);

  const lab = state.optionGroups.find((g) => g.type === 'Lab');
  const placed = state.placements.find((p) => p.groupId === lab.groupId);
  const other = lab.sessions.find((s) => s.sessionId !== placed.selectedSessionId);
  state.moveEvent(lab.groupId, other.sessionId, placed.selectedSessionId);
  assert.equal(subscriptionOutOfDate(state), true);

  state.undo();
  assert.equal(subscriptionOutOfDate(state), false);
});

test('a republish the feed can follow keeps the subscription current', () => {
  const state = stateOf(10, 'COMP 2611');
  state.subscribedBody = subscriptionBody(state);
  const again = TimetableState.fromWarehouseResponse({ publicationId: 11, courses: [course('COMP 2611')] });
  for (const s of again.courses[0].sessions) s.sessionId += 40000;

  const before = subscriptionBody(state);
  const result = state.refreshFromWarehouse(again.courses, [], 11);
  carrySubscription(state, before, result);

  assert.equal(subscriptionOutOfDate(state), false);
});

test('a republish that forced a new choice puts the subscription out of date', () => {
  const state = stateOf(10, 'COMP 2611');
  state.subscribedBody = subscriptionBody(state);
  const lab = state.optionGroups.find((g) => g.type === 'Lab');
  const placed = state.placements.find((p) => p.groupId === lab.groupId);

  // The placed lab is withdrawn and four others stay, so nothing says which
  // the student would take: the refresh picks one, the feed shows a note.
  const again = TimetableState.fromWarehouseResponse({ publicationId: 11, courses: [course('COMP 2611')] });
  again.courses[0].sessions = again.courses[0].sessions.filter((s) => s.sessionId !== placed.selectedSessionId);
  for (const s of again.courses[0].sessions) s.sessionId += 40000;

  const before = subscriptionBody(state);
  const result = state.refreshFromWarehouse(again.courses, [], 11);
  carrySubscription(state, before, result);

  assert.equal(result.replaced, 1);
  assert.equal(subscriptionOutOfDate(state), true);
});

test('the subscription is saved with the timetable', () => {
  const state = stateOf(11, 'COMP 2611');
  state.subscribedBody = subscriptionBody(state);
  const saved = JSON.parse(JSON.stringify(state.toSaved()));
  const reloaded = new TimetableState({ courses: saved.courses, publicationId: saved.publicationId }, saved);
  assert.equal(reloaded.subscribedBody, state.subscribedBody);
  assert.equal(subscriptionOutOfDate(reloaded), false);
});
