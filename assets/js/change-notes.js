'use strict';

/**
 * Saying what a republish did to one student's timetable.
 *
 * `/api/timetable/changes` answers with the shape of a change; this turns
 * that into the sentence a student reads. It is kept out of the calendar's
 * inline script because wording is the part most likely to be wrong, and the
 * part cheapest to test: no DOM is touched here, so the whole vocabulary is
 * pinned by `tests/js/change-notes.test.js`.
 *
 * Two things it is careful about.
 *
 * **A confirmed venue is not a move.** It is the largest category in a real
 * republish and it is good news; wording it as "moved" sends a student
 * looking for a change to their week that did not happen.
 *
 * **A course losing a whole activity type is not a class going missing.** The
 * option group a saved timetable placed is keyed on the type, so the
 * placement is stranded rather than moved, and there is nothing the app can
 * do about it. That one says to ask the department.
 */

/** Changes a student should act on, as against ones that are merely news. */
const ACT = 'act';
const INFO = 'info';

function _short(day) {
  return String(day || '').slice(0, 3);
}

/** Where a sitting is, as a student would say it aloud. */
function _at(slot) {
  if (!slot) return '';
  const day = _short(slot.day);
  return slot.startTime ? day + ' ' + slot.startTime : day;
}

function _sameTime(a, b) {
  return !!a && !!b && a.day === b.day && a.startTime === b.startTime
    && a.endTime === b.endTime;
}

/**
 * Describe a move, which has more shapes than "it is on a different day".
 *
 * A class can change room without moving, change weeks without moving, or
 * change several sittings at once. Each reads differently and only the last
 * is worth sending someone to the full page for.
 */
function _describeMove(change, type, before, after) {
  if (before.length > 1 || after.length > 1) {
    return { severity: ACT, text: type + ' timetable changed' };
  }
  const b = before[0];
  const a = after[0];
  if (!b || !a) return { severity: ACT, text: type + ' changed' };

  if (_sameTime(a, b)) {
    if ((a.room || '') !== (b.room || '')) {
      return { severity: ACT, text: type + ' moved to ' + (a.room || 'a room not yet published') };
    }
    if ((a.weeks || '') !== (b.weeks || '')) {
      return { severity: ACT, text: type + ' now runs ' + a.weeks };
    }
    return { severity: ACT, text: type + ' changed' };
  }
  return { severity: ACT, text: type + ' moved from ' + _at(b) + ' to ' + _at(a) };
}

/**
 * One change, as a line under the student's own course code.
 *
 * Returns `{ code, text, severity }`. `code` is what the student's timetable
 * holds, which for a rename is the *old* code - the one they are looking at
 * and would otherwise not recognise.
 */
function describeChange(change) {
  const kind = change.displayKind || change.changeType;
  const type = change.activityType || 'class';
  const before = change.before || [];
  const after = change.after || [];
  const code = kind === 'course_renamed' && change.previousCode
    ? change.previousCode
    : change.code;

  let described;
  switch (kind) {
    case 'course_renamed':
      described = { severity: INFO, text: 'is now published as ' + change.code };
      break;
    case 'course_dropped':
      described = { severity: ACT, text: 'is no longer published' };
      break;
    case 'course_added':
      described = { severity: INFO, text: 'has been added to the timetable' };
      break;
    case 'class_venue_confirmed':
      described = {
        severity: INFO,
        text: type + ' venue confirmed: ' + ((after[0] && after[0].room) || 'a room'),
      };
      break;
    case 'class_removed':
      described = change.lastOfType
        ? {
            severity: ACT,
            text: 'no longer has a published ' + type
                + ' — check with your department',
          }
        : { severity: ACT, text: type + ' removed' };
      break;
    case 'class_added':
      described = { severity: INFO, text: 'new ' + type + ' — ' + _at(after[0]) };
      break;
    case 'sitting_added':
      described = { severity: INFO, text: 'extra ' + type + ' — ' + _at(after[0]) };
      break;
    case 'sitting_removed':
      described = {
        severity: ACT,
        text: 'one ' + type + ' sitting dropped — was ' + _at(before[0]),
      };
      break;
    case 'class_moved':
      described = _describeMove(change, type, before, after);
      break;
    default:
      described = { severity: ACT, text: type + ' changed' };
  }

  return { code: code, text: described.text, severity: described.severity };
}

/**
 * Everything that happened to a student's courses, ready to render.
 *
 * Lines needing action come first: a lecture that no longer exists matters
 * more than a room being filled in, and a student who reads only the first
 * line should read the one that costs them something.
 */
function summariseChanges(changes) {
  const lines = (changes || []).map(describeChange);
  const act = lines.filter(function (l) { return l.severity === ACT; });
  const info = lines.filter(function (l) { return l.severity !== ACT; });
  const ordered = act.concat(info);

  return {
    total: ordered.length,
    actionable: act.length,
    lines: ordered,
    headline: ordered.length === 0
      ? 'None of your classes moved'
      : ordered.length + ' of your classes changed',
  };
}
