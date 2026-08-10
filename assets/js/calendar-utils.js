'use strict';

const DAYS = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"];
const START_HOUR = 8;
const SLOTS_PER_HOUR = 2;
const TOTAL_HOURS = 14;
const TOTAL_SLOTS = TOTAL_HOURS * SLOTS_PER_HOUR;
const SLOT_HEIGHT = 30;

const TYPE_ALIASES = Object.freeze({
  "lec": "Lecture", "lecture": "Lecture", "lectuer": "Lecture",
  "lab": "Lab", "laboratory": "Lab",
  "tut": "Tutorial", "tutorial": "Tutorial", "tute": "Tutorial",
  "sem": "Seminar", "seminar": "Seminar",
  "wrk": "Workshop", "workshop": "Workshop",
});

function normalizeType(raw) {
  const cleaned = String(raw).trim().toLowerCase();
  return TYPE_ALIASES[cleaned] || "Other";
}

function computeTypeKey(type, groupLabel) {
  return type + (groupLabel ? "-" + groupLabel : "");
}

function computeStreamId(type, day, startTime, endTime, groupLabel) {
  const safe = s => s.replace(/[^a-zA-Z0-9_-]/g, '');
  return safe(normalizeType(type)) + "-" + safe(day) + "-" + startTime.replace(":", "") + "-" + endTime.replace(":", "") + (groupLabel ? "-" + safe(groupLabel) : "");
}

function timeToMins(time) {
  if (!time) return START_HOUR * 60; // 480 = 8:00 AM
  const trimmed = time.trim();
  const is12h = /(am|pm)/i.test(trimmed);
  if (is12h) {
    const match = trimmed.match(/^(\d{1,2}):(\d{2})\s*(am|pm)/i);
    if (!match) return 0;
    let hours = parseInt(match[1], 10);
    const minutes = parseInt(match[2], 10);
    const meridiem = match[3].toLowerCase();
    if (meridiem === "pm" && hours !== 12) hours += 12;
    if (meridiem === "am" && hours === 12) hours = 0;
    return hours * 60 + minutes;
  }
  const parts = trimmed.split(":");
  if (parts.length !== 2) return 0;
  const hours = parseInt(parts[0], 10);
  const minutes = parseInt(parts[1], 10);
  if (isNaN(hours) || isNaN(minutes)) return 0;
  return hours * 60 + minutes;
}

function minsToTime(mins) {
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return String(h).padStart(2, "0") + ":" + String(m).padStart(2, "0");
}

function timeLabel(mins) {
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  const period = h >= 12 ? "PM" : "AM";
  const displayH = h === 0 ? 12 : h > 12 ? h - 12 : h;
  return displayH + ":" + String(m).padStart(2, "0") + " " + period;
}

function timesOverlap(aStart, aEnd, bStart, bEnd) {
  return timeToMins(aStart) < timeToMins(bEnd) && timeToMins(bStart) < timeToMins(aEnd);
}

function timeToSlot(time) {
  const mins = timeToMins(time);
  const startMins = START_HOUR * 60;
  const endMins = (START_HOUR + TOTAL_HOURS) * 60;
  if (mins < startMins || mins > endMins) return -1;
  return Math.floor((mins - startMins) / (60 / SLOTS_PER_HOUR));
}

/**
 * The teaching weeks two events share, or null when that cannot be known.
 *
 * Null means "assume they always coincide". An event with no week data came
 * from an uploaded PDF, which carries none, and those have to keep behaving
 * exactly as they did before the warehouse existed. It is deliberately not the
 * same answer as [], which means "these two never meet".
 */
function sharedWeeks(a, b) {
  const known = w => Array.isArray(w) && w.length > 0;
  const ascending = (x, y) => x - y;

  if (!known(a.weeks) && !known(b.weeks)) return null;
  if (!known(a.weeks)) return [...b.weeks].sort(ascending);
  if (!known(b.weeks)) return [...a.weeks].sort(ascending);

  const inB = new Set(b.weeks);
  return a.weeks.filter(w => inB.has(w)).sort(ascending);
}

/** Both modes name a course differently; upload has courseId, the warehouse courseKey. */
function courseOf(event) {
  return event.courseKey || event.courseId;
}

/**
 * Every pair of placed classes that genuinely collide.
 *
 * Two things this does not do that a naive overlap check would.
 *
 * It does not call two events a clash merely because they share a day and an
 * hour: they also have to run in the same teaching week. BIOL 1262 lectures on
 * Thursday at 16:00 in weeks 2 to 12, and its relocated Thursday 16:00 lecture
 * runs in week 10 only. On a grid they sit on top of each other and a student
 * never has to choose between them.
 *
 * And it no longer skips two classes of the same course. Under option grouping
 * a course places several sessions, so its own lecture and lab can collide.
 * That is real and hiding it helps nobody.
 */
/** Whether two placed classes cannot both be attended. */
function eventsCollide(a, b) {
  if (a.day !== b.day) return false;
  if (!timesOverlap(a.startTime, a.endTime, b.startTime, b.endTime)) return false;
  const weeks = sharedWeeks(a, b);
  return weeks === null || weeks.length > 0;
}

function findConflicts(events) {
  const conflicts = [];
  for (let i = 0; i < events.length; i++) {
    for (let j = i + 1; j < events.length; j++) {
      const a = events[i], b = events[j];
      if (!eventsCollide(a, b)) continue;

      const weeks = sharedWeeks(a, b);
      conflicts.push({
        a, b,
        courseA: courseOf(a), courseB: courseOf(b),
        sameCourse: courseOf(a) === courseOf(b),
        day: a.day,
        timeA: a.startTime + "-" + a.endTime,
        timeB: b.startTime + "-" + b.endTime,
        // Null where neither side publishes weeks, so a caller can say "every
        // week" rather than printing an empty list.
        weeks,
      });
    }
  }
  return conflicts;
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.appendChild(document.createTextNode(str));
  return div.innerHTML;
}
