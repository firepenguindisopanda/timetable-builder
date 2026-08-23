'use strict';

/**
 * What the resolve dialog shows a student, decided before any DOM exists.
 */

const test = require('node:test');
const assert = require('node:assert');
const { load, warehouse, course } = require('./harness.js');

const api = load(
  'calendar-utils.js',
  'option-groups.js',
  'placement.js',
  'timetable-state.js',
  'conflict-resolve.js'
);
const TimetableState = api.get('TimetableState');
const buildResolveModel = api.get('buildResolveModel');
const renderResolveDialog = api.get('renderResolveDialog');

/**
 * A state carrying the one clash the whole file talks about: BIOL 1262's
 * Monday 14:00-18:00 lab, with an AGBU 1005 tutorial pinned into its window.
 */
function clashingState() {
  const sourceData = TimetableState.fromWarehouseResponse({
    publicationId: warehouse.publicationId,
    courses: [course('AGBU 1005'), course('BIOL 1262')],
  });
  const state = new TimetableState(sourceData);
  state.placeMissing();
  const colliding = state.getOptions('AGBU 1005|Tutorial|all').find(
    s => s.day === 'Monday' && s.startTime === '15:00'
  );
  state.moveEvent('AGBU 1005|Tutorial|all', colliding.sessionId);
  return state;
}

function modelOf(state) {
  const conflict = state.getClassifiedConflicts()[0];
  return buildResolveModel(
    conflict,
    state.placements,
    state.groupIndex,
    key => (state.getCourse(key) || {}).title || null
  );
}

test('the model shows both sides of the clash with their courses named', () => {
  const model = modelOf(clashingState());

  assert.equal(model.sides.length, 2);
  const codes = model.sides.map(s => s.courseKey).sort();
  assert.deepEqual(codes, ['AGBU 1005', 'BIOL 1262']);
  assert.ok(model.sides.every(s => s.title));
});

test('each side offers every sitting of its group', () => {
  const state = clashingState();
  const model = modelOf(state);

  for (const side of model.sides) {
    assert.equal(
      side.options.length,
      state.getOptions(side.groupId).length
    );
  }
});

test('the sitting the clash is on is marked current, and knows its collider', () => {
  const model = modelOf(clashingState());

  for (const side of model.sides) {
    const current = side.options.filter(o => o.current);
    assert.equal(current.length, 1);
    const other = model.sides.find(s => s !== side);
    assert.ok(
      current[0].colliders.some(c => c.startsWith(other.courseKey)),
      'the current sitting should name what it clashes with'
    );
  }
});

test('a clash-free alternative reports no colliders', () => {
  const model = modelOf(clashingState());
  const lab = model.sides.find(s => s.courseKey === 'BIOL 1262');

  assert.ok(lab.options.some(o => !o.current && o.colliders.length === 0));
});

test('the pinned side says so, and the fix side carries the suggestion', () => {
  const model = modelOf(clashingState());
  const pinnedSide = model.sides.find(s => s.courseKey === 'AGBU 1005');
  const fixSide = model.sides.find(s => s.courseKey === 'BIOL 1262');

  assert.equal(pinnedSide.pinned, true);
  assert.ok(fixSide.options.some(o => o.recommended));
  assert.ok(pinnedSide.options.every(o => !o.recommended));
});

test('a sitting already attended as an extra is offered as taken, not movable', () => {
  const state = clashingState();
  const extra = state.getOptions('BIOL 1262|Lab|all').find(
    s => !state.placements.some(
      p => p.groupId === 'BIOL 1262|Lab|all' && p.selectedSessionId === s.sessionId
    )
  );
  state.addSitting('BIOL 1262|Lab|all', extra.sessionId);

  const model = modelOf(state);
  const lab = model.sides.find(s => s.courseKey === 'BIOL 1262');
  const taken = lab.options.find(o => o.sessionId === extra.sessionId);
  assert.equal(taken.alsoAttending, true);
});

test('the markup offers buttons for real moves and none for the current sitting', () => {
  const model = modelOf(clashingState());
  const html = renderResolveDialog(model);

  assert.match(html, /AGBU 1005/);
  assert.match(html, /BIOL 1262/);
  assert.match(html, /data-from-session-id=/);
  // The current sitting renders as a div, never as something clickable.
  assert.match(html, /<div class="resolve-option is-current"/);
  assert.match(html, /Where it is now/);
});

test('the markup states the day and the weeks the clash lives in', () => {
  const model = modelOf(clashingState());
  const html = renderResolveDialog(model);

  assert.match(html, /Monday/);
  // Both sides publish weeks, so the dialog says which, not "every week".
  if (model.weeks !== null) {
    assert.match(html, /weeks? \d/);
  }
});

test('markup escapes what it prints', () => {
  const model = modelOf(clashingState());
  model.sides[0].title = 'Maths & "Stats" <II>';
  const html = renderResolveDialog(model);

  assert.ok(!html.includes('<II>'));
  assert.match(html, /Maths &amp; &quot;Stats&quot; &lt;II&gt;/);
});
