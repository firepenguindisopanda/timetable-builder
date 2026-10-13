'use strict';

/**
 * What the detail view says about one placed class.
 *
 * The same markup serves the panel beside the event list and the dialog a
 * grid tap opens, so what it states is decided and tested here once.
 */

const test = require('node:test');
const assert = require('node:assert');
const { load, warehouse, course } = require('./harness.js');

const api = load(
  'calendar-utils.js',
  'calendar-events.js',
  'coming-up.js',
  'option-groups.js',
  'placement.js',
  'slot-identity.js',
  'timetable-state.js',
  'detail-view.js'
);
const TimetableState = api.get('TimetableState');
const renderEventDetail = api.get('renderEventDetail');

function stateOf(...codes) {
  const sourceData = TimetableState.fromWarehouseResponse({
    publicationId: warehouse.publicationId,
    courses: codes.map(course),
  });
  const state = new TimetableState(sourceData);
  state.placeMissing();
  return state;
}

/** The model the page assembles before calling the renderer. */
function modelFor(state, groupId, extra) {
  const placement = state.placements.find(p => p.groupId === groupId);
  const details = state.getPlacedEventDetails(groupId, placement.selectedSessionId);
  return Object.assign({
    details,
    sessions: state.getOptions(groupId),
    attendedSessionIds: state.placements
      .filter(p => p.groupId === groupId)
      .map(p => p.selectedSessionId),
    clashing: false,
    idSuffix: 'Test',
  }, extra || {});
}

const LECTURES = 'COMP 1602|Lecture|all';

test('the body names the course, its type and its schedule', () => {
  const state = stateOf('COMP 1602');
  const html = renderEventDetail(modelFor(state, LECTURES));

  assert.match(html, /Schedule/);
  assert.match(html, /Location/);
  assert.match(html, /COMP 1602/);
  assert.match(html, /Lecture/);
});

test('an unpublished field says so rather than rendering blank', () => {
  const state = stateOf('COMP 1602');
  const model = modelFor(state, LECTURES);
  model.details.room = null;
  model.details.staff = [];

  const html = renderEventDetail(model);

  assert.match(html, /Not published/);
});

test('a placement the student made says so', () => {
  const state = stateOf('COMP 1602');
  const model = modelFor(state, LECTURES);

  assert.match(renderEventDetail(model), /Picked for you/);

  model.details.pinned = true;
  assert.match(renderEventDetail(model), /You picked this time/);
});

test('every sitting is listed, the shown one marked and the rest actionable', () => {
  const state = stateOf('COMP 1602');
  const html = renderEventDetail(modelFor(state, LECTURES));

  // COMP 1602 publishes two lectures: the placed one reads "This one" and
  // the other offers itself.
  assert.equal((html.match(/sitting-row/g) || []).length, 2);
  assert.match(html, /This one/);
  assert.match(html, /class="btn btn-outline-secondary btn-sm sitting-add"/);
});

test('a sitting already attended as an extra offers Remove, not Also attend', () => {
  const state = stateOf('COMP 1602');
  const other = state.getOptions(LECTURES).find(
    s => !state.placements.some(
      p => p.groupId === LECTURES && p.selectedSessionId === s.sessionId));
  state.addSitting(LECTURES, other.sessionId);
  const html = renderEventDetail(modelFor(state, LECTURES));

  assert.match(html, /sitting-remove/);
  assert.ok(!html.includes('sitting-add'));
});

test('another time can be chosen with a button, not only by dragging', () => {
  /**
   * Moving a class was drag-only: no keyboard could do it, and a phone needed
   * a one-second press (WCAG 2.5.7). "Use this time" names where it goes and
   * where it comes from, so the page can move exactly that placement.
   */
  const state = stateOf('COMP 1602');
  const model = modelFor(state, LECTURES);
  const html = renderEventDetail(model);
  const other = state.getOptions(LECTURES).find(s => s.sessionId !== model.details.sessionId);

  const button = html.match(/<button[^>]*sitting-use[^>]*>/)[0];
  assert.ok(button.includes(`data-session-id="${other.sessionId}"`));
  assert.ok(button.includes(`data-from-session-id="${model.details.sessionId}"`));
  assert.match(html, />Use this time</);
});

test('a time already attended is not offered to move onto', () => {
  const state = stateOf('COMP 1602');
  const other = state.getOptions(LECTURES).find(
    s => !state.placements.some(
      p => p.groupId === LECTURES && p.selectedSessionId === s.sessionId));
  state.addSitting(LECTURES, other.sessionId);
  assert.ok(!renderEventDetail(modelFor(state, LECTURES)).includes('sitting-use'));
});

test('the actions remove one class or the whole course, and name which', () => {
  const state = stateOf('COMP 1602');
  const html = renderEventDetail(modelFor(state, LECTURES));

  assert.match(html, /detail-remove-class/);
  assert.match(html, /detail-remove-course/);
  assert.match(html, /Remove COMP 1602/);
});

test('a clashing class carries the way into the resolve dialog', () => {
  const state = stateOf('COMP 1602');

  const calm = renderEventDetail(modelFor(state, LECTURES));
  assert.ok(!calm.includes('detail-resolve-clash'));

  const clashing = renderEventDetail(modelFor(state, LECTURES, { clashing: true }));
  assert.match(clashing, /detail-resolve-clash/);
  assert.match(clashing, /Resolve the clash/);
});

test('the raw data region id carries the suffix, so two copies can coexist', () => {
  const state = stateOf('COMP 1602');

  const panel = renderEventDetail(modelFor(state, LECTURES, { idSuffix: 'Panel', showRawData: true }));
  const dialog = renderEventDetail(modelFor(state, LECTURES, { idSuffix: 'Dialog', showRawData: true }));

  assert.match(panel, /id="rawDataContentPanel"/);
  assert.match(panel, /aria-controls="rawDataContentPanel"/);
  assert.match(dialog, /id="rawDataContentDialog"/);
});

test('weeks come from the printed text when that is all there is', () => {
  const state = stateOf('COMP 1602');
  const model = modelFor(state, LECTURES);
  model.details.weeks = null;
  model.details.weeksRaw = 'W1-W12';

  assert.match(renderEventDetail(model), /W1-W12/);
});

test('markup escapes what it prints', () => {
  const state = stateOf('COMP 1602');
  const model = modelFor(state, LECTURES);
  model.details.courseTitle = 'Maths & "Stats" <II>';

  const html = renderEventDetail(model);

  assert.ok(!html.includes('<II>'));
  assert.match(html, /Maths &amp; &quot;Stats&quot; &lt;II&gt;/);
});

test('a menu group offers the split correction, and a split one the way back', () => {
  const state = stateOf('COMP 1602');

  const menu = renderEventDetail(modelFor(state, LECTURES));
  assert.match(menu, /group-split/);

  const model = modelFor(state, LECTURES);
  model.details.groupReason = 'split';
  const split = renderEventDetail(model);
  assert.match(split, /group-reset/);
});

test('a student never sees the raw fields the extractor read', () => {
  // groupId and sessionId are for debugging; only dev tools show them.
  const html = renderEventDetail(modelFor(stateOf('COMP 1602'), LECTURES));
  assert.doesNotMatch(html, /Raw Extracted Data|rawDataContent/);
});

test('weeks come from the full list, not the shorter printed range', () => {
  /**
   * Past weeks are carried forward from earlier publications, so a class
   * that began in week 1 can print "W6-W12". The list is the truth.
   */
  const describeDetailWeeks = api.get('describeDetailWeeks');
  assert.equal(
    describeDetailWeeks({ weeks: [1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 12], weeksRaw: 'W6-W7, W9-W12' }),
    'Weeks 1–7, 9–12'
  );
});

test('a one-week class says so, with its date when the calendar is dated', () => {
  const describeDetailWeeks = api.get('describeDetailWeeks');
  const exam = { weeks: [7], day: 'Thursday', weeksRaw: 'W7' };
  assert.equal(describeDetailWeeks(exam), 'Week 7 only');
  assert.equal(describeDetailWeeks(exam, '2026-08-31'), 'Week 7 only · Thu 15 Oct');
});

// Notes, links and how sure we are

test('the room and lecturer link to their explorer pages', () => {
  const model = modelFor(stateOf('COMP 1602'), LECTURES);
  model.details.room = 'ENG MD3; JFK AUD';
  model.details.staff = ['HOSEIN,Michael'];
  const html = renderEventDetail(model);

  assert.match(html, /href="\/explore\/room\/ENG%20MD3">ENG MD3<\/a>/);
  assert.match(html, /href="\/explore\/room\/JFK%20AUD">JFK AUD<\/a>/);
  assert.match(html, /href="\/explore\/staff\/HOSEIN%2CMichael">HOSEIN,Michael<\/a>/);
});

test('a lecturer not published says so, never "unknown"', () => {
  const model = modelFor(stateOf('COMP 1602'), LECTURES);
  model.details.staff = [];
  assert.match(renderEventDetail(model), /Not published by UWI/);
});

test('an uploaded class is not linked into the explorer', () => {
  const model = modelFor(stateOf('COMP 1602'), LECTURES);
  model.details.origin = 'upload';
  assert.doesNotMatch(renderEventDetail(model), /href="\/explore\//);
});

test('a note from the timetable is shown, escaped', () => {
  const model = modelFor(stateOf('COMP 1602'), LECTURES);
  model.details.notes = 'Bring a laptop <b>';
  const html = renderEventDetail(model);
  assert.match(html, /Note from the timetable/);
  assert.match(html, /Bring a laptop &lt;b&gt;/);
});

test('a class only one UWI timetable lists says to check', () => {
  const describeSources = api.get('describeSources');
  assert.equal(describeSources({ sourceCount: 3 }), 'Listed in 3 UWI timetables');
  assert.match(describeSources({ sourceCount: 1 }), /only one UWI timetable\. Check with your department/);
  assert.equal(describeSources({ origin: 'upload', sourceFile: 'law.pdf' }), 'Your upload: law.pdf');
});

test('each other time says what choosing it would do', () => {
  const state = stateOf('COMP 1602');
  const model = modelFor(state, LECTURES);
  const other = state.getOptions(LECTURES).find(s => s.sessionId !== model.details.sessionId);
  model.optionEffects = { [String(other.sessionId)]: 'Clashes with COMP 2602 Lecture \u00b7 Monday would run 9am\u20135pm' };
  const html = renderEventDetail(model);

  assert.match(html, /class="sitting-effect clashes">Clashes with COMP 2602 Lecture/);
  // The time already shown has nothing to compare against.
  assert.equal((html.match(/sitting-effect/g) || []).length, 1);
});
