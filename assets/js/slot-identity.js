'use strict';

/**
 * Recognising the same class in a newer publication.
 *
 * Every republish stores every session as a new row, so a session id names a
 * class in one publication and nothing after it. The builder kept a student's
 * choices by session id, and "Update my courses" therefore dropped every one
 * of them and placed the timetable again from scratch: a pinned Tuesday 8am
 * lab came back as Monday 10am and the toast said two classes had moved when
 * none had. What a class is, its slot, is what survives.
 *
 * The calendar subscription feed resolves a student's choices on the server
 * with the same rules. timetable_extractor/subscription.py mirrors this file,
 * and tests/fixtures/slot_resolution.json holds both to the same answers.
 */

/** FNV-1a over a string's UTF-16 code units, as eight hex digits. */
function fnv1aHex(text, seed = 0x811c9dc5) {
  let hash = seed >>> 0;
  for (let i = 0; i < text.length; i += 1) {
    hash ^= text.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return hash.toString(16).padStart(8, '0');
}

function _slotWeeks(session) {
  return Array.isArray(session.weeks)
    ? [...new Set(session.weeks)].sort((a, b) => a - b).join(',')
    : '';
}

/**
 * Everything that makes one sitting of a course different from another:
 * type, day, times, room, stream label and weeks. Not the session id, which
 * is a row in one publication, and not the lecturer, who is not where or
 * when the class is.
 */
function slotKey(session) {
  return [
    session.type || '',
    session.day || '',
    session.startTime || '',
    session.endTime || '',
    session.room || '',
    session.streamLabel || '',
    _slotWeeks(session),
  ].join('|');
}

/** A slot key short enough to put eight of a course's in a link. */
function slotHash(session) {
  return fnv1aHex(slotKey(session));
}

function _slotSameTime(a, b) {
  return a.day === b.day
    && a.startTime === b.startTime
    && a.endTime === b.endTime
    && (a.streamLabel || '') === (b.streamLabel || '');
}

/**
 * The session in a newer publication that a choice made in an older one
 * now means, or null when that cannot be told without guessing.
 *
 * `oldOfType` and `newOfType` are one course's sessions of the chosen
 * session's type, then and now. In order:
 *
 * 1. The same slot is still published.
 * 2. The only class at the same day and time: its room or weeks changed,
 *    which is still the class the student picked.
 * 3. Exactly one class of the type went and exactly one arrived, and the one
 *    that went is theirs: it moved.
 * 4. The type has a single class now, so there is nothing to choose.
 *
 * Anything else is null, and the caller says so rather than picking.
 */
function resolveSlot(old, oldOfType, newOfType) {
  if (!old) return null;
  const key = slotKey(old);
  const exact = newOfType.find((s) => slotKey(s) === key);
  if (exact) return exact;

  const sameTime = newOfType.filter((s) => _slotSameTime(s, old));
  if (sameTime.length === 1) return sameTime[0];

  const newKeys = new Set(newOfType.map(slotKey));
  const oldKeys = new Set(oldOfType.map(slotKey));
  const gone = oldOfType.filter((s) => !newKeys.has(slotKey(s)));
  const arrived = newOfType.filter((s) => !oldKeys.has(slotKey(s)));
  if (gone.length === 1 && arrived.length === 1 && slotKey(gone[0]) === key) {
    return arrived[0];
  }

  if (newOfType.length === 1) return newOfType[0];
  return null;
}
