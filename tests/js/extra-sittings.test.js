'use strict';

/**
 * The one-of-each rule is a guide for auto-placement, not a wall.
 *
 * A student attends one lecture, one lab and one tutorial per course per week,
 * and that is still what auto-placement builds. But the timetable is theirs:
 * they can attend a second sitting, or drop a class entirely, and neither
 * choice may be undone for them by the next load.
 */

const test = require('node:test');
const assert = require('node:assert');
const { load, warehouse, course } = require('./harness.js');

const api = load(
  'calendar-utils.js',
  'option-groups.js',
  'placement.js',
  'timetable-state.js'
);
const TimetableState = api.get('TimetableState');

function response(...codes) {
  return {
    publicationId: warehouse.publicationId,
    courses: codes.map(course),
    notFound: [],
  };
}

function stateOf(...codes) {
  const sourceData = TimetableState.fromWarehouseResponse(response(...codes));
  const state = new TimetableState(sourceData);
  state.placeMissing();
  return state;
}

function placementsOf(state, groupId) {
  return state.placements.filter(p => p.groupId === groupId);
}

const LECTURES = 'COMP 1602|Lecture|all';

/** The group's sessions that no placement currently shows. */
function unattendedSession(state, groupId) {
  const shown = new Set(placementsOf(state, groupId).map(p => p.selectedSessionId));
  return state.getOptions(groupId).find(s => !shown.has(s.sessionId));
}

// Attending more than one sitting


test('a second sitting joins the grid beside the first', () => {
  const state = stateOf('COMP 1602');
  const extra = unattendedSession(state, LECTURES);

  assert.equal(state.addSitting(LECTURES, extra.sessionId), true);

  const placements = placementsOf(state, LECTURES);
  assert.equal(placements.length, 2);
  assert.equal(state.getPlacedEvents()
    .filter(e => e.groupId === LECTURES).length, 2);
});

test('an added sitting is pinned, because the student chose it', () => {
  const state = stateOf('COMP 1602');
  const extra = unattendedSession(state, LECTURES);

  state.addSitting(LECTURES, extra.sessionId);

  const added = placementsOf(state, LECTURES)
    .find(p => p.selectedSessionId === extra.sessionId);
  assert.equal(added.pinned, true);
});

test('a sitting already attended cannot be added twice', () => {
  const state = stateOf('COMP 1602');
  const [placed] = placementsOf(state, LECTURES);

  assert.equal(state.addSitting(LECTURES, placed.selectedSessionId), false);
  assert.equal(placementsOf(state, LECTURES).length, 1);
});

test('details name the specific sitting when a group holds two', () => {
  const state = stateOf('COMP 1602');
  const extra = unattendedSession(state, LECTURES);
  state.addSitting(LECTURES, extra.sessionId);

  const details = state.getPlacedEventDetails(LECTURES, extra.sessionId);
  assert.equal(details.sessionId, extra.sessionId);
  assert.equal(details.attendedCount, 2);
});

// Removing one class


test('removing one sitting leaves its twin in place', () => {
  const state = stateOf('COMP 1602');
  const extra = unattendedSession(state, LECTURES);
  state.addSitting(LECTURES, extra.sessionId);
  const [first] = placementsOf(state, LECTURES);

  state.removePlacement(LECTURES, first.selectedSessionId);

  const left = placementsOf(state, LECTURES);
  assert.equal(left.length, 1);
  assert.equal(left[0].selectedSessionId, extra.sessionId);
});

test('emptying a group dismisses it, so placeMissing does not refill it', () => {
  const state = stateOf('COMP 1602');
  const [placed] = placementsOf(state, LECTURES);

  state.removePlacement(LECTURES, placed.selectedSessionId);
  assert.equal(placementsOf(state, LECTURES).length, 0);

  state.placeMissing();
  assert.equal(placementsOf(state, LECTURES).length, 0);
});

test('a dismissed group survives a save and reload', () => {
  const state = stateOf('COMP 1602');
  const [placed] = placementsOf(state, LECTURES);
  state.removePlacement(LECTURES, placed.selectedSessionId);

  const saved = state.toSaved();
  const reloaded = new TimetableState(
    { courses: saved.courses, publicationId: saved.publicationId },
    saved
  );
  reloaded.placeMissing();

  assert.equal(placementsOf(reloaded, LECTURES).length, 0);
});

test('adding any sitting back lifts the dismissal', () => {
  const state = stateOf('COMP 1602');
  const [placed] = placementsOf(state, LECTURES);
  const keptId = placed.selectedSessionId;
  state.removePlacement(LECTURES, keptId);

  assert.equal(state.addSitting(LECTURES, keptId), true);
  assert.deepEqual(state.dismissedGroups, []);
});

test('undo restores a removed class, dismissal and all', () => {
  const state = stateOf('COMP 1602');
  const [placed] = placementsOf(state, LECTURES);
  state.removePlacement(LECTURES, placed.selectedSessionId);

  state.undo();

  assert.equal(placementsOf(state, LECTURES).length, 1);
  assert.deepEqual(state.dismissedGroups, []);
});

test('removing a course clears its dismissals, so re-adding places fully', () => {
  const state = stateOf('COMP 1602');
  const [placed] = placementsOf(state, LECTURES);
  state.removePlacement(LECTURES, placed.selectedSessionId);

  state.removeCourse('COMP 1602');
  state.addCourses(TimetableState.fromWarehouseResponse(
    response('COMP 1602')).courses);

  assert.equal(placementsOf(state, LECTURES).length, 1);
});

test('re-optimising does not resurrect a dismissed class', () => {
  const state = stateOf('COMP 1602');
  const [placed] = placementsOf(state, LECTURES);
  state.removePlacement(LECTURES, placed.selectedSessionId);

  state.reoptimise();

  assert.equal(placementsOf(state, LECTURES).length, 0);
});

test('re-optimising keeps a pinned extra and re-places around it', () => {
  const state = stateOf('COMP 1602');
  const extra = unattendedSession(state, LECTURES);
  state.addSitting(LECTURES, extra.sessionId);

  state.reoptimise();

  const placements = placementsOf(state, LECTURES);
  assert.equal(placements.length, 2);
  assert.ok(placements.some(p => p.selectedSessionId === extra.sessionId && p.pinned));
  // The two placements still show two different sittings.
  assert.notEqual(placements[0].selectedSessionId, placements[1].selectedSessionId);
});

// Moving when a group holds more than one placement


test('moving names which of two sittings moves, and only that one moves', () => {
  const state = stateOf('COMP 1602');
  const [first] = placementsOf(state, LECTURES);
  const firstId = first.selectedSessionId;
  const extra = unattendedSession(state, LECTURES);
  state.addSitting(LECTURES, extra.sessionId);

  // COMP 1602 publishes two lectures, so the only legal move collapses onto
  // the twin. That must be refused rather than produce a duplicate.
  state.moveEvent(LECTURES, extra.sessionId, firstId);

  const shown = placementsOf(state, LECTURES).map(p => p.selectedSessionId);
  assert.deepEqual(new Set(shown).size, shown.length);
});

test('a drop on its own slot still pins, as it always has', () => {
  const state = stateOf('COMP 1602');
  const [placed] = placementsOf(state, LECTURES);
  assert.equal(placed.pinned, false);

  state.moveEvent(LECTURES, placed.selectedSessionId);

  assert.equal(placementsOf(state, LECTURES)[0].pinned, true);
});

// Conflicts when pinning is per placement


test('a fix names the placement it moves, not just the group', () => {
  const state = stateOf('AGBU 1005', 'BIOL 1262');
  // Recreate the clash a student makes by hand: BIOL 1262's lab sits on
  // Monday 14:00-18:00, and pinning an AGBU tutorial into that window
  // collides with it. The pinned side may not move, so the fix must move the
  // lab, and must say which of the lab group's placements it means.
  const lab = state.getPlacedEvents().find(
    e => e.courseKey === 'BIOL 1262' && e.type === 'Lab');
  assert.equal(lab.day, 'Monday', 'fixture no longer places the lab on Monday');
  const agbuTutorials = 'AGBU 1005|Tutorial|all';
  const colliding = state.getOptions(agbuTutorials).find(
    s => s.day === 'Monday' && s.startTime === '15:00');
  assert.ok(colliding, 'fixture no longer poses the Monday 15:00 clash');
  state.moveEvent(agbuTutorials, colliding.sessionId);

  const conflicts = state.getClassifiedConflicts();
  assert.ok(conflicts.length > 0);
  const withFix = conflicts.find(c => c.resolvable);
  assert.ok(withFix, 'expected at least one resolvable clash');
  assert.equal(withFix.fix.groupId, 'BIOL 1262|Lab|all');
  assert.equal(withFix.fix.fromSessionId, lab.sessionId);
});
