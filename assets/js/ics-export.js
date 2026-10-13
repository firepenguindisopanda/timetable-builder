'use strict';

/**
 * A student's timetable as an .ics file for Google, Apple and Outlook.
 *
 * ICS-EXPORT-SPEC.md, as amended by UX-IMPROVEMENT-PLAN.md section 4.4. Built
 * in the browser from the saved timetable, so it works offline and there is
 * no endpoint to secure. Everything here is a pure function of its inputs;
 * the page only collects them and saves the result.
 *
 * Built from the placed classes rather than the print model: the print model
 * formats weeks to text and drops the raw list, and both exports are built
 * from the same placements anyway, so they cannot disagree about what is on
 * the timetable.
 */

//: Trinidad and Tobago: UTC-4 all year, no daylight saving.
const ICS_TZID = 'America/Port_of_Spain';
const ICS_UTC_OFFSET_HOURS = 4;

//: A file a calendar app recognises as published information, not invites.
const ICS_PRODID = '-//UWI Timetable Builder//Timetable Export//EN';

//: The domain half of every UID. Never resolved, only kept unique to us.
const ICS_UID_DOMAIN = 'timetable.uwi-sta';

//: RFC 5545 folds content lines longer than this many octets.
const ICS_LINE_OCTETS = 75;

const ICS_VTIMEZONE = [
  'BEGIN:VTIMEZONE',
  `TZID:${ICS_TZID}`,
  'BEGIN:STANDARD',
  'DTSTART:19700101T000000',
  'TZOFFSETFROM:-0400',
  'TZOFFSETTO:-0400',
  'TZNAME:AST',
  'END:STANDARD',
  'END:VTIMEZONE',
];

// Text

/** Escape a TEXT value: backslash, semicolon, comma and newline (RFC 5545 3.3.11). */
function icsEscape(value) {
  return String(value === null || value === undefined ? '' : value)
    .replace(/\\/g, '\\\\')
    .replace(/;/g, '\\;')
    .replace(/,/g, '\\,')
    .replace(/\r\n|\r|\n/g, '\\n');
}

/** UTF-8 octets one code point takes. */
function _icsOctets(codePoint) {
  if (codePoint < 0x80) return 1;
  if (codePoint < 0x800) return 2;
  if (codePoint < 0x10000) return 3;
  return 4;
}

/**
 * Fold a content line at 75 octets, continuing with a single space.
 *
 * Counted in UTF-8 octets, not characters, and never inside a character: a
 * course title with an accent folded mid-character makes a file some
 * clients reject outright.
 */
function icsFold(line) {
  const parts = [];
  let current = '';
  let octets = 0;
  // The first line has 75 octets; each continuation spends one on its space.
  let limit = ICS_LINE_OCTETS;
  for (const ch of line) {
    const size = _icsOctets(ch.codePointAt(0));
    if (octets + size > limit) {
      parts.push(current);
      current = '';
      octets = 0;
      limit = ICS_LINE_OCTETS - 1;
    }
    current += ch;
    octets += size;
  }
  parts.push(current);
  return parts.join('\r\n ');
}

// Dates

function _icsPad(n, width = 2) {
  return String(n).padStart(width, '0');
}

/** "20260831T100000": a local wall-clock time, to pair with TZID. */
function icsLocal(dateIso, time) {
  const mins = timeToMins(time);
  return dateIso.replace(/-/g, '') + 'T'
    + _icsPad(Math.floor(mins / 60)) + _icsPad(mins % 60) + '00';
}

/**
 * "20261116T140000Z": a campus time in UTC.
 *
 * RFC 5545 requires UNTIL in UTC when DTSTART carries a TZID, and an UNTIL
 * left local is read differently by different clients. Trinidad never
 * shifts, so this is a fixed four hours, which can cross midnight.
 */
function icsUtc(dateIso, time) {
  const [y, m, d] = dateIso.split('-').map(Number);
  const mins = timeToMins(time);
  const at = new Date(Date.UTC(y, m - 1, d, Math.floor(mins / 60) + ICS_UTC_OFFSET_HOURS, mins % 60));
  return at.getUTCFullYear() + _icsPad(at.getUTCMonth() + 1) + _icsPad(at.getUTCDate()) + 'T'
    + _icsPad(at.getUTCHours()) + _icsPad(at.getUTCMinutes()) + '00Z';
}

/** A Date as an ICS UTC timestamp, for DTSTAMP. */
function icsStamp(date) {
  return date.getUTCFullYear() + _icsPad(date.getUTCMonth() + 1) + _icsPad(date.getUTCDate()) + 'T'
    + _icsPad(date.getUTCHours()) + _icsPad(date.getUTCMinutes()) + _icsPad(date.getUTCSeconds()) + 'Z';
}

// Weeks

/**
 * Teaching weeks from printed text: "W1-W7, W9-W12" is 1..7 and 9..12.
 *
 * Uploaded PDFs carry only the printed text, so without this they could not
 * be dated at all. Semester prefixes ("S2W7") are dropped as the warehouse's
 * expand_weeks drops them: the week number is what places a class.
 */
function weeksFromText(text) {
  const weeks = new Set();
  const token = /(?:S\d+)?W(\d+)(?:\s*-\s*(?:S\d+)?W?(\d+))?/gi;
  let match;
  while ((match = token.exec(String(text || ''))) !== null) {
    const from = Number(match[1]);
    const to = match[2] ? Number(match[2]) : from;
    for (let w = Math.min(from, to); w <= Math.max(from, to); w += 1) weeks.add(w);
  }
  return [...weeks].sort((a, b) => a - b);
}

/** The weeks a class runs: the published list, or failing that its printed text. */
function icsWeeksOf(event) {
  if (Array.isArray(event.weeks) && event.weeks.length) {
    return [...new Set(event.weeks)].sort((a, b) => a - b);
  }
  return weeksFromText(event.weeksRaw);
}

/**
 * One weekly rule from the first week to the last, with an exception for
 * each week in between the class skips (spec 5.2). A single week is a plain
 * event. One construction covers every pattern in the corpus: gaps such as
 * graduation week, fortnightly labs and irregular runs alike.
 */
function icsRecurrence(weeks, day, startTime, weekOne) {
  if (!weeks.length) return null;
  const first = weeks[0];
  const last = weeks[weeks.length - 1];
  const start = dateOfTeachingDay(first, day, weekOne);
  if (!start) return null;
  if (first === last) return { start, rule: null, exdates: [] };

  const runs = new Set(weeks);
  const exdates = [];
  for (let w = first + 1; w < last; w += 1) {
    if (!runs.has(w)) exdates.push(icsLocal(dateOfTeachingDay(w, day, weekOne), startTime));
  }
  const until = icsUtc(dateOfTeachingDay(last, day, weekOne), startTime);
  return { start, rule: `FREQ=WEEKLY;UNTIL=${until}`, exdates };
}

// Identity

/** FNV-1a over a string, as eight hex digits. */
function _icsFnv(text, seed) {
  let hash = seed >>> 0;
  for (let i = 0; i < text.length; i += 1) {
    hash ^= text.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return hash.toString(16).padStart(8, '0');
}

/**
 * A UID that stays the same for the same class across exports (spec 5.4).
 *
 * Course, type, group, day and start time: a room or lecturer change is the
 * same class somewhere else and should update the event already in the
 * calendar, while a different lab group or time is a different commitment.
 *
 * An exam or other dated one-off also keys on its weeks, because its date is
 * what it is: COMP 2601 sits two exams at Thursday 9am, in weeks 7 and 12.
 */
function icsUid(event) {
  const key = [event.courseKey, event.type || '', event.streamLabel || '',
    event.day, event.startTime, event.dated ? (event.weeks || []).join(',') : ''].join('|');
  return `${_icsFnv(key, 0x811c9dc5)}${_icsFnv(key, 0x01000193)}@${ICS_UID_DOMAIN}`;
}

// Events

/** "ENG MD3 / JFK LT (check which is yours)" for a split exam, else the room. */
function _icsWhere(rooms) {
  if (rooms.length > 1) return rooms.join(' / ') + ' (check which is yours)';
  return rooms[0] || '';
}

function _icsRooms(room) {
  return String(room || '').split(';').map((r) => r.trim()).filter(Boolean);
}

/**
 * The classes to export, each with its weeks, from what is on the grid and
 * what is listed by date. Exams split across rooms are one entry, as they are
 * in the "Coming up" list.
 */
function icsEntries(placedEvents, datedSessions) {
  const entries = [];
  for (const event of placedEvents || []) {
    entries.push({ ...event, rooms: _icsRooms(event.room), weeks: icsWeeksOf(event), dated: false });
  }
  const byKey = new Map();
  for (const session of datedSessions || []) {
    const weeks = icsWeeksOf(session);
    const key = [session.courseKey, session.type, session.day, session.startTime,
      session.endTime, weeks.join(',')].join('|');
    if (!byKey.has(key)) {
      byKey.set(key, { ...session, rooms: [], weeks, dated: true });
    }
    const entry = byKey.get(key);
    for (const room of _icsRooms(session.room)) {
      if (!entry.rooms.includes(room)) entry.rooms.push(room);
    }
  }
  for (const entry of byKey.values()) {
    entry.rooms.sort((a, b) => a.localeCompare(b));
    entries.push(entry);
  }
  return entries;
}

function _icsSummary(entry) {
  const label = entry.code || entry.courseKey;
  return [label, entry.type, entry.streamLabel ? `(${entry.streamLabel})` : '']
    .filter(Boolean).join(' ');
}

function _icsDescription(entry, meta) {
  const lines = [];
  if (entry.courseTitle && entry.courseTitle !== entry.courseKey) lines.push(entry.courseTitle);
  if (entry.staff && entry.staff.length) lines.push(entry.staff.join(', '));
  if (entry.rooms.length > 1) lines.push('Held in ' + entry.rooms.join(', ') + '. Check which room is yours.');
  if (meta.publishedLabel) lines.push(`From UWI's timetable published ${meta.publishedLabel}.`);
  if (meta.pageUrl) lines.push(`Your timetable: ${meta.pageUrl}`);
  return lines.join('\n');
}

/**
 * The whole file, or the reason there is none.
 *
 * `meta`: `weekOne` (Monday of teaching week 1, or null when the semester is
 * not known, which refuses the export rather than guessing dates),
 * `publicationId` (the SEQUENCE, so a later publication's copy is the newer
 * one), `now` (a Date, for DTSTAMP), `publishedLabel` and `pageUrl` for the
 * description.
 *
 * Returns `{ ok, text, events, skipped, reason }`. `skipped` names classes
 * that could not be dated, so the page can say what was left out.
 */
function buildIcsCalendar(placedEvents, datedSessions, meta) {
  if (!meta || !meta.weekOne) {
    return {
      ok: false,
      text: '',
      events: 0,
      skipped: [],
      reason: 'The dates of this semester\'s teaching weeks are not known yet, so the classes cannot be put on a calendar.',
    };
  }

  const stamp = icsStamp(meta.now || new Date());
  const sequence = Number.isInteger(meta.publicationId) && meta.publicationId > 0 ? meta.publicationId : 0;
  const lines = [
    'BEGIN:VCALENDAR',
    'VERSION:2.0',
    `PRODID:${ICS_PRODID}`,
    'CALSCALE:GREGORIAN',
    'METHOD:PUBLISH',
    'X-WR-CALNAME:My UWI timetable',
    `X-WR-TIMEZONE:${ICS_TZID}`,
    ...ICS_VTIMEZONE,
  ];

  const skipped = [];
  const used = new Set();
  let events = 0;
  for (const entry of icsEntries(placedEvents, datedSessions)) {
    const recurrence = icsRecurrence(entry.weeks, entry.day, entry.startTime, meta.weekOne);
    const startMins = timeToMins(entry.startTime);
    if (!recurrence || timeToMins(entry.endTime) <= startMins) {
      skipped.push(_icsSummary(entry));
      continue;
    }

    // Unique within the file. Two classes with the same identity at the same
    // time cannot both be attended, but if a timetable ever holds both, the
    // second must not silently replace the first on import.
    let uid = icsUid(entry);
    for (let n = 2; used.has(uid); n += 1) uid = icsUid(entry).replace('@', `-${n}@`);
    used.add(uid);

    lines.push('BEGIN:VEVENT');
    lines.push(`UID:${uid}`);
    lines.push(`DTSTAMP:${stamp}`);
    lines.push(`SEQUENCE:${sequence}`);
    lines.push(`SUMMARY:${icsEscape(_icsSummary(entry))}`);
    const description = _icsDescription(entry, meta);
    if (description) lines.push(`DESCRIPTION:${icsEscape(description)}`);
    const where = _icsWhere(entry.rooms);
    if (where) lines.push(`LOCATION:${icsEscape(where)}`);
    lines.push(`DTSTART;TZID=${ICS_TZID}:${icsLocal(recurrence.start, entry.startTime)}`);
    lines.push(`DTEND;TZID=${ICS_TZID}:${icsLocal(recurrence.start, entry.endTime)}`);
    if (recurrence.rule) lines.push(`RRULE:${recurrence.rule}`);
    for (const exdate of recurrence.exdates) lines.push(`EXDATE;TZID=${ICS_TZID}:${exdate}`);
    lines.push('TRANSP:OPAQUE');
    lines.push('END:VEVENT');
    events += 1;
  }

  lines.push('END:VCALENDAR');
  return {
    ok: events > 0,
    text: lines.map(icsFold).join('\r\n') + '\r\n',
    events,
    skipped,
    reason: events > 0 ? '' : 'There are no classes on your timetable to add.',
  };
}
