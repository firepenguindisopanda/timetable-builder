'use strict';

/**
 * What a student's week adds up to.
 *
 * "How heavy is my week" was a sum done by hand over the grid: contact hours,
 * which days run long, where the dead time is, and which back-to-back classes
 * mean crossing campus. Everything here works on the classes the student
 * attends in one week (placements and that week's exams), never on every
 * session a course offers, which would count every parallel lab.
 */

//: A gap this long between two classes is time to use, not a walk.
const MY_WEEK_GAP_MINS = 120;

//: A day this long from first class to last counts as a long day.
const MY_WEEK_LONG_DAY_MINS = 8 * 60;

//: Classes this close count as back to back.
const MY_WEEK_TIGHT_MINS = 10;

//: The weekdays a free day is worth mentioning on. A free Sunday is not news.
const MY_WEEK_WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday'];

/**
 * Buildings, from the first word of a room code. Curated, because there are
 * no coordinates in the data and the prefixes are only mostly regular: in
 * publication 11 FHE, FST, ENG, TLC, FSS, FFA, TCB, LRC, JFK, LAW, IGDS and
 * Daaga cover nearly every room. "Remote Teaching", "Venue to be advised" and
 * anything unrecognised have no building, so they never raise a warning.
 */
const MY_WEEK_BUILDINGS = {
  FHE: 'Humanities & Education',
  FST: 'Science & Technology',
  ENG: 'Engineering',
  TLC: 'Teaching & Learning Complex',
  FSS: 'Social Sciences',
  FFA: 'Food & Agriculture',
  TCB: 'TCB',
  LRC: 'Learning Resource Centre',
  JFK: 'JFK Quad',
  LAW: 'Law',
  IGDS: 'IGDS',
  DAAGA: 'Daaga Auditorium',
};

/** The building a room is in, or null when the code does not say. */
function buildingOf(room) {
  const first = String(room || '').split(';')[0].trim().split(/\s+/)[0].toUpperCase();
  return MY_WEEK_BUILDINGS[first] ? first : null;
}

/** Merge overlapping [start, end) minute ranges, so a clash is not counted twice. */
function _mergedMinutes(ranges) {
  const sorted = [...ranges].sort((a, b) => a[0] - b[0]);
  let total = 0;
  let current = null;
  for (const [from, to] of sorted) {
    if (!current || from > current[1]) {
      if (current) total += current[1] - current[0];
      current = [from, to];
    } else {
      current[1] = Math.max(current[1], to);
    }
  }
  if (current) total += current[1] - current[0];
  return total;
}

/**
 * The week, summed up.
 *
 * `events` carry day, startTime, endTime, room and a label (course code).
 * Returns contact minutes, each day's span and gaps, the earliest start and
 * latest finish, the weekdays with nothing on, and back-to-back classes in
 * different buildings.
 */
function weekSummary(events) {
  const byDay = new Map();
  for (const event of events || []) {
    const from = timeToMins(event.startTime);
    const to = timeToMins(event.endTime);
    if (!(to > from) || !DAYS.includes(event.day)) continue;
    if (!byDay.has(event.day)) byDay.set(event.day, []);
    byDay.get(event.day).push({ ...event, from, to });
  }

  const days = [];
  let contactMins = 0;
  let earliest = null;
  let latest = null;
  const backToBack = [];

  for (const day of DAYS) {
    const classes = (byDay.get(day) || []).sort((a, b) => a.from - b.from || a.to - b.to);
    if (!classes.length) continue;
    const minutes = _mergedMinutes(classes.map((c) => [c.from, c.to]));
    contactMins += minutes;

    const first = classes[0].from;
    const last = Math.max(...classes.map((c) => c.to));
    const gaps = [];
    let reach = classes[0].to;
    for (let i = 1; i < classes.length; i += 1) {
      const next = classes[i];
      if (next.from - reach >= MY_WEEK_GAP_MINS) gaps.push({ from: reach, to: next.from });
      // Back to back: the next class starts within minutes of this one
      // ending, in a different building.
      const prev = classes[i - 1];
      const tight = next.from >= prev.to && next.from - prev.to <= MY_WEEK_TIGHT_MINS;
      const a = buildingOf(prev.room);
      const b = buildingOf(next.room);
      if (tight && a && b && a !== b) {
        backToBack.push({ day, at: next.from, fromLabel: prev.label, toLabel: next.label, fromBuilding: a, toBuilding: b });
      }
      reach = Math.max(reach, next.to);
    }

    days.push({ day, first, last, spanMins: last - first, contactMins: minutes, count: classes.length, gaps });
    if (!earliest || first < earliest.mins) earliest = { day, mins: first };
    if (!latest || last > latest.mins) latest = { day, mins: last };
  }

  const busy = new Set(days.map((d) => d.day));
  return {
    contactMins,
    days,
    longDays: days.filter((d) => d.spanMins >= MY_WEEK_LONG_DAY_MINS),
    earliest,
    latest,
    freeWeekdays: MY_WEEK_WEEKDAYS.filter((d) => !busy.has(d)),
    backToBack,
  };
}

function _hours(mins) {
  const h = mins / 60;
  return Number.isInteger(h) ? String(h) : h.toFixed(1).replace(/\.0$/, '');
}

function _clockOf(mins) {
  return displayTime(minsToTime(mins));
}

/**
 * The one-line answer: "14 contact hours · 2 long days · earliest 8am Tue ·
 * free Fri". Empty when there is nothing on.
 */
function weekSummaryLine(summary) {
  if (!summary || !summary.days.length) return '';
  const parts = [`${_hours(summary.contactMins)} contact ${summary.contactMins === 60 ? 'hour' : 'hours'}`];
  if (summary.longDays.length) {
    parts.push(`${summary.longDays.length} long ${summary.longDays.length === 1 ? 'day' : 'days'}`);
  }
  if (summary.earliest) parts.push(`earliest ${_clockOf(summary.earliest.mins)} ${summary.earliest.day.slice(0, 3)}`);
  if (summary.freeWeekdays.length) parts.push('free ' + summary.freeWeekdays.map((d) => d.slice(0, 3)).join(', '));
  return parts.join(' · ');
}

/**
 * The detail behind the line, one sentence each, in day order: how long each
 * day runs, its gaps, and any dash across campus.
 */
function weekSummaryDetails(summary) {
  if (!summary) return [];
  const lines = [];
  for (const day of summary.days) {
    let line = `${day.day}: ${displayTimeRange(minsToTime(day.first), minsToTime(day.last))}, `
      + `${_hours(day.contactMins)}h of class`;
    if (day.spanMins >= MY_WEEK_LONG_DAY_MINS) line += ' (a long day)';
    for (const gap of day.gaps) {
      line += `; free ${displayTimeRange(minsToTime(gap.from), minsToTime(gap.to))}`;
    }
    lines.push(line + '.');
  }
  for (const dash of summary.backToBack) {
    lines.push(`${dash.day} ${_clockOf(dash.at)}: ${dash.fromLabel} in ${MY_WEEK_BUILDINGS[dash.fromBuilding]} `
      + `runs straight into ${dash.toLabel} in ${MY_WEEK_BUILDINGS[dash.toBuilding]}.`);
  }
  if (summary.latest) {
    lines.push(`Latest finish: ${_clockOf(summary.latest.mins)} on ${summary.latest.day}.`);
  }
  return lines;
}

/**
 * What choosing another time would do: which classes it would clash with,
 * week by week as the clash panel counts them, and how long its day would
 * then run. `others` are the student's other classes, without the one being
 * moved. There is no "popular" or "full": the data has no enrolment.
 */
function optionEffect(option, others) {
  const clashes = [];
  for (const other of others || []) {
    if (eventsCollide(option, other) && !clashes.includes(other.label)) clashes.push(other.label);
  }
  const sameDay = (others || []).filter((o) => o.day === option.day).concat([option]);
  const first = Math.min(...sameDay.map((e) => timeToMins(e.startTime)));
  const last = Math.max(...sameDay.map((e) => timeToMins(e.endTime)));
  return { clashes, day: option.day, first, last, alone: sameDay.length === 1 };
}

/** "No clash · Tuesday would run 9am–7pm", or what it clashes with. */
function optionEffectText(effect) {
  const clash = effect.clashes.length
    ? 'Clashes with ' + effect.clashes.join(', ')
    : 'No clash';
  const day = effect.alone
    ? `the only class on ${effect.day}`
    : `${effect.day} would run ${displayTimeRange(minsToTime(effect.first), minsToTime(effect.last))}`;
  return `${clash} \u00b7 ${day}`;
}
