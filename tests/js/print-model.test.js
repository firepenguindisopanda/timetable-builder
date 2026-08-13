'use strict';

/**
 * What ends up on the printed page.
 *
 * The interesting cases are all absences: no room, no lecturer, no week data,
 * no type. The warehouse is missing at least one of them on most sessions, so
 * the fixtures are real sessions rather than tidy invented ones.
 */

const test = require('node:test');
const assert = require('node:assert');
const { load, course, warehouse } = require('./harness.js');

// Loaded in the order calendar.html lists them: print-model.js uses DAYS,
// timeToMins and normalizeType out of calendar-utils.js.
const api = load('calendar-utils.js', 'print-model.js');
const {
  buildPrintModel,
  formatWeeks,
  formatStaff,
  formatPersonName,
  formatTimeRange,
  printTypeClass,
  courseColourIndex,
  groupByDay,
  weeksSpan,
  isWeeksRestricted,
  PRINT_PALETTE,
} = api.take(
  'buildPrintModel',
  'formatWeeks',
  'formatStaff',
  'formatPersonName',
  'formatTimeRange',
  'printTypeClass',
  'courseColourIndex',
  'groupByDay',
  'weeksSpan',
  'isWeeksRestricted',
  'PRINT_PALETTE'
);

/** A placed event, in the shape `getPlacedEvents` hands over. */
function event(fields) {
  return {
    courseKey: 'COMP 1601',
    courseTitle: 'Introduction to Programming',
    groupId: 'COMP 1601|Lecture|0',
    type: 'Lecture',
    day: 'Monday',
    startTime: '09:00',
    endTime: '11:00',
    room: 'SB1',
    staff: [],
    streamLabel: null,
    weeks: null,
    pinned: false,
    ...fields,
  };
}

/** A real session off the fixture, as a placed event. */
function fixtureEvent(code, predicate) {
  const found = course(code).sessions.find(predicate);
  if (!found) throw new Error(`no matching session in ${code}`);
  return event({
    courseKey: code,
    courseTitle: course(code).title,
    type: found.type,
    day: found.day,
    startTime: found.startTime,
    endTime: found.endTime,
    room: found.room || null,
    staff: found.staff,
    streamLabel: found.streamLabel,
    weeks: found.weeks,
  });
}

// Teaching weeks

test('a contiguous run of weeks prints as a range', () => {
  assert.equal(formatWeeks([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]), 'Wks 1–12');
});

test('gaps in the weeks are kept as separate runs', () => {
  assert.equal(formatWeeks([2, 3, 4, 8, 9]), 'Wks 2–4, 8–9');
});

test('a single week is singular', () => {
  assert.equal(formatWeeks([5]), 'Wk 5');
});

test('scattered single weeks are listed, not collapsed', () => {
  /**
   * BIOL 1262 lectures on alternating weeks. Printing that as "Wks 2–12"
   * would put a student in a lecture theatre five times for nothing.
   */
  assert.equal(formatWeeks([2, 4, 6, 8, 12]), 'Wks 2, 4, 6, 8, 12');
});

test('weeks arrive unsorted and with duplicates and still print in order', () => {
  assert.equal(formatWeeks([3, 1, 2, 3]), 'Wks 1–3');
});

test('no week data is null, not "every week"', () => {
  /**
   * Only the caller knows whether the absence means the class always runs or
   * that an uploaded PDF never said, so the model refuses to guess.
   */
  assert.equal(formatWeeks(null), null);
  assert.equal(formatWeeks([]), null);
  assert.equal(formatWeeks(undefined), null);
});

test('every fixture session produces a printable week range', () => {
  for (const c of warehouse.courses) {
    for (const session of c.sessions) {
      const formatted = formatWeeks(session.weeks);
      assert.ok(
        formatted && formatted.startsWith('Wk'),
        `${c.code} ${session.weeksRaw} formatted as ${formatted}`
      );
    }
  }
});

// Restricted weeks

test('a class running the full span is not marked restricted', () => {
  const span = { min: 1, max: 12 };
  const full = Array.from({ length: 12 }, (_, i) => i + 1);
  assert.equal(isWeeksRestricted(full, span), false);
});

test('a class that starts late is marked restricted', () => {
  const span = { min: 1, max: 12 };
  const late = Array.from({ length: 10 }, (_, i) => i + 3);
  assert.equal(isWeeksRestricted(late, span), true);
});

test('unknown weeks are not restricted', () => {
  // Unknown is not the same as narrow, and emphasising it would be a lie.
  assert.equal(isWeeksRestricted(null, { min: 1, max: 12 }), false);
});

test('the span covers every placed class', () => {
  const span = weeksSpan([
    event({ weeks: [3, 4, 5] }),
    event({ weeks: [1, 2] }),
    event({ weeks: null }),
  ]);
  assert.deepEqual(span, { min: 1, max: 5 });
});

test('a timetable with no week data anywhere has no span', () => {
  assert.equal(weeksSpan([event({ weeks: null })]), null);
});

// Activity types

test('the three main types map to their own treatment', () => {
  assert.equal(printTypeClass('Lecture'), 'lecture');
  assert.equal(printTypeClass('Lab'), 'lab');
  assert.equal(printTypeClass('Tutorial'), 'tutorial');
});

test('short forms from uploads resolve like the full words', () => {
  assert.equal(printTypeClass('LEC'), 'lecture');
  assert.equal(printTypeClass('tute'), 'tutorial');
  assert.equal(printTypeClass('laboratory'), 'lab');
});

test('a relocated lecture still prints as a lecture', () => {
  /**
   * Six of the fixture's 224 sessions are "Lecture Relocated" and one is
   * "Tutorial (make-up/relocated)". `normalizeType` only knows whole strings
   * and calls both "Other", which would print a student's lecture in the
   * same grey as a Help Desk booking.
   */
  assert.equal(printTypeClass('Lecture Relocated'), 'lecture');
  assert.equal(printTypeClass('Tutorial (make-up/relocated)'), 'tutorial');
});

test('a combined session prints as the part you cannot skip', () => {
  assert.equal(printTypeClass('Lecture & Tutorial'), 'lecture');
});

test('a practical is a lab', () => {
  assert.equal(printTypeClass('Practical'), 'lab');
});

test('types with no treatment of their own fall through to other', () => {
  assert.equal(printTypeClass('Seminar'), 'other');
  assert.equal(printTypeClass('Chemistry Review Centre'), 'other');
  assert.equal(printTypeClass('Examination'), 'other');
  assert.equal(printTypeClass(null), 'other');
});

test('a word that merely contains "lab" is not a lab', () => {
  assert.equal(printTypeClass('Collaborative Studio'), 'other');
});

// Lecturers

test('a shouted surname-first name is turned round for reading', () => {
  assert.equal(formatPersonName('AUSTIN,Nigel'), 'Nigel Austin');
});

test('an apostrophe survives title casing', () => {
  assert.equal(formatPersonName("O'BRIEN,Mary"), "Mary O'Brien");
});

test('a name with no comma is left in its own order', () => {
  assert.equal(formatPersonName('Dr Hosein'), 'Dr Hosein');
});

test('several lecturers are joined', () => {
  assert.equal(
    formatStaff(['AUSTIN,Nigel', 'FARRELL,Aidan']),
    'Nigel Austin, Aidan Farrell'
  );
});

test('a long teaching team is summarised so the line cannot run away', () => {
  const many = ['A,One', 'B,Two', 'C,Three', 'D,Four', 'E,Five'];
  assert.equal(formatStaff(many), 'One A, Two B, Three C +2 more');
});

test('no lecturer is null rather than "Unknown"', () => {
  /**
   * 134 of the fixture's 224 sessions name nobody. A column of "Unknown" is
   * worse than a short line.
   */
  assert.equal(formatStaff([]), null);
  assert.equal(formatStaff(null), null);
  assert.equal(formatStaff(undefined), null);
});

test('an uploaded timetable gives staff as a bare string and still prints', () => {
  // `TimetableEntry.staff` is typed `str | None`, so uploads never produce
  // the array the warehouse does.
  assert.equal(formatStaff('SINGH,Anil'), 'Anil Singh');
});

// Colour assignment

test('each course gets its own colour', () => {
  const keys = ['CHEM 1073', 'COMP 1601', 'MATH 1115'];
  const indices = keys.map(k => courseColourIndex(k, keys));
  assert.deepEqual(indices, [0, 1, 2]);
});

test('a ninth course wraps round the palette rather than falling off it', () => {
  const keys = Array.from({ length: 9 }, (_, i) => `C${i}`);
  assert.equal(courseColourIndex('C8', keys), 0);
  assert.equal(PRINT_PALETTE.length, 8);
});

test('the same timetable prints the same colours twice running', () => {
  const events = [
    event({ courseKey: 'MATH 1115' }),
    event({ courseKey: 'COMP 1601' }),
  ];
  const first = buildPrintModel({ events });
  const second = buildPrintModel({ events });
  assert.deepEqual(first.courses, second.courses);
});

// Days

test('days come out in week order, not the order they were placed', () => {
  const days = groupByDay([
    event({ day: 'Wednesday' }),
    event({ day: 'Monday' }),
    event({ day: 'Friday' }),
  ]).map(d => d.day);
  assert.deepEqual(days, ['Monday', 'Wednesday', 'Friday']);
});

test('a day with nothing on it is left off the page', () => {
  const days = groupByDay([event({ day: 'Monday' })]).map(d => d.day);
  assert.deepEqual(days, ['Monday']);
});

test('classes within a day are ordered by start time', () => {
  const [monday] = groupByDay([
    event({ startTime: '14:00', endTime: '16:00' }),
    event({ startTime: '09:00', endTime: '11:00' }),
  ]);
  assert.deepEqual(
    monday.entries.map(e => e.startTime),
    ['09:00', '14:00']
  );
});

test('two classes at the identical time still have a fixed order', () => {
  // Otherwise a clashing pair could swap places between two printings of the
  // same timetable.
  const build = () =>
    groupByDay([
      event({ courseKey: 'MATH 1115' }),
      event({ courseKey: 'CHEM 1073' }),
    ])[0].entries.map(e => e.courseKey);
  assert.deepEqual(build(), ['CHEM 1073', 'MATH 1115']);
  assert.deepEqual(build(), build());
});

test('a day the calendar does not recognise is kept, not dropped', () => {
  /**
   * It should not happen. But a printout that silently loses a class is
   * worse than one with an odd heading on it.
   */
  const days = groupByDay([
    event({ day: 'Monday' }),
    event({ day: 'Funday' }),
  ]).map(d => d.day);
  assert.deepEqual(days, ['Monday', 'Funday']);
});

// The model

test('an empty timetable produces an empty page, not a crash', () => {
  const model = buildPrintModel({});
  assert.deepEqual(model.days, []);
  assert.deepEqual(model.courses, []);
  assert.equal(model.meta.courseCount, 0);
  assert.equal(model.meta.classCount, 0);
});

test('the header counts courses and classes, not placements', () => {
  const model = buildPrintModel({
    events: [
      event({ courseKey: 'COMP 1601', type: 'Lecture' }),
      event({ courseKey: 'COMP 1601', type: 'Lab', day: 'Tuesday' }),
      event({ courseKey: 'MATH 1115', day: 'Friday' }),
    ],
  });
  assert.equal(model.meta.courseCount, 2);
  assert.equal(model.meta.classCount, 3);
});

test('a missing room is dropped rather than filled in', () => {
  // 19 of the fixture's 224 sessions have no room.
  const [day] = buildPrintModel({ events: [event({ room: null })] }).days;
  assert.equal(day.entries[0].room, null);
});

test('a class with no published type is called a class', () => {
  // 136 entries in the corpus publish no type, and a blank there reads as a
  // rendering fault rather than missing data.
  const [day] = buildPrintModel({ events: [event({ type: null })] }).days;
  assert.equal(day.entries[0].type, 'Class');
  assert.equal(day.entries[0].typeClass, 'other');
});

test('the lab group label is carried through, because it decides where you go', () => {
  const [day] = buildPrintModel({
    events: [event({ type: 'Lab', streamLabel: 'T1' })],
  }).days;
  assert.equal(day.entries[0].streamLabel, 'T1');
});

test('a class that sits out part of the semester is flagged', () => {
  const model = buildPrintModel({
    events: [
      event({ weeks: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12] }),
      event({ day: 'Tuesday', weeks: [3, 4, 5, 6, 7, 8, 9, 10, 11, 12] }),
    ],
  });
  const [monday, tuesday] = model.days;
  assert.equal(monday.entries[0].weeksRestricted, false);
  assert.equal(tuesday.entries[0].weeksRestricted, true);
  assert.equal(tuesday.entries[0].weeks, 'Wks 3–12');
});

test('a stale course still prints, and says it is stale', () => {
  const model = buildPrintModel({
    events: [event({ courseKey: 'COMP 1601' })],
    courses: [
      {
        courseKey: 'COMP 1601',
        title: 'Introduction to Programming',
        stale: true,
        origin: 'warehouse',
      },
    ],
  });
  assert.equal(model.courses[0].stale, true);
});

test('an uploaded course keeps its origin so the page can say so', () => {
  const model = buildPrintModel({
    events: [event({ courseKey: 'Some Uploaded Title', courseTitle: null })],
    courses: [
      { courseKey: 'Some Uploaded Title', title: null, origin: 'upload' },
    ],
  });
  assert.equal(model.courses[0].origin, 'upload');
  // No title anywhere, so the key has to stand in rather than print "null".
  assert.equal(model.courses[0].courseTitle, 'Some Uploaded Title');
});

test('a course title missing from the course list falls back to the event', () => {
  const model = buildPrintModel({ events: [event()], courses: [] });
  assert.equal(model.courses[0].courseTitle, 'Introduction to Programming');
});

test('an unresolved clash is printed, not quietly dropped', () => {
  /**
   * A student who prints a timetable with an overlap in it has to be told,
   * or the paper is confidently wrong.
   */
  const a = event({ courseKey: 'COMP 1601', day: 'Thursday', startTime: '14:00', endTime: '16:00' });
  const b = event({ courseKey: 'CHEM 1073', day: 'Thursday', startTime: '15:00', endTime: '17:00' });
  const model = buildPrintModel({
    events: [a, b],
    conflicts: [
      {
        a, b,
        courseA: 'COMP 1601',
        courseB: 'CHEM 1073',
        sameCourse: false,
        day: 'Thursday',
        weeks: [3, 4, 5],
      },
    ],
  });
  assert.equal(model.clashes.length, 1);
  assert.deepEqual(model.clashes[0], {
    day: 'Thursday',
    courseA: 'COMP 1601',
    timeA: '14:00–16:00',
    courseB: 'CHEM 1073',
    timeB: '15:00–17:00',
    weeks: 'Wks 3–5',
    sameCourse: false,
  });
});

test('a class the builder could not place is listed rather than omitted', () => {
  const model = buildPrintModel({
    events: [event()],
    unplaced: [{ courseKey: 'MATH 1115', type: 'Tutorial' }],
  });
  assert.deepEqual(model.unplaced, [
    { courseKey: 'MATH 1115', type: 'Tutorial' },
  ]);
});

test('printedAt comes from the caller, so the model has no clock in it', () => {
  const model = buildPrintModel({ meta: { printedAt: '12 August 2026' } });
  assert.equal(model.meta.printedAt, '12 August 2026');
  assert.equal(buildPrintModel({}).meta.printedAt, null);
});

test('a time range uses an en dash, not a hyphen', () => {
  assert.equal(formatTimeRange('09:00', '11:00'), '09:00–11:00');
});

// Against real data

test('a real tutorial off the fixture prints every field it has', () => {
  const placed = fixtureEvent('COMP 1601', s => s.type === 'Lab');
  const model = buildPrintModel({ events: [placed] });
  const entry = model.days[0].entries[0];

  assert.equal(entry.typeClass, 'lab');
  assert.equal(entry.courseKey, 'COMP 1601');
  assert.ok(entry.time.includes('–'));
  assert.ok(entry.weeks && entry.weeks.startsWith('Wk'));
});

test('a whole fixture course builds a model with no nulls where data exists', () => {
  const events = course('MATH 1115').sessions.map(s =>
    event({
      courseKey: 'MATH 1115',
      courseTitle: course('MATH 1115').title,
      type: s.type,
      day: s.day,
      startTime: s.startTime,
      endTime: s.endTime,
      room: s.room || null,
      staff: s.staff,
      streamLabel: s.streamLabel,
      weeks: s.weeks,
    })
  );
  const model = buildPrintModel({ events });

  assert.equal(model.meta.classCount, events.length);
  assert.equal(model.meta.courseCount, 1);
  for (const day of model.days) {
    for (const entry of day.entries) {
      assert.ok(entry.time, 'every entry has a time range');
      assert.ok(entry.type, 'every entry has a type word');
      assert.ok(
        ['lecture', 'lab', 'tutorial', 'other'].includes(entry.typeClass),
        `unexpected typeClass ${entry.typeClass}`
      );
      assert.ok(
        entry.colourIndex >= 0 && entry.colourIndex < PRINT_PALETTE.length,
        'colour index is inside the palette'
      );
    }
  }
});

test('every session in the fixture survives the model without throwing', () => {
  const events = warehouse.courses.flatMap(c =>
    c.sessions.map(s =>
      event({
        courseKey: c.code,
        courseTitle: c.title,
        type: s.type,
        day: s.day,
        startTime: s.startTime,
        endTime: s.endTime,
        room: s.room || null,
        staff: s.staff,
        streamLabel: s.streamLabel,
        weeks: s.weeks,
      })
    )
  );
  const model = buildPrintModel({ events });
  const printed = model.days.reduce((n, d) => n + d.entries.length, 0);

  // Nothing may be lost between the timetable and the page.
  assert.equal(printed, events.length);
  assert.equal(model.meta.courseCount, warehouse.courses.length);
});
