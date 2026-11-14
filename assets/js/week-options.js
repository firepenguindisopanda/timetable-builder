'use strict';

/**
 * What the Re-arrange dialog says. WEEK-OPTIMISER-SPEC 5.3.
 *
 * Pure functions from TimetableState.rearrangeOptions()'s result to text, so
 * the wording is tested in node and the inline script in calendar.html only
 * draws it. Needs calendar-utils.js (displayTimeRange), placement.js
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

/** "up to 3 hours in a row, class on 4 days" */
function _weekOptionsFigures(week) {
  return `up to ${_weekOptionsDuration(week.runMins)} in a row, `
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
function _weekOptionsNow(current) {
  const clashes = current.clashes
    ? `${_weekOptionsCount(current.clashes, 'clash', 'clashes')}, `
    : '';
  return `Now: ${clashes}${_weekOptionsFigures(current)}.`;
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

/**
 * Everything the Re-arrange dialog, or the toast instead of it, shows.
 *
 * `result` is rearrangeOptions()'s { current, options, proven } and `index`
 * the state's groupIndex. Returns { nothingToGain, toast, now, cards,
 * unproven }; `toast` is there only when there is nothing to gain, because
 * that is the one case the page shows a toast and no dialog. Each card keeps
 * its option so the page can hand it straight to applyArrangement.
 */
function weekOptionsView(result, index) {
  const current = result.current;
  const options = result.options || [];
  const titles = WEEK_OPTIONS_TITLES[options.length] || [];

  const cards = options.map((option, i) => {
    const isCurrent = sameArrangement(option.placements, current.placements);
    return {
      title: titles[i] || '',
      figures: _weekOptionsFigures(option),
      clash: _weekOptionsClash(option.clashes),
      moves: isCurrent ? [] : _weekOptionsMoves(option, current, index),
      isCurrent,
      // What the toast says once this week is on the grid.
      applied: `${_weekOptionsFigures(option).replace(/^u/, 'U')}.`,
      option,
    };
  });

  const view = {
    nothingToGain: cards.every((card) => card.isCurrent),
    now: _weekOptionsNow(current),
    cards,
    unproven: result.proven
      ? null
      : 'These are the best weeks found. There may be a better one.',
  };
  if (view.nothingToGain) {
    view.toast = {
      // Only a finished search can call the week the best one.
      message: result.proven
        ? 'This is already the best week for these courses.'
        : 'No better week was found for these courses.',
      detail: current.placements.some((p) => p.pinned)
        ? 'Classes you locked were left where they are.'
        : '',
    };
  }
  return view;
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
      ${moves}
      ${action}
    </section>`;
}

/**
 * The inside of the Re-arrange dialog, as HTML, from weekOptionsView's
 * result. Built the way renderResolveDialog builds the clash dialog, whose
 * head and close button it shares, so the page only has to put it in an
 * overlay and listen for a click on `.week-option-use`, whose `data-option`
 * is the card's position in `view.cards`.
 */
function renderWeekOptions(view) {
  const unproven = view.unproven
    ? `<p class="week-options-unproven">${_weekOptionsEscape(view.unproven)}</p>`
    : '';
  return `<header class="resolve-head">
      <h2 class="resolve-title">Re-arrange your week</h2>
      <p class="resolve-sub">
        ${_weekOptionsEscape(view.now)}
        Classes you locked stay where they are.
      </p>
      <button type="button" class="resolve-close" aria-label="Close without changing anything">
        <i class="bi bi-x-lg"></i>
      </button>
    </header>
    <div class="week-options">
      ${view.cards.map(_weekOptionsCardHtml).join('')}
      ${unproven}
    </div>`;
}
