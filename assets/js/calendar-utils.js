'use strict';

const DAYS = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"];
const START_HOUR = 8;
const SLOTS_PER_HOUR = 2;
const TOTAL_HOURS = 14;
const TOTAL_SLOTS = TOTAL_HOURS * SLOTS_PER_HOUR;
const SLOT_HEIGHT = 30;
const STORAGE_KEY_V2 = 'celcat_timetable_v2';

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

function findConflicts(events) {
  const conflicts = [];
  for (let i = 0; i < events.length; i++) {
    for (let j = i + 1; j < events.length; j++) {
      const a = events[i], b = events[j];
      if (a.day === b.day && a.courseId !== b.courseId && timesOverlap(a.startTime, a.endTime, b.startTime, b.endTime)) {
        conflicts.push({ courseA: a.courseId, courseB: b.courseId, day: a.day, timeA: a.startTime + "-" + a.endTime, timeB: b.startTime + "-" + b.endTime });
      }
    }
  }
  return conflicts;
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.appendChild(document.createTextNode(str));
  return div.innerHTML;
}
