'use strict';

/**
 * The calendar subscription link: a timetable a phone keeps up to date.
 *
 * Nothing about the student is stored on the server, so the link carries
 * their choices (SUBSCRIPTION-FEED-SPEC.md section 5), and the server resolves
 * them against each new publication with the rules in slot-identity.js.
 * timetable_extractor/subscription.py decodes what this file encodes.
 *
 * Because the link is the timetable, changing the timetable makes a new
 * link, and a calendar subscribed to the old one keeps showing the old
 * choices. The page says so: it remembers what the student subscribed to.
 */

//: The token format, matching TOKEN_VERSION in subscription.py.
const SUBSCRIPTION_TOKEN_VERSION = 1;

//: The server refuses longer tokens (MAX_TOKEN_LENGTH in subscription.py).
const SUBSCRIPTION_TOKEN_MAX = 2048;

//: Where the feed is served.
const SUBSCRIPTION_PATH = '/api/timetable/calendar.ics';

const _B64URL = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_';

/** UTF-8 bytes of a string, without TextEncoder, which the test vm lacks. */
function _utf8(text) {
  const bytes = [];
  for (const ch of text) {
    const cp = ch.codePointAt(0);
    if (cp < 0x80) bytes.push(cp);
    else if (cp < 0x800) bytes.push(0xc0 | (cp >> 6), 0x80 | (cp & 63));
    else if (cp < 0x10000) bytes.push(0xe0 | (cp >> 12), 0x80 | ((cp >> 6) & 63), 0x80 | (cp & 63));
    else bytes.push(0xf0 | (cp >> 18), 0x80 | ((cp >> 12) & 63), 0x80 | ((cp >> 6) & 63), 0x80 | (cp & 63));
  }
  return bytes;
}

/** Unpadded base64url, the form Python's decoder expects. */
function base64Url(text) {
  const bytes = _utf8(text);
  let out = '';
  for (let i = 0; i < bytes.length; i += 3) {
    const n = (bytes[i] << 16) | ((bytes[i + 1] || 0) << 8) | (bytes[i + 2] || 0);
    out += _B64URL[(n >> 18) & 63] + _B64URL[(n >> 12) & 63];
    if (i + 1 < bytes.length) out += _B64URL[(n >> 6) & 63];
    if (i + 2 < bytes.length) out += _B64URL[n & 63];
  }
  return out;
}

/**
 * The courses a link can carry, and the ones it leaves out.
 *
 * Only warehouse courses the current publication still has: the server has
 * nothing to resolve an uploaded PDF or a withdrawn course against.
 */
function subscribableCourses(state) {
  const included = [];
  const left = [];
  for (const course of state.activeCourses) {
    if (course.origin === 'warehouse' && !course.stale) included.push(course);
    else left.push(course.code || course.courseKey);
  }
  included.sort((a, b) => (a.courseKey < b.courseKey ? -1 : a.courseKey > b.courseKey ? 1 : 0));
  return { included, left };
}

/**
 * Everything the link says about the timetable except the publication:
 * each course, the slot hashes of its placed classes, and the types the
 * student removed. Two timetables with the same body put the same classes in
 * a subscribed calendar.
 */
function subscriptionBody(state) {
  const { included } = subscribableCourses(state);
  const placements = state.placements;
  const parts = [];
  for (const course of included) {
    const byId = new Map((course.sessions || []).map((s) => [s.sessionId, s]));
    const picks = new Set();
    for (const p of placements) {
      if (p.courseKey !== course.courseKey) continue;
      const session = byId.get(p.selectedSessionId);
      if (session) picks.add(slotHash(session));
    }
    const prefix = course.courseKey + '|';
    const dismissed = new Set(
      (state.dismissedGroups || [])
        .filter((id) => id.startsWith(prefix))
        .map((id) => id.slice(prefix.length).split('|')[0])
    );
    let part = `${course.code || course.courseKey}:${[...picks].sort().join(',')}`;
    if (dismissed.size) part += '!' + [...dismissed].sort().join(',');
    parts.push(part);
  }
  return parts.join(';');
}

/**
 * The link's token, or the reason there is none, as `{ token, reason }`.
 */
function subscriptionToken(state) {
  const body = subscriptionBody(state);
  if (!body) {
    return { token: null, reason: 'None of your courses come from UWI\'s published timetable, so there is nothing a calendar could keep up to date.' };
  }
  if (!Number.isInteger(state.publicationId) || state.publicationId < 1) {
    return { token: null, reason: 'Update your courses first, so the link knows which timetable your choices were made on.' };
  }
  const token = base64Url(`${SUBSCRIPTION_TOKEN_VERSION}|${state.publicationId}|${body}`);
  if (token.length > SUBSCRIPTION_TOKEN_MAX) {
    return { token: null, reason: 'This timetable has too many courses for one calendar link.' };
  }
  return { token, reason: '' };
}

/**
 * The feed's address, and the ones that hand it to each calendar app.
 *
 * Apple opens webcal:// itself. Outlook.com takes the address in its
 * add-from-web page. Google takes nothing in a link that it reliably
 * honours, so its page is opened and the address pasted.
 */
function subscriptionUrls(origin, token) {
  const https = `${origin}${SUBSCRIPTION_PATH}?t=${token}`;
  return {
    https,
    webcal: https.replace(/^https?:/, 'webcal:'),
    google: 'https://calendar.google.com/calendar/r/settings/addbyurl',
    outlook: 'https://outlook.live.com/calendar/0/addfromweb?url='
      + encodeURIComponent(https) + '&name=' + encodeURIComponent('UWI timetable'),
  };
}

/**
 * Whether the calendar the student subscribed to shows a different
 * timetable from the one in front of them.
 */
function subscriptionOutOfDate(state) {
  return Boolean(state.subscribedBody) && state.subscribedBody !== subscriptionBody(state);
}

/**
 * Keep a subscription current through "Update my courses".
 *
 * The feed follows a republish with the same rules the refresh does, so a
 * subscribed calendar still matches after it, and saying otherwise would
 * cry wolf on every republish. The exception is a class the refresh had to
 * place afresh: the feed shows a note there instead, so the link really is
 * out of date and the page should say so.
 */
function carrySubscription(state, bodyBefore, refreshResult) {
  if (!state.subscribedBody || state.subscribedBody !== bodyBefore) return;
  if (refreshResult && refreshResult.replaced > 0) return;
  state.subscribedBody = subscriptionBody(state);
}
