'use strict';

/**
 * The shape of a timetable on paper.
 *
 * Everything here is pure: given the same placed events it returns the same
 * model, with no DOM, no clock and no `state`. That matters twice over. It
 * makes the printout testable without a browser, and it keeps the one piece
 * of logic ICS export will also need, a flat null-safe list of classes with
 * course, type, day, times, room, staff and weeks resolved, in a place a
 * second exporter can reach.
 *
 * Nothing in here decides how the page *looks*. It decides what is on it.
 *
 * See PRINT-EXPORT-SPEC.md.
 */

/**
 * Course colours, for white paper.
 *
 * The screen palette is tuned for a near-black background and cannot be
 * reused: `--accent-cyan` #00E5FF sits at about 1.5:1 on white. These eight
 * were picked to clear 4.5:1 instead, so each can carry bold 10pt text, and
 * measure 6.26:1 to 11.32:1.
 *
 * They are deliberately NOT spread across the grey range, because they cannot
 * be: eight hues dark enough for text all land between 24% and 38% grey, some
 * within two points of each other. On a black-and-white printer they are
 * indistinguishable. That is why the swatch also carries a fill treatment for
 * the activity type, and why the course code and type are always printed as
 * words. Colour is the third copy of the information, never the only one.
 */
const PRINT_PALETTE = Object.freeze([
  Object.freeze({ hex: '#14487F', name: 'blue' }),
  Object.freeze({ hex: '#9A4A00', name: 'orange' }),
  Object.freeze({ hex: '#1B5E20', name: 'green' }),
  Object.freeze({ hex: '#6A1B7A', name: 'purple' }),
  Object.freeze({ hex: '#96123C', name: 'crimson' }),
  Object.freeze({ hex: '#00564F', name: 'teal' }),
  Object.freeze({ hex: '#5C4700', name: 'olive' }),
  Object.freeze({ hex: '#4E342E', name: 'brown' }),
]);

/** Lecturers past this many are summarised, so one line cannot run away. */
const STAFF_SHOWN = 3;

/** Separates the two ends of a range, in weeks and in times alike. */
const RANGE_DASH = '-';

/**
 * The activity type, reduced to the four the printout can draw.
 *
 * `normalizeType` matches whole strings against an alias table, which handles
 * the short forms an upload might carry ("LEC", "tute") but reads every
 * multi-word published type as "Other". CELCAT publishes several: "Lecture
 * Relocated" is 6 of the 224 sessions in the fixture and "Tutorial
 * (make-up/relocated)" one more. To a student those are a lecture and a
 * tutorial, so fall back to matching the words inside the phrase.
 *
 * "Lecture & Tutorial" is checked against "lecture" first and prints as a
 * lecture, on the grounds that the lecture is the part you cannot skip.
 */
function printTypeClass(type) {
  if (!type) return 'other';

  const alias = normalizeType(type);
  if (alias === 'Lecture') return 'lecture';
  if (alias === 'Lab') return 'lab';
  if (alias === 'Tutorial') return 'tutorial';

  // Word boundaries, not bare `includes`, so a future "Collaborative Studio"
  // is not filed as a lab.
  const text = String(type).toLowerCase();
  if (/\blectures?\b/.test(text)) return 'lecture';
  if (/\blabs?\b|\blaborator/.test(text) || /\bpractical/.test(text)) return 'lab';
  if (/\btutorials?\b/.test(text)) return 'tutorial';
  return 'other';
}

/**
 * Teaching weeks as a student would write them.
 *
 * `[1..12]` is "Wks 1-12", `[2,3,4,8,9]` is "Wks 2-4, 8-9", `[5]` is "Wk 5".
 * Null is null rather than "every week": only the caller knows whether the
 * absence means the class runs always or that an uploaded PDF never said.
 */
function formatWeeks(weeks) {
  if (!Array.isArray(weeks) || weeks.length === 0) return null;

  const sorted = [...new Set(weeks)]
    .filter(w => Number.isFinite(w))
    .sort((a, b) => a - b);
  if (sorted.length === 0) return null;

  const runs = [];
  let start = sorted[0];
  let prev = sorted[0];
  for (let i = 1; i < sorted.length; i++) {
    if (sorted[i] === prev + 1) {
      prev = sorted[i];
      continue;
    }
    runs.push([start, prev]);
    start = sorted[i];
    prev = sorted[i];
  }
  runs.push([start, prev]);

  const parts = runs.map(
    ([from, to]) => (from === to ? String(from) : `${from}${RANGE_DASH}${to}`)
  );
  return `${sorted.length === 1 ? 'Wk' : 'Wks'} ${parts.join(', ')}`;
}

/** The widest run of teaching weeks anything on the timetable uses. */
function weeksSpan(events) {
  let min = null;
  let max = null;
  for (const event of events) {
    if (!Array.isArray(event.weeks)) continue;
    for (const week of event.weeks) {
      if (!Number.isFinite(week)) continue;
      if (min === null || week < min) min = week;
      if (max === null || week > max) max = week;
    }
  }
  return min === null ? null : { min, max };
}

/**
 * Whether a class sits out part of the semester.
 *
 * Emphasised on the page, because "this one is not like the others" is the
 * whole reason to print weeks at all. A class with no week data is not
 * restricted: unknown is not the same as narrow.
 */
function isWeeksRestricted(weeks, span) {
  if (!span) return false;
  if (!Array.isArray(weeks) || weeks.length === 0) return false;
  const present = new Set(weeks);
  for (let week = span.min; week <= span.max; week++) {
    if (!present.has(week)) return true;
  }
  return false;
}

/** Title case that survives an apostrophe: "O'BRIEN" stays "O'Brien". */
function _titleCase(text) {
  return String(text).replace(
    /[A-Za-zÀ-ɏ]+/g,
    word => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase()
  );
}

/**
 * One lecturer, as printed.
 *
 * The warehouse stores them shouted and surname-first, "AUSTIN,Nigel", which
 * is right for sorting and wrong for reading.
 */
function formatPersonName(raw) {
  const text = String(raw === null || raw === undefined ? '' : raw).trim();
  if (!text) return null;

  const comma = text.indexOf(',');
  if (comma === -1) return _titleCase(text);

  const surname = text.slice(0, comma).trim();
  const given = text.slice(comma + 1).trim();
  if (!given) return _titleCase(surname) || null;
  if (!surname) return _titleCase(given) || null;
  return `${_titleCase(given)} ${_titleCase(surname)}`;
}

/**
 * The teaching staff line, or null when there is none.
 *
 * Two shapes arrive here. The warehouse gives an array and leaves it empty
 * when it does not know, which is most of the time: only 90 of the fixture's
 * 224 sessions name anyone. An upload gives a single string, because the
 * extractor types `staff` as `str | None`.
 *
 * Null rather than "Unknown": a column of "Unknown" is worse than a short
 * line, and the reader can tell the difference between absent and unknown
 * without being told.
 */
function formatStaff(staff) {
  if (staff === null || staff === undefined) return null;

  const raw = Array.isArray(staff) ? staff : [staff];
  const names = raw.map(formatPersonName).filter(Boolean);
  if (names.length === 0) return null;
  if (names.length <= STAFF_SHOWN) return names.join(', ');

  const shown = names.slice(0, STAFF_SHOWN).join(', ');
  return `${shown} +${names.length - STAFF_SHOWN} more`;
}

/** "09:00" and "11:00" become "09:00-11:00", with the print dash. */
function formatTimeRange(startTime, endTime) {
  if (!startTime && !endTime) return null;
  if (!endTime) return String(startTime);
  if (!startTime) return String(endTime);
  return `${startTime}${RANGE_DASH}${endTime}`;
}

/**
 * Which of the eight colours a course gets.
 *
 * Indexed off the sorted key list, so the same timetable prints the same way
 * every time. It is not stable across edits, since adding "AGBU 1005" to a
 * timetable that starts at "COMP 1601" shifts everything down one, but the
 * legend is printed on the same page so a reprint explains itself. Hashing
 * would survive edits at the cost of letting two courses collide on one
 * colour, which is the worse failure.
 */
function courseColourIndex(courseKey, orderedKeys) {
  const at = orderedKeys.indexOf(courseKey);
  return at === -1 ? 0 : at % PRINT_PALETTE.length;
}

/** Start time, then course, then type: two classes at once still have an order. */
function _compareEntries(a, b) {
  const byTime = timeToMins(a.startTime) - timeToMins(b.startTime);
  if (byTime !== 0) return byTime;
  const byCourse = String(a.courseKey).localeCompare(String(b.courseKey));
  if (byCourse !== 0) return byCourse;
  return String(a.type || '').localeCompare(String(b.type || ''));
}

/**
 * Events split into days, in week order, empty days dropped.
 *
 * A day the calendar does not recognise is kept and appended rather than
 * filtered out. It should not happen, but a printout that silently loses a
 * class is worse than one with an odd heading on it.
 */
function groupByDay(events) {
  const byDay = new Map();
  for (const event of events) {
    const day = event.day;
    if (!byDay.has(day)) byDay.set(day, []);
    byDay.get(day).push(event);
  }

  const known = DAYS.filter(day => byDay.has(day));
  const unknown = [...byDay.keys()].filter(day => !DAYS.includes(day));

  return [...known, ...unknown].map(day => ({
    day,
    entries: byDay.get(day).slice().sort(_compareEntries),
  }));
}

function _entry(event, orderedKeys, span) {
  const weeks = Array.isArray(event.weeks) ? event.weeks : null;
  return {
    startTime: event.startTime,
    endTime: event.endTime,
    time: formatTimeRange(event.startTime, event.endTime),
    courseKey: event.courseKey,
    courseTitle: event.courseTitle || event.courseKey,
    colourIndex: courseColourIndex(event.courseKey, orderedKeys),
    // "Class" rather than an empty slot: 136 of the corpus's entries publish
    // no type at all, and a blank there reads as a rendering fault.
    type: event.type || 'Class',
    typeClass: printTypeClass(event.type),
    room: event.room || null,
    staff: formatStaff(event.staff),
    streamLabel: event.streamLabel || null,
    weeks: formatWeeks(weeks),
    weeksRestricted: isWeeksRestricted(weeks, span),
  };
}

function _clash(conflict) {
  const a = conflict.a || {};
  const b = conflict.b || {};
  return {
    day: conflict.day || a.day || null,
    courseA: conflict.courseA || a.courseKey || null,
    timeA: formatTimeRange(a.startTime, a.endTime) || conflict.timeA || null,
    courseB: conflict.courseB || b.courseKey || null,
    timeB: formatTimeRange(b.startTime, b.endTime) || conflict.timeB || null,
    // Null carries "every week they both run" through from `sharedWeeks`.
    weeks: formatWeeks(conflict.weeks),
    sameCourse: Boolean(conflict.sameCourse),
  };
}

/**
 * Everything the printed page needs, and nothing about how it looks.
 *
 * Takes an options object rather than five positional arguments because four
 * of the five are lists and transposing two of them would be silent.
 *
 * `printedAt` is supplied by the caller instead of read from the clock here,
 * so that the model stays pure and two runs of the tests cannot disagree.
 */
function buildPrintModel(input) {
  const options = input || {};
  const events = Array.isArray(options.events) ? options.events : [];
  const conflicts = Array.isArray(options.conflicts) ? options.conflicts : [];
  const sourceCourses = Array.isArray(options.courses) ? options.courses : [];
  const unplaced = Array.isArray(options.unplaced) ? options.unplaced : [];
  const meta = options.meta || {};

  const orderedKeys = [...new Set(events.map(e => e.courseKey))].sort();
  const span = weeksSpan(events);

  const byKey = new Map(sourceCourses.map(c => [c.courseKey, c]));
  const titleFromEvents = new Map();
  for (const event of events) {
    if (event.courseTitle && !titleFromEvents.has(event.courseKey)) {
      titleFromEvents.set(event.courseKey, event.courseTitle);
    }
  }

  const courses = orderedKeys.map(courseKey => {
    const course = byKey.get(courseKey) || null;
    return {
      courseKey,
      courseTitle:
        (course && course.title)
        || titleFromEvents.get(courseKey)
        || courseKey,
      colourIndex: courseColourIndex(courseKey, orderedKeys),
      // A course the current publication dropped is still on the timetable
      // and still printable, but saying so is the point.
      stale: Boolean(course && course.stale),
      origin: (course && course.origin) || null,
    };
  });

  return {
    meta: {
      title: meta.title || 'My Timetable',
      publication: meta.publication || null,
      printedAt: meta.printedAt || null,
      courseCount: courses.length,
      classCount: events.length,
    },
    courses,
    days: groupByDay(events).map(({ day, entries }) => ({
      day,
      entries: entries.map(event => _entry(event, orderedKeys, span)),
    })),
    clashes: conflicts.map(_clash),
    unplaced: unplaced.map(item => ({
      courseKey: item.courseKey || null,
      type: item.type || 'Class',
    })),
  };
}
