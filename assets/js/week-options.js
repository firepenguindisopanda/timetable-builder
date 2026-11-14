'use strict';

/**
 * What the Re-arrange dialog says. WEEK-OPTIMISER-SPEC 5.3 and 14.
 *
 * Pure functions from TimetableState.rearrangeOptions()'s result to text, so
 * the wording is tested in node and the inline script in calendar.html only
 * draws it. The student's remembered choices are read and written here too,
 * against a storage object the page passes in, for the same reason. Needs calendar-utils.js (displayTimeRange), placement.js
 * (eventForPlacement) and week-optimiser.js (sameArrangement) loaded first.
 *
 * Private helpers carry a `_weekOptions` prefix because every script shares
 * one global scope, and a short name like `_hours` is already taken.
 */

/**
 * Card titles by how many options there are. The front runs from the
 * shortest longest run to the fewest days, so the ends are named for those.
 */
const WEEK_OPTIONS_TITLES = {
  1: ['Best week'],
  2: ['Shortest stretches', 'Fewest days'],
  3: ['Shortest stretches', 'In between', 'Fewest days'],
};

function _weekOptionsCount(n, one, many) {
  return `${n} ${n === 1 ? one : many}`;
}

/** "3 hours", "1 hour 30 minutes", "30 minutes". */
function _weekOptionsDuration(mins) {
  const hours = Math.floor(mins / 60);
  const rest = mins % 60;
  const parts = [];
  if (hours > 0) parts.push(_weekOptionsCount(hours, 'hour', 'hours'));
  if (rest > 0 || hours === 0) parts.push(_weekOptionsCount(rest, 'minute', 'minutes'));
  return parts.join(' ');
}

// The student's preferences. WEEK-OPTIMISER-SPEC 14.1 and 14.3.

/** Where this browser remembers the choices; the saved timetable never holds them. */
const WEEK_PREFS_KEY = 'celcat_week_prefs_v1';

/** Every day a student could keep free, in week order. */
const WEEK_OPTIONS_ALL_DAYS = [
  'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday',
];

/**
 * Preferences as the rest of this file reads them: real day names only, once
 * each and in week order, and a break of 60 or 120 minutes. Anything else
 * falls back to the defaults, no free days and 1 hour, field by field.
 */
function _weekOptionsPrefs(prefs) {
  const given = prefs && typeof prefs === 'object' && !Array.isArray(prefs) ? prefs : {};
  const wanted = Array.isArray(given.freeDays) ? given.freeDays : [];
  return {
    freeDays: WEEK_OPTIONS_ALL_DAYS.filter((day) => wanted.includes(day)),
    breakMins: given.breakMins === 120 ? 120 : 60,
  };
}

/**
 * The choices this browser remembered, or the defaults.
 *
 * `storage` is the page's localStorage (browserStorage() in
 * timetable-state.js), passed in so node can test this. Reading throws in
 * some privacy modes, and an old or hand-edited value may be anything, so
 * every way of failing reads as the defaults rather than stopping Re-arrange.
 */
function loadWeekPrefs(storage) {
  let raw = null;
  try {
    raw = storage ? storage.getItem(WEEK_PREFS_KEY) : null;
  } catch (e) {
    raw = null;
  }
  if (typeof raw !== 'string') return _weekOptionsPrefs(null);
  try {
    return _weekOptionsPrefs(JSON.parse(raw));
  } catch (e) {
    return _weekOptionsPrefs(null);
  }
}

/** Remember the choices. False where the browser refuses, which costs only the memory. */
function saveWeekPrefs(storage, prefs) {
  if (!storage) return false;
  try {
    storage.setItem(WEEK_PREFS_KEY, JSON.stringify(_weekOptionsPrefs(prefs)));
    return true;
  } catch (e) {
    return false;
  }
}

/**
 * The days the dialog offers to keep free: Monday to Saturday, and Sunday
 * only when one of these option groups has a sitting on a Sunday, because a
 * Sunday toggle that can never matter is one more thing to read past.
 */
function weekOptionsDays(groups) {
  const sunday = (groups || []).some((group) =>
    (group && Array.isArray(group.sessions) ? group.sessions : [])
      .some((s) => s && s.day === 'Sunday'));
  return sunday ? WEEK_OPTIONS_ALL_DAYS.slice() : WEEK_OPTIONS_ALL_DAYS.slice(0, 6);
}

/**
 * "up to 3 hours in a row, class on 4 days", or with a 2-hour break "up to 4
 * hours without a 2-hour break, class on 3 days": "in a row" would claim no
 * gap at all, when the run now bridges gaps of up to two hours.
 */
function _weekOptionsFigures(week, breakMins = 60) {
  const run = breakMins === 60
    ? 'in a row'
    : `without a ${breakMins / 60}-hour break`;
  return `up to ${_weekOptionsDuration(week.runMins)} ${run}, `
    + `class on ${_weekOptionsCount(week.days, 'day', 'days')}`;
}

function _weekOptionsClash(clashes) {
  if (!clashes) return null;
  return `${_weekOptionsCount(clashes, 'clash', 'clashes')} that cannot be avoided`;
}

/**
 * "Now: up to 5 hours in a row, class on 4 days."
 *
 * A week with clashes says so first. Without that, a clashing week can show
 * shorter runs and fewer days than every option offered, and the options
 * look like a step backwards when they are the fix.
 */
function _weekOptionsNow(current, breakMins) {
  const clashes = current.clashes
    ? `${_weekOptionsCount(current.clashes, 'clash', 'clashes')}, `
    : '';
  return `Now: ${clashes}${_weekOptionsFigures(current, breakMins)}.`;
}

/** "Wed 9-11am", with the range exactly as the rest of the page prints it. */
function _weekOptionsWhen(event) {
  return `${String(event.day).slice(0, 3)} ${displayTimeRange(event.startTime, event.endTime)}`;
}

/** Plain string order, so the list reads the same in every browser. */
function _weekOptionsCompare(a, b) {
  if (a < b) return -1;
  if (a > b) return 1;
  return 0;
}

/**
 * One line per unpinned class the option puts somewhere the grid does not.
 *
 * Matched group by group: a placement the grid already holds, at the same
 * session, has not moved. What is left in the option is paired in order with
 * what is left of that group's unpinned placements on the grid, and a class
 * with nothing to pair with is one the grid does not hold, so it is added.
 * A class left on the grid with nothing to pair with is one the option drops.
 * Pinned placements never move, so they are not looked at.
 */
function _weekOptionsMoves(option, current, index) {
  const leftOnGrid = new Map();
  for (const p of current.placements) {
    if (p.pinned) continue;
    if (!leftOnGrid.has(p.groupId)) leftOnGrid.set(p.groupId, []);
    leftOnGrid.get(p.groupId).push(p);
  }
  const arriving = [];
  for (const p of option.placements) {
    if (p.pinned) continue;
    const grid = leftOnGrid.get(p.groupId) || [];
    const same = grid.findIndex((q) => q.selectedSessionId === p.selectedSessionId);
    if (same >= 0) grid.splice(same, 1);
    else arriving.push(p);
  }

  const moves = [];
  for (const p of arriving) {
    const to = eventForPlacement(p, index);
    if (!to) continue;
    const grid = leftOnGrid.get(p.groupId) || [];
    const from = grid.length > 0 ? eventForPlacement(grid.shift(), index) : null;
    const name = `${to.courseKey} ${to.type}`;
    const text = from
      ? `${name}: ${_weekOptionsWhen(from)} to ${_weekOptionsWhen(to)}`
      : `${name}: added ${_weekOptionsWhen(to)}`;
    moves.push({ courseKey: String(to.courseKey), type: String(to.type), text });
  }
  // What is still left on the grid is a class the option does not keep. It
  // happens when an extra sitting was unlocked: the group then holds two
  // loose classes and re-arranging places one. Said, not done silently.
  for (const left of leftOnGrid.values()) {
    for (const p of left) {
      const from = eventForPlacement(p, index);
      if (!from) continue;
      moves.push({
        courseKey: String(from.courseKey),
        type: String(from.type),
        text: `${from.courseKey} ${from.type}: removed ${_weekOptionsWhen(from)}`,
      });
    }
  }
  moves.sort((a, b) =>
    _weekOptionsCompare(a.courseKey, b.courseKey)
    || _weekOptionsCompare(a.type, b.type)
    || _weekOptionsCompare(a.text, b.text));
  return moves.map((m) => m.text);
}

/** Lines sorted by course code, then class type, then the words themselves. */
function _weekOptionsSorted(lines) {
  return lines
    .sort((a, b) =>
      _weekOptionsCompare(a.courseKey, b.courseKey)
      || _weekOptionsCompare(a.type, b.type)
      || _weekOptionsCompare(a.text, b.text))
    .map((line) => line.text);
}

/** "Monday", "Monday or Friday", "Monday, Friday or Saturday". */
function _weekOptionsDaysInWords(days) {
  if (days.length <= 1) return days.join('');
  return `${days.slice(0, -1).join(', ')} or ${days[days.length - 1]}`;
}

/**
 * "On a day you wanted free: COMP 1601 Lecture, Mon 12-1pm", one per loose
 * class the week puts on a free day. Pinned classes are left to the notes,
 * as the search does not count them either: they cannot move.
 *
 * A class that also runs on a day the student did not keep free says why it
 * stayed: "Its other times clash with your classes." Without that, MATH 1115
 * Lab left on a Saturday next to a free Wednesday sitting reads as a mistake.
 * The reason holds only for a finished search. Clashes are ranked before free
 * days, so if moving that one class off the free day kept the clashes level,
 * the search would have found a week with fewer classes on free days.
 */
function _weekOptionsFreeDayClasses(week, index, freeDays, proven) {
  const lines = [];
  for (const p of week.placements) {
    if (p.pinned) continue;
    const event = eventForPlacement(p, index);
    if (!event || !freeDays.has(event.day)) continue;
    const group = index.get(p.groupId);
    const elsewhere = Boolean(group) && group.sessions.some((s) => !freeDays.has(s.day));
    const why = proven && elsewhere ? '. Its other times clash with your classes.' : '';
    lines.push({
      courseKey: String(event.courseKey),
      type: String(event.type),
      text: `On a day you wanted free: ${event.courseKey} ${event.type}, ${_weekOptionsWhen(event)}${why}`,
    });
  }
  return _weekOptionsSorted(lines);
}

/**
 * Why no week can keep the free days clear, said once above the cards rather
 * than on each one.
 *
 * A loose class whose every sitting it could be given falls on a free day:
 * "COMP 1601 Lecture only runs on Monday." The sittings are the group's, less
 * any a pinned extra sitting of the same group already holds, because
 * re-arranging cannot choose those (TimetableState._rearrangeInstance). The
 * loose groups are read off the grid and the first option together, so a
 * group the grid lacks still counts. A pinned class on a free day: "You
 * locked COMP 1602 Lab on Saturday."
 */
function _weekOptionsNotes(result, index, freeDays) {
  if (freeDays.size === 0) return [];
  const current = result.current;
  const first = (result.options || [])[0];
  const pinned = current.placements.filter((p) => p.pinned);
  const looseIds = new Set();
  for (const p of [...current.placements, ...(first ? first.placements : [])]) {
    if (!p.pinned) looseIds.add(p.groupId);
  }

  const runsOnly = [];
  for (const groupId of looseIds) {
    const group = index.get(groupId);
    if (!group) continue;
    const held = new Set(pinned.filter((p) => p.groupId === groupId).map((p) => p.selectedSessionId));
    const sittings = group.sessions.filter((s) => !held.has(s.sessionId));
    if (sittings.length === 0 || !sittings.every((s) => freeDays.has(s.day))) continue;
    const days = WEEK_OPTIONS_ALL_DAYS.filter((day) => sittings.some((s) => s.day === day));
    runsOnly.push({
      courseKey: String(group.courseKey),
      type: String(group.type),
      text: `${group.courseKey} ${group.type} only runs on ${_weekOptionsDaysInWords(days)}.`,
    });
  }

  const locked = [];
  const said = new Set();
  for (const p of pinned) {
    const event = eventForPlacement(p, index);
    if (!event || !freeDays.has(event.day)) continue;
    const text = `You locked ${event.courseKey} ${event.type} on ${event.day}.`;
    if (said.has(text)) continue;
    said.add(text);
    locked.push({ courseKey: String(event.courseKey), type: String(event.type), text });
  }
  return [..._weekOptionsSorted(runsOnly), ..._weekOptionsSorted(locked)];
}

/**
 * Everything the Re-arrange dialog shows. WEEK-OPTIMISER-SPEC 5.3 and 14.4.
 *
 * `result` is rearrangeOptions(prefs)'s { current, options, proven }, `index`
 * the state's groupIndex and `prefs` the { freeDays, breakMins } it was asked
 * with, the defaults when omitted. Returns { prefs, nothingToGain, message,
 * now, notes, cards, unproven }. `message` is set only when no option differs
 * from the grid, and the dialog shows it in place of the cards; the dialog
 * always opens now, because the choices live in it. Each card keeps its
 * option so the page can hand it straight to applyArrangement.
 */
function weekOptionsView(result, index, prefs) {
  const wanted = _weekOptionsPrefs(prefs);
  const freeDays = new Set(wanted.freeDays);
  const current = result.current;
  const options = result.options || [];
  const titles = WEEK_OPTIONS_TITLES[options.length] || [];

  const cards = options.map((option, i) => {
    const isCurrent = sameArrangement(option.placements, current.placements);
    const figures = _weekOptionsFigures(option, wanted.breakMins);
    return {
      title: titles[i] || '',
      figures,
      clash: _weekOptionsClash(option.clashes),
      freeDayClasses: _weekOptionsFreeDayClasses(option, index, freeDays, Boolean(result.proven)),
      moves: isCurrent ? [] : _weekOptionsMoves(option, current, index),
      isCurrent,
      // What the toast says once this week is on the grid.
      applied: `${figures.replace(/^u/, 'U')}.`,
      option,
    };
  });

  const nothingToGain = cards.every((card) => card.isCurrent);
  return {
    prefs: wanted,
    nothingToGain,
    // Only a finished search can call the week the best one.
    message: !nothingToGain
      ? null
      : result.proven
        ? 'This is already the best week for these choices.'
        : 'No better week was found for these choices.',
    now: _weekOptionsNow(current, wanted.breakMins),
    notes: _weekOptionsNotes(result, index, freeDays),
    cards,
    unproven: result.proven
      ? null
      : 'These are the best weeks found. There may be a better one.',
  };
}

function _weekOptionsEscape(value) {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function _weekOptionsCardHtml(card, at) {
  const title = _weekOptionsEscape(card.title);
  const clash = card.clash
    ? `<p class="week-option-clash">${_weekOptionsEscape(card.clash)}</p>`
    : '';
  const freeDays = _weekOptionsFreeDayList(card.freeDayClasses || []);
  const moves = card.moves.length > 0
    ? `<p class="week-option-moves-head">Moves ${_weekOptionsCount(card.moves.length, 'class', 'classes')}:</p>
       <ul class="week-option-moves">
         ${card.moves.map((move) => `<li>${_weekOptionsEscape(move)}</li>`).join('')}
       </ul>`
    : '';
  // Three buttons that all read "Use this week" are one button to a screen
  // reader, so each carries its card's title.
  const action = card.isCurrent
    ? '<p class="week-option-now">This is the week you have now.</p>'
    : `<button type="button" class="btn btn-sm btn-accent week-option-use"
               data-option="${at}" aria-label="Use this week: ${title}">Use this week</button>`;
  return `<section class="week-option${card.isCurrent ? ' is-current' : ''}">
      <h3 class="week-option-title">${title}</h3>
      <p class="week-option-figures">${_weekOptionsEscape(card.figures)}</p>
      ${clash}
      ${freeDays}
      ${moves}
      ${action}
    </section>`;
}

function _weekOptionsFreeDayList(lines) {
  if (lines.length === 0) return '';
  return `<ul class="week-option-free-days">
      ${lines.map((line) => `<li>${_weekOptionsEscape(line)}</li>`).join('')}
    </ul>`;
}

/** Mon, Tue ... on screen; the checkbox itself carries the full name. */
function _weekOptionsDayToggle(day, checked) {
  const name = _weekOptionsEscape(day);
  return `<label class="week-options-day">
        <input type="checkbox" name="weekFreeDay" value="${name}" aria-label="${name}"${checked ? ' checked' : ''}>
        <span class="week-options-toggle" aria-hidden="true">${_weekOptionsEscape(String(day).slice(0, 3))}</span>
      </label>`;
}

function _weekOptionsBreakRadio(mins, text, checked) {
  return `<label class="week-options-break">
        <input type="radio" name="weekBreak" value="${mins}"${checked ? ' checked' : ''}>
        <span class="week-options-toggle">${text}</span>
      </label>`;
}

/**
 * The two choices of spec 14.4, as HTML: a toggle per day to keep free, each
 * a real checkbox so a keyboard and a screen reader get one for free, and a
 * pair of radio buttons for what counts as a break. `days` is
 * weekOptionsDays()'s list and `prefs` the choices to show as made. The page
 * listens for `change` on the inputs, named `weekFreeDay` and `weekBreak`.
 */
function renderWeekOptionsChoices(days, prefs) {
  const wanted = _weekOptionsPrefs(prefs);
  return `<div class="week-options-choices">
      <fieldset class="week-options-choice">
        <legend class="week-options-legend">Days to keep free</legend>
        <div class="week-options-toggles">
          ${(days || []).map((day) => _weekOptionsDayToggle(day, wanted.freeDays.includes(day))).join('')}
        </div>
      </fieldset>
      <fieldset class="week-options-choice">
        <legend class="week-options-legend">Count as a break</legend>
        <div class="week-options-toggles">
          ${_weekOptionsBreakRadio(60, '1 hour', wanted.breakMins === 60)}
          ${_weekOptionsBreakRadio(120, '2 hours', wanted.breakMins === 120)}
        </div>
      </fieldset>
    </div>`;
}

/**
 * What changes when a choice does: the notes, then the cards or the message
 * that there is nothing to gain, then the line about an unfinished search.
 * The page puts this inside `.week-options-results` and redraws only that,
 * so the control the student just changed keeps focus.
 *
 * With nothing to gain, the unfinished-search line is left out because the
 * message already says no better week was found, and any loose class still
 * on a free day is listed under it, as its card would have listed it.
 */
function renderWeekOptionsResults(view) {
  const notes = (view.notes || []).length > 0
    ? `<ul class="week-options-notes">
        ${view.notes.map((note) => `<li>${_weekOptionsEscape(note)}</li>`).join('')}
      </ul>`
    : '';
  if (view.nothingToGain) {
    const card = view.cards[0];
    return `${notes}
      <div class="week-options-best">
        <p class="week-options-message">${_weekOptionsEscape(view.message)}</p>
        ${card ? _weekOptionsFreeDayList(card.freeDayClasses || []) : ''}
      </div>`;
  }
  const unproven = view.unproven
    ? `<p class="week-options-unproven">${_weekOptionsEscape(view.unproven)}</p>`
    : '';
  return `${notes}
      ${view.cards.map(_weekOptionsCardHtml).join('')}
      ${unproven}`;
}

/**
 * The inside of the Re-arrange dialog, as HTML, from weekOptionsView's
 * result. Built the way renderResolveDialog builds the clash dialog, whose
 * head and close button it shares, so the page only has to put it in an
 * overlay and listen for a click on `.week-option-use`, whose `data-option`
 * is the card's position in `view.cards`.
 *
 * `days` is weekOptionsDays()'s list, Monday to Saturday when omitted. The
 * line for now (`.week-options-now`) and the results container
 * (`.week-options-results`, filled here so one innerHTML draws the dialog)
 * are the two parts the page redraws when a choice changes; the choices
 * themselves are drawn once.
 */
function renderWeekOptions(view, days) {
  const offered = days || WEEK_OPTIONS_ALL_DAYS.slice(0, 6);
  return `<header class="resolve-head">
      <h2 class="resolve-title">Re-arrange your week</h2>
      <p class="resolve-sub">
        <span class="week-options-now" aria-live="polite">${_weekOptionsEscape(view.now)}</span>
        Classes you locked stay where they are.
      </p>
      <button type="button" class="resolve-close" aria-label="Close without changing anything">
        <i class="bi bi-x-lg"></i>
      </button>
    </header>
    <div class="week-options">
      ${renderWeekOptionsChoices(offered, view.prefs)}
      <div class="week-options-results">${renderWeekOptionsResults(view)}</div>
    </div>`;
}
