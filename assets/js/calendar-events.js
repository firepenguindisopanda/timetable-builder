'use strict';

/**
 * Placed classes as FullCalendar events.
 *
 * The grid used to be drawn by hand inside calendar.html's inline script, the
 * one block of the page with no tests, and both failures recorded in
 * STATUS.md lived there. FullCalendar now draws it, and every decision about
 * what it is handed lives here, where node can check it. FullCalendar is a
 * view only: TimetableState stays the source of truth, and the page replaces
 * the calendar's events from it on every change.
 */

//: Monday of teaching week 1, Semester 1 2026/27, confirmed 22 Sep 2026. The
//: generic week is drawn in this week, with the dates hidden, so that dated
//: weeks later only have to change which week is the anchor.
const ANCHOR_MONDAY = '2026-08-31';

//: The hours the grid has always shown. A class outside them widens the grid
//: rather than being clamped: a clamped block looked shorter than the class.
const DEFAULT_FIRST_HOUR = 8;
const DEFAULT_LAST_HOUR = 22;

//: A class whose end is not after its start still needs a block to click.
const MIN_EVENT_MINS = 30;

/** The key the page uses for one block: an option group and the sitting it shows. */
function eventKeyOf(groupId, sessionId) {
  return String(groupId) + ' ' + String(sessionId);
}

/** Lecture, lab and tutorial carry a hue; every other activity type is "other". */
function typeClassOf(type) {
  const known = ['lecture', 'lab', 'tutorial'];
  const lower = String(type || '').toLowerCase();
  return known.includes(lower) ? lower : 'other';
}

function _pad2(n) {
  return String(n).padStart(2, '0');
}

function _clock(mins) {
  return _pad2(Math.floor(mins / 60)) + ':' + _pad2(mins % 60);
}

/**
 * The date of a weekday in the anchor week.
 *
 * Done in UTC so that a daylight-saving change in the viewer's zone can never
 * move a day; the date is only ever a label for a column.
 */
function _dateOfDay(anchorMonday, dayIndex) {
  const [y, m, d] = anchorMonday.split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, d + dayIndex)).toISOString().slice(0, 10);
}

/**
 * The date of a weekday in a teaching week, as YYYY-MM-DD.
 *
 * The one week-to-date function: the "Coming up" list reads it now, and the
 * dated grid and the calendar export are to share it, so a week cannot mean
 * one date on screen and another in a student's phone. Week 1 is the week of
 * `anchorMonday`. Null for a week or day that is not one.
 */
function dateOfTeachingDay(week, day, anchorMonday = ANCHOR_MONDAY) {
  const dayIndex = DAYS.indexOf(day);
  if (!Number.isInteger(week) || week < 1 || dayIndex === -1) return null;
  return _dateOfDay(anchorMonday, (week - 1) * 7 + dayIndex);
}

// Dated weeks

const _MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

//: The dash between the two ends of a date range.
const RANGE_DASH_WEEK = '–';

/** Whole days from one YYYY-MM-DD to another, counted in UTC. */
function _daysBetween(fromIso, toIso) {
  const at = (iso) => {
    const [y, m, d] = iso.split('-').map(Number);
    return Date.UTC(y, m - 1, d);
  };
  return Math.round((at(toIso) - at(fromIso)) / 86400000);
}

/**
 * The teaching week a date falls in, clamped to the semester.
 *
 * Before week 1 the calendar opens on week 1, and after the last week on the
 * last, so a student looking ahead in August or back in December lands on a
 * week that has classes rather than an empty one.
 */
function teachingWeekOf(todayIso, weekOne, totalWeeks) {
  const week = Math.floor(_daysBetween(weekOne, todayIso) / 7) + 1;
  return Math.min(Math.max(week, 1), totalWeeks);
}

/** "12–18 Oct", or "28 Sep – 4 Oct" when the week crosses a month. */
function weekRangeLabel(week, weekOne) {
  const parts = (iso) => iso.split('-').map(Number);
  const [, m1, d1] = parts(dateOfTeachingDay(week, 'Monday', weekOne));
  const [, m2, d2] = parts(dateOfTeachingDay(week, 'Sunday', weekOne));
  return m1 === m2
    ? `${d1}${RANGE_DASH_WEEK}${d2} ${_MONTHS[m2 - 1]}`
    : `${d1} ${_MONTHS[m1 - 1]} ${RANGE_DASH_WEEK} ${d2} ${_MONTHS[m2 - 1]}`;
}

/**
 * Whether a class runs in a teaching week.
 *
 * A class with no week list runs every week. Every uploaded PDF is like that,
 * and the clash check already treats it as "every week", so the grid and the
 * clash panel agree about when it is on.
 */
function runsInWeek(event, week) {
  return !Array.isArray(event.weeks) || event.weeks.length === 0 || event.weeks.includes(week);
}

/** The placed classes on in one week. */
function eventsInWeek(placedEvents, week) {
  return placedEvents.filter((event) => runsInWeek(event, week));
}

/**
 * Placed classes that are not on in a week, and why.
 *
 * "gap" is a week missing from the middle of a class's run, which is how a
 * cancellation shows up: 45 classes dropped week 8, graduation week, in the
 * 9 Oct 2026 republish. "finished" and "starts" are the ends of a run. Without
 * this a class simply vanished from a week's grid with nothing to say why.
 */
function weekAbsences(placedEvents, week) {
  const absences = [];
  for (const event of placedEvents) {
    if (runsInWeek(event, week)) continue;
    const first = Math.min(...event.weeks);
    const last = Math.max(...event.weeks);
    const reason = week < first ? 'starts' : week > last ? 'finished' : 'gap';
    absences.push({
      courseKey: event.courseKey,
      label: event.code || event.courseKey,
      type: event.type,
      reason,
      first,
      last,
    });
  }
  const order = { gap: 0, starts: 1, finished: 2 };
  return absences.sort((a, b) =>
    order[a.reason] - order[b.reason]
    || String(a.label).localeCompare(String(b.label))
    || String(a.type || '').localeCompare(String(b.type || '')));
}

/** The week bar's sentence about classes not on this week, or "". */
function weekAbsenceText(absences) {
  if (!absences.length) return '';
  const why = (a) => (a.reason === 'gap' ? 'no class this week'
    : a.reason === 'starts' ? `starts week ${a.first}`
      : `finished week ${a.last}`);
  return 'Not on this week: ' + absences
    .map((a) => [a.label, a.type, `(${why(a)})`].filter(Boolean).join(' '))
    .join(', ');
}

/**
 * Exams and other dated one-offs as FullCalendar events for one week.
 *
 * Shown on the grid so a student sees an exam beside the week's classes, but
 * never draggable: they are not a choice. Sittings of the same course and type
 * at the same time are one block, as in the "Coming up" list.
 */
function toDatedEvents(datedSessions, week, weekOne) {
  const byKey = new Map();
  for (const session of datedSessions || []) {
    if (!Array.isArray(session.weeks) || !session.weeks.includes(week)) continue;
    const date = dateOfTeachingDay(week, session.day, weekOne);
    if (!date) continue;
    const key = [session.courseKey, session.type, session.day,
      session.startTime, session.endTime].join('|');
    if (!byKey.has(key)) {
      const startMins = timeToMins(session.startTime);
      const rawEnd = timeToMins(session.endTime);
      const endMins = rawEnd > startMins ? rawEnd : startMins + MIN_EVENT_MINS;
      byKey.set(key, {
        id: 'dated ' + key,
        start: `${date}T${_clock(startMins)}:00`,
        end: `${date}T${_clock(endMins)}:00`,
        className: 'calendar-event other dated',
        editable: false,
        // Not a button: there is nothing to choose or open. The "Coming up"
        // list says the same thing in text a keyboard can reach.
        interactive: false,
        extendedProps: {
          dated: true,
          courseKey: session.courseKey,
          label: session.courseKey,
          type: session.type,
          day: session.day,
          startTime: session.startTime,
          endTime: session.endTime,
          rooms: [],
          pinned: false,
          clash: false,
        },
      });
    }
    const props = byKey.get(key).extendedProps;
    for (const room of String(session.room || '').split(';')) {
      const name = room.trim();
      if (name && !props.rooms.includes(name)) props.rooms.push(name);
    }
  }
  return [...byKey.values()].map((event) => {
    const rooms = event.extendedProps.rooms.sort((a, b) => a.localeCompare(b));
    event.extendedProps.room = rooms.join('; ') || null;
    return event;
  });
}

/**
 * Placed events as FullCalendar event inputs, in the anchor week.
 *
 * Dated in a fixed week rather than with FullCalendar's `daysOfWeek`
 * recurrence, so each class is one event with one id. Times are local
 * wall-clock strings with no offset, which FullCalendar reads in the
 * viewer's own zone. `clashKeys` holds the event keys of genuine clashes.
 */
function toCalendarEvents(placedEvents, clashKeys, anchorMonday = ANCHOR_MONDAY) {
  const events = [];
  for (const event of placedEvents) {
    const dayIndex = DAYS.indexOf(event.day);
    if (dayIndex === -1) continue;

    const date = _dateOfDay(anchorMonday, dayIndex);
    const startMins = timeToMins(event.startTime);
    const rawEndMins = timeToMins(event.endTime);
    const endMins = rawEndMins > startMins ? rawEndMins : startMins + MIN_EVENT_MINS;
    const key = eventKeyOf(event.groupId, event.sessionId);
    const clash = clashKeys.has(key);
    const pinned = Boolean(event.pinned);

    events.push({
      id: key,
      start: `${date}T${_clock(startMins)}:00`,
      end: `${date}T${_clock(endMins)}:00`,
      className: ['calendar-event', typeClassOf(event.type)]
        .concat(clash ? ['clash'] : [], pinned ? ['pinned'] : [])
        .join(' '),
      extendedProps: {
        groupId: event.groupId,
        sessionId: event.sessionId,
        courseKey: event.courseKey,
        label: event.code || event.courseKey || event.courseTitle || '?',
        type: event.type,
        day: event.day,
        startTime: event.startTime,
        endTime: event.endTime,
        room: event.room,
        pinned,
        clash,
      },
    });
  }
  return events;
}

/**
 * The hours to show: the usual 08:00 to 22:00, widened to whole hours around
 * any class outside them, so no class is ever cut off by the axis.
 */
function visibleRange(placedEvents) {
  let first = DEFAULT_FIRST_HOUR * 60;
  let last = DEFAULT_LAST_HOUR * 60;
  for (const event of placedEvents) {
    first = Math.min(first, timeToMins(event.startTime));
    last = Math.max(last, timeToMins(event.endTime));
  }
  const firstHour = Math.floor(first / 60);
  const lastHour = Math.min(24, Math.ceil(last / 60));
  return { slotMinTime: _clock(firstHour * 60), slotMaxTime: _clock(lastHour * 60) };
}

// Dragging a class to one of its alternatives

/**
 * Where a dragged class may land: its option group's sittings, minus any that
 * another placement of the same group already shows.
 *
 * Landing on one of those would fold two attended sittings into one block.
 * The dragged class's own sitting stays a target, because dropping a class
 * back where it stands is how a student pins it there.
 */
function dropTargets(options, placements, groupId, draggedSessionId) {
  const taken = new Set(placements
    .filter(p => p.groupId === groupId && p.selectedSessionId !== draggedSessionId)
    .map(p => p.selectedSessionId));
  return options.filter(session => !taken.has(session.sessionId));
}

/**
 * The sitting a drop landed on, or null to put the class back.
 *
 * The drop counts where its middle lands, as the hand-built grid counted the
 * centre of the block. A drop between sittings lands nowhere rather than on
 * the nearer one: snapping would move a class somewhere the student did not
 * aim. Two rooms running the same sitting both contain the middle, and the
 * first in option order wins, as the first drop zone did before.
 */
function resolveDrop(targets, droppedDay, droppedStartMins, durationMins) {
  const middle = droppedStartMins + durationMins / 2;
  const hit = targets.find(session => session.day === droppedDay
    && timeToMins(session.startTime) <= middle
    && middle < timeToMins(session.endTime));
  return hit ? hit.sessionId : null;
}

/** Drop targets as FullCalendar background events in the anchor week. */
function toDropZones(targets, anchorMonday = ANCHOR_MONDAY) {
  return targets
    .filter(session => DAYS.includes(session.day))
    .map(session => {
      const date = _dateOfDay(anchorMonday, DAYS.indexOf(session.day));
      return {
        start: `${date}T${_clock(timeToMins(session.startTime))}:00`,
        end: `${date}T${_clock(timeToMins(session.endTime))}:00`,
        display: 'background',
        className: 'drop-zone',
      };
    });
}
