'use strict';

/**
 * The timetable as an .ics file (ICS-EXPORT-SPEC.md, amended by the UX plan
 * section 4.4). A real import into Google, Apple and Outlook is the only full
 * proof; what can be pinned without a calendar app is pinned here.
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
  'timetable-state.js',
  'ics-export.js'
);
const {
  icsEscape, icsFold, icsLocal, icsUtc, icsStamp, weeksFromText, icsRecurrence,
  icsUid, buildIcsCalendar, TimetableState,
} = api.take('icsEscape', 'icsFold', 'icsLocal', 'icsUtc', 'icsStamp', 'weeksFromText',
  'icsRecurrence', 'icsUid', 'buildIcsCalendar', 'TimetableState');

const WEEK_ONE = '2026-08-31';
const NOW = new Date(Date.UTC(2026, 9, 12, 22, 30, 5));

function lecture(fields) {
  return {
    courseKey: 'COMP 2601',
    courseTitle: 'Computer Architecture',
    type: 'Lecture',
    streamLabel: null,
    day: 'Wednesday',
    startTime: '14:00',
    endTime: '15:00',
    room: 'TLC LT E',
    staff: ['RAGBIR-SHRIPAT,Diana'],
    weeks: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
    ...fields,
  };
}

function build(placed, dated, meta) {
  return buildIcsCalendar(placed, dated || [], {
    weekOne: WEEK_ONE, publicationId: 11, now: NOW, ...meta,
  });
}

/** The content lines of one VEVENT block, unfolded. */
function eventLines(text, index = 0) {
  const unfolded = text.replace(/\r\n /g, '');
  const blocks = unfolded.split('BEGIN:VEVENT\r\n').slice(1);
  return blocks[index].split('END:VEVENT')[0].split('\r\n').filter(Boolean);
}

function field(lines, name) {
  const line = lines.find((l) => l.startsWith(name + ':') || l.startsWith(name + ';'));
  return line ? line.slice(line.indexOf(':') + 1) : null;
}

// Text

test('commas, semicolons, backslashes and newlines are escaped', () => {
  assert.equal(icsEscape('Intro, Part 1; see \\notes\nnext'),
    'Intro\\, Part 1\\; see \\\\notes\\nnext');
});

test('a line of exactly 75 octets is left whole, and 76 folds', () => {
  assert.equal(icsFold('x'.repeat(75)), 'x'.repeat(75));
  assert.equal(icsFold('x'.repeat(76)), 'x'.repeat(75) + '\r\n x');
});

test('folding never splits a multi-byte character', () => {
  // 74 ASCII octets then a two-octet "é": it cannot fit on the first line.
  const folded = icsFold('x'.repeat(74) + 'é' + 'y');
  assert.equal(folded, 'x'.repeat(74) + '\r\n éy');
});

test('continuation lines also stay within 75 octets', () => {
  const folded = icsFold('z'.repeat(300));
  for (const line of folded.split('\r\n')) assert.ok(line.length <= 75);
});

// Dates

test('a campus time is written local, and in UTC four hours on', () => {
  assert.equal(icsLocal('2026-08-31', '10:00'), '20260831T100000');
  assert.equal(icsUtc('2026-11-16', '10:00'), '20261116T140000Z');
});

test('an evening class crosses midnight in UTC', () => {
  assert.equal(icsUtc('2026-11-16', '21:00'), '20261117T010000Z');
});

test('a stamp is UTC with seconds', () => {
  assert.equal(icsStamp(NOW), '20261012T223005Z');
});

// Weeks

test('printed weeks are read the way the warehouse reads them', () => {
  assert.deepEqual(weeksFromText('W1-W12'), [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]);
  assert.deepEqual(weeksFromText('W1-W7, W9-W12'), [1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 12]);
  assert.deepEqual(weeksFromText('W2, W4, W6'), [2, 4, 6]);
  assert.deepEqual(weeksFromText('S2W7-S2W9'), [7, 8, 9]);
  assert.deepEqual(weeksFromText(null), []);
});

// Recurrence, the spec's five patterns

test('every week: one rule, no exceptions', () => {
  const r = icsRecurrence([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12], 'Monday', '10:00', WEEK_ONE);
  assert.equal(r.start, '2026-08-31');
  assert.equal(r.rule, 'FREQ=WEEKLY;UNTIL=20261116T140000Z');
  assert.deepEqual(r.exdates, []);
});

test('a later start begins on that week', () => {
  const r = icsRecurrence([3, 4, 5, 6, 7, 8, 9, 10, 11, 12], 'Monday', '10:00', WEEK_ONE);
  assert.equal(r.start, '2026-09-14');
});

test('a gap is an exception at the same time of day, such as graduation week', () => {
  const r = icsRecurrence([1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 12], 'Monday', '14:00', WEEK_ONE);
  assert.deepEqual(r.exdates, ['20261019T140000']);
});

test('a fortnightly lab skips every other week', () => {
  const r = icsRecurrence([2, 4, 6, 8, 10, 12], 'Friday', '13:00', WEEK_ONE);
  assert.equal(r.start, '2026-09-11');
  assert.deepEqual(r.exdates, ['20260918T130000', '20261002T130000', '20261016T130000',
    '20261030T130000', '20261113T130000']);
});

test('a single week is a plain event with no rule', () => {
  const r = icsRecurrence([10], 'Friday', '09:00', WEEK_ONE);
  assert.equal(r.start, '2026-11-06');
  assert.equal(r.rule, null);
});

// Identity

test('a UID stays the same across exports of the same class', () => {
  assert.equal(icsUid(lecture({})), icsUid(lecture({})));
});

test('a room or lecturer change keeps the UID, so the event updates', () => {
  assert.equal(icsUid(lecture({})), icsUid(lecture({ room: 'FST C1', staff: ['SOMEONE,Else'] })));
});

test('a different group or time is a different event', () => {
  assert.notEqual(icsUid(lecture({})), icsUid(lecture({ streamLabel: 'L2' })));
  assert.notEqual(icsUid(lecture({})), icsUid(lecture({ startTime: '15:00' })));
});

// The file

test('the file is a calendar of published events with the campus zone', () => {
  const { ok, text } = build([lecture({})]);
  assert.ok(ok);
  assert.ok(text.startsWith('BEGIN:VCALENDAR\r\nVERSION:2.0\r\n'));
  assert.ok(text.endsWith('END:VCALENDAR\r\n'));
  assert.match(text, /\r\nMETHOD:PUBLISH\r\n/);
  assert.match(text, /\r\nTZID:America\/Port_of_Spain\r\n/);
  assert.match(text, /\r\nX-WR-CALNAME:My UWI timetable\r\n/);
});

test('every line ends CRLF and no line is longer than 75 octets', () => {
  const { text } = build([lecture({ courseTitle: 'A very long course title, with commas; and more, ' + 'x'.repeat(80) })]);
  assert.ok(!/[^\r]\n/.test(text), 'a bare LF');
  for (const line of text.split('\r\n')) {
    assert.ok(Buffer.byteLength(line, 'utf8') <= 75, line);
  }
});

test('BEGIN and END pair up, one VEVENT per class', () => {
  const placed = [lecture({}), lecture({ type: 'Tutorial', day: 'Friday', startTime: '12:00', endTime: '13:00' })];
  const { text, events } = build(placed);
  assert.equal(events, 2);
  assert.equal(text.split('BEGIN:VEVENT').length - 1, 2);
  assert.equal(text.split('END:VEVENT').length - 1, 2);
  assert.equal(text.split('BEGIN:').length, text.split('END:').length);
});

test('an event says what, when, where and how often', () => {
  const lines = eventLines(build([lecture({ streamLabel: 'L1', type: 'Lab' })]).text);
  assert.equal(field(lines, 'SUMMARY'), 'COMP 2601 Lab (L1)');
  assert.equal(field(lines, 'LOCATION'), 'TLC LT E');
  assert.equal(field(lines, 'DTSTART'), '20260902T140000');
  assert.equal(field(lines, 'DTEND'), '20260902T150000');
  assert.equal(field(lines, 'RRULE'), 'FREQ=WEEKLY;UNTIL=20261118T180000Z');
  assert.equal(field(lines, 'SEQUENCE'), '11');
  assert.equal(field(lines, 'DTSTAMP'), '20261012T223005Z');
  assert.ok(lines.some((l) => l.startsWith('DTSTART;TZID=America/Port_of_Spain:')));
});

test('the description names the course, lecturer and source', () => {
  const lines = eventLines(build([lecture({})], [], {
    publishedLabel: '9 Oct 2026', pageUrl: 'https://example.test/calendar',
  }).text);
  assert.equal(field(lines, 'DESCRIPTION'),
    'Computer Architecture\\nRAGBIR-SHRIPAT\\,Diana\\nFrom UWI\'s timetable published 9 Oct 2026.\\nYour timetable: https://example.test/calendar');
});

test('no room means no LOCATION line, not an empty one', () => {
  const lines = eventLines(build([lecture({ room: null })]).text);
  assert.equal(field(lines, 'LOCATION'), null);
});

test('an exam split across rooms is one event that says to check the room', () => {
  const exam = { courseKey: 'COMP 2601', courseTitle: 'Computer Architecture', type: 'Examination',
    day: 'Thursday', startTime: '09:00', endTime: '11:00', weeks: [7] };
  const { text, events } = build([], [{ ...exam, room: 'JFK LT' }, { ...exam, room: 'ENG MD3' }]);
  assert.equal(events, 1);
  const lines = eventLines(text);
  assert.equal(field(lines, 'LOCATION'), 'ENG MD3 / JFK LT (check which is yours)');
  assert.equal(field(lines, 'DTSTART'), '20261015T090000');
  assert.equal(field(lines, 'RRULE'), null);
});

test('an uploaded class is dated from its printed weeks', () => {
  const upload = lecture({ weeks: null, weeksRaw: 'W1-W6, W8-W12' });
  const lines = eventLines(build([upload]).text);
  assert.deepEqual(lines.filter((l) => l.startsWith('EXDATE')),
    ['EXDATE;TZID=America/Port_of_Spain:20261014T140000']);
});

test('a class with no weeks at all is left out and named', () => {
  const result = build([lecture({ weeks: null, weeksRaw: null })]);
  assert.equal(result.events, 0);
  assert.deepEqual(result.skipped, ['COMP 2601 Lecture']);
  assert.equal(result.ok, false);
});

test('an unknown semester refuses rather than guessing dates', () => {
  const result = buildIcsCalendar([lecture({})], [], { weekOne: null, now: NOW });
  assert.equal(result.ok, false);
  assert.equal(result.text, '');
  assert.match(result.reason, /not known/);
});

test('two classes with the same identity still get distinct UIDs', () => {
  const { text } = build([lecture({ room: 'A' }), lecture({ room: 'B' })]);
  const uids = text.split('\r\n').filter((l) => l.startsWith('UID:'));
  assert.equal(new Set(uids).size, 2);
});

test('a real timetable from the fixture exports every placed class', () => {
  const state = new TimetableState(TimetableState.fromWarehouseResponse({
    publicationId: warehouse.publicationId,
    courses: ['COMP 1601', 'PSYC 1001', 'BIOL 1262'].map(course),
  }));
  state.placeMissing();
  const placed = state.getPlacedEvents();
  const result = build(placed, state.datedSessions);

  assert.ok(result.ok);
  assert.deepEqual(result.skipped, []);
  assert.ok(result.events >= placed.length, 'every placed class, plus the dated one-offs');
});

test('two exams at the same weekday and hour are told apart by their dates', () => {
  // COMP 2601 sits exams at Thursday 9am in weeks 7 and 12. Without the date
  // in the UID the second only got a suffix by position, which a republish
  // adding an earlier exam would shift, overwriting the wrong event.
  const exam = { courseKey: 'COMP 2601', type: 'Examination', day: 'Thursday',
    startTime: '09:00', endTime: '11:00', dated: true };
  assert.notEqual(icsUid({ ...exam, weeks: [7] }), icsUid({ ...exam, weeks: [12] }));
  assert.equal(icsUid({ ...exam, weeks: [12] }), icsUid({ ...exam, weeks: [12] }));

  const { text } = build([], [{ ...exam, room: 'ENG MD3', weeks: [7] }, { ...exam, room: 'TBA', weeks: [12] }]);
  assert.ok(!/-2@/.test(text), 'no positional suffix needed');
});
