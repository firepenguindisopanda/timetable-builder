'use strict';

/**
 * Which notices sit above the grid, and in what order.
 *
 * Each notice used to switch itself on, so a student who undid "Update my
 * courses" saw the green "2 of your classes changed" banner and the gold
 * "What changed for you" panel at once, listing the same two changes.
 * Notices now say whether they *want* to show, and this decides
 * (REDESIGN-SPEC.md 5.3). No DOM is touched here, so
 * `tests/js/notices.test.js` pins the policy.
 */

//: Most urgent first. A timetable that will not be saved outranks
//: everything; then the offer to catch up with a republish; then what the
//: last update changed; then a calendar subscription gone out of date.
const NOTICE_ORDER = ['storage', 'republish', 'changes', 'subscription'];

//: More than two notices pushed the grid, the thing a student came for, off
//: a phone's first screen.
const MAX_NOTICES = 2;

/**
 * The notices to show, in order, from `wants` ({storage: true, ...}).
 *
 * `wants.republish` is 'offer' while an update is on offer, 'dismissed' once
 * the student said "Not now", and false otherwise. A pending republish and
 * the last update's changes are two states of one notice: updating replaces
 * the list, so while an update is pending the older list stays hidden, and
 * "Not now" does not bring it back in the offer's place.
 */
function noticesToShow(wants) {
  const pending = Boolean(wants && wants.republish);
  const wanted = NOTICE_ORDER.filter((name) => {
    if (!wants || !wants[name]) return false;
    if (name === 'republish') return wants.republish === 'offer';
    if (name === 'changes') return !pending;
    return true;
  });
  return wanted.slice(0, MAX_NOTICES);
}
