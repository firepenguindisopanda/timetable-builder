'use strict';

/**
 * Exams, relocated lectures and make-ups, listed by date.
 *
 * These used to be auto-placed on the weekly grid like any other class, so a
 * week-8 exam was drawn in every week and clashed with its own course's
 * lecture. They are dated events, and a student needs to know when and where
 * each one is, not to choose between them. TimetableState hands over the
 * sessions (`datedSessions`); this turns them into the list a student reads.
 * No DOM is touched here, so `tests/js/coming-up.test.js` pins all of it.
 */

//: What each dated type is called in the list. Anything else keeps its name.
const COMING_UP_LABELS = {
  'Examination': 'Exam',
  'Lecture Relocated': 'Lecture moved',
  'Lecture Make-up': 'Make-up lecture',
  'Tutorial (make-up/relocated)': 'Make-up or moved tutorial',
};

const _UP_MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

function _upEscape(value) {
  return String(value === null || value === undefined ? '' : value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/** "Thu 15 Oct", read from the ISO date so no time zone can shift it. */
function comingUpDateLabel(isoDate, day) {
  const [, m, d] = isoDate.split('-').map(Number);
  return String(day).slice(0, 3) + ' ' + d + ' ' + _UP_MONTHS[m - 1];
}

/**
 * One entry per class per week it runs, upcoming first.
 *
 * `today` is YYYY-MM-DD. A sitting earlier than today is not listed; `past`
 * counts them, per room, so the page can say some have gone by. Sittings of the same course and type at the same date and time are
 * one entry with every room, because an exam split across rooms is one exam:
 * the student needs to know to check which room is theirs, not to pick one.
 */
function comingUpItems(datedSessions, today, anchorMonday) {
  const byKey = new Map();
  let past = 0;

  for (const session of datedSessions || []) {
    for (const week of session.weeks || []) {
      const date = dateOfTeachingDay(week, session.day, anchorMonday);
      if (!date) continue;
      if (today && date < today) {
        past += 1;
        continue;
      }
      const key = [session.courseKey, session.type, date,
        session.startTime, session.endTime].join('|');
      if (!byKey.has(key)) {
        byKey.set(key, {
          date,
          week,
          day: session.day,
          startTime: session.startTime,
          endTime: session.endTime,
          courseKey: session.courseKey,
          courseTitle: session.courseTitle,
          type: session.type,
          label: COMING_UP_LABELS[session.type] || session.type,
          rooms: [],
        });
      }
      const item = byKey.get(key);
      for (const room of String(session.room || '').split(';')) {
        const name = room.trim();
        if (name && !item.rooms.includes(name)) item.rooms.push(name);
      }
    }
  }

  const items = [...byKey.values()];
  for (const item of items) item.rooms.sort((a, b) => a.localeCompare(b));
  items.sort((a, b) =>
    a.date.localeCompare(b.date)
    || a.startTime.localeCompare(b.startTime)
    || String(a.courseKey).localeCompare(String(b.courseKey))
    || String(a.type).localeCompare(String(b.type))
  );
  return { items, past };
}

/** Where an entry is, said so that a split room reads as a split. */
function comingUpWhere(rooms) {
  if (!rooms.length) return 'Room not published';
  if (rooms.length === 1) return rooms[0];
  return rooms.join(' / ') + ' (check which is yours)';
}

/** The list's HTML. An empty string when there is nothing to list. */
function comingUpHtml(result) {
  const items = (result && result.items) || [];
  if (!items.length) return '';
  return items.map((item) => `<li class="up-item">
    <span class="up-date">${_upEscape(comingUpDateLabel(item.date, item.day))}<span class="up-week">Week ${item.week}</span></span>
    <span class="up-what"><strong>${_upEscape(item.courseKey)}</strong> ${_upEscape(item.label)}
      <span class="up-where">${_upEscape(displayTimeRange(item.startTime, item.endTime))} · ${_upEscape(comingUpWhere(item.rooms))}</span>
    </span>
  </li>`).join('');
}
