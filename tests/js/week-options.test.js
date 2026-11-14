'use strict';

/**
 * What the Re-arrange dialog says. WEEK-OPTIMISER-SPEC 5.3.
 *
 * The wording is pure, so it is tested here against hand-built results for
 * the exact phrasing, and against a real state built from the warehouse
 * fixture so a move is known to name a real course and both its times.
 */

const test = require('node:test');
const assert = require('node:assert');
const { load, warehouse, course } = require('./harness.js');

const api = load(
  'calendar-utils.js',
  'option-groups.js',
  'placement.js',
  'week-optimiser.js',
  'slot-identity.js',
  'timetable-state.js',
  'week-options.js'
);
const TimetableState = api.get('TimetableState');
const displayTimeRange = api.get('displayTimeRange');
const indexGroups = api.get('indexGroups');

// Read lazily, so each test fails on its own before the script exists.
function weekOptionsView(...args) {
  return api.get('weekOptionsView')(...args);
}

const plain = (value) => JSON.parse(JSON.stringify(value));

// ---- Hand-built results ----

const LAB = 'COMP 2611|Lab|all';
const LECTURE = 'COMP 2611|Lecture|all';
const TUTORIAL = 'COMP 1601|Tutorial|all';

function session(sessionId, day, startTime, endTime) {
  return { sessionId, day, startTime, endTime, weeks: null };
}

const INDEX = indexGroups([
  {
    groupId: LAB,
    courseKey: 'COMP 2611',
    type: 'Lab',
    sessions: [
      session(1, 'Monday', '12:00', '14:00'),
      session(2, 'Wednesday', '09:00', '11:00'),
      session(3, 'Friday', '13:00', '15:00'),
    ],
  },
  {
    groupId: LECTURE,
    courseKey: 'COMP 2611',
    type: 'Lecture',
    sessions: [
      session(4, 'Tuesday', '10:00', '12:00'),
      session(5, 'Thursday', '10:00', '12:00'),
    ],
  },
  {
    groupId: TUTORIAL,
    courseKey: 'COMP 1601',
    type: 'Tutorial',
    sessions: [
      session(6, 'Monday', '15:00', '16:00'),
      session(7, 'Tuesday', '15:00', '16:00'),
    ],
  },
]);

function placed(groupId, selectedSessionId, pinned = false) {
  return { courseKey: groupId.split('|')[0], groupId, selectedSessionId, pinned };
}

function week(runMins, days, placements, clashes = 0) {
  return { runMins, days, clashes, placements };
}

const NOW = [placed(LAB, 1), placed(LECTURE, 4), placed(TUTORIAL, 6)];

/** A result whose current week is NOW and whose options are the ones given. */
function resultOf(options, { current = week(300, 4, NOW), proven = true } = {}) {
  return { current, options, proven };
}

const MOVED_LAB = [placed(LAB, 2), placed(LECTURE, 4), placed(TUTORIAL, 6)];
const MOVED_TWO = [placed(LAB, 3), placed(LECTURE, 5), placed(TUTORIAL, 7)];

test('three options are titled shortest stretches, in between, fewest days', () => {
  const view = weekOptionsView(resultOf([
    week(120, 5, MOVED_LAB),
    week(180, 4, MOVED_TWO),
    week(240, 3, NOW),
  ]), INDEX);
  assert.deepEqual(
    view.cards.map((c) => c.title),
    ['Shortest stretches', 'In between', 'Fewest days']
  );
});

test('two options are titled shortest stretches and fewest days', () => {
  const view = weekOptionsView(resultOf([
    week(120, 5, MOVED_LAB),
    week(240, 3, MOVED_TWO),
  ]), INDEX);
  assert.deepEqual(view.cards.map((c) => c.title), ['Shortest stretches', 'Fewest days']);
});

test('a single option is the best week', () => {
  const view = weekOptionsView(resultOf([week(120, 4, MOVED_LAB)]), INDEX);
  assert.deepEqual(view.cards.map((c) => c.title), ['Best week']);
});

test('figures read as hours in a row and days of class', () => {
  const figures = (runMins, days) =>
    weekOptionsView(resultOf([week(runMins, days, MOVED_LAB)]), INDEX).cards[0].figures;
  assert.equal(figures(180, 4), 'up to 3 hours in a row, class on 4 days');
  assert.equal(figures(60, 1), 'up to 1 hour in a row, class on 1 day');
  assert.equal(figures(150, 2), 'up to 2 hours 30 minutes in a row, class on 2 days');
  assert.equal(figures(90, 3), 'up to 1 hour 30 minutes in a row, class on 3 days');
  assert.equal(figures(30, 1), 'up to 30 minutes in a row, class on 1 day');
  assert.equal(figures(61, 5), 'up to 1 hour 1 minute in a row, class on 5 days');
});

test('the line for now uses the same figures', () => {
  const view = weekOptionsView(resultOf([week(120, 4, MOVED_LAB)], {
    current: week(300, 4, NOW),
  }), INDEX);
  assert.equal(view.now, 'Now: up to 5 hours in a row, class on 4 days.');
});

test('no clash, one clash and several clashes are said three ways', () => {
  const clash = (n) =>
    weekOptionsView(resultOf([week(120, 4, MOVED_LAB, n)]), INDEX).cards[0].clash;
  assert.equal(clash(0), null);
  assert.equal(clash(1), '1 clash that cannot be avoided');
  assert.equal(clash(2), '2 clashes that cannot be avoided');
});

test('a move names the course, the class type and both times', () => {
  const view = weekOptionsView(resultOf([week(120, 4, MOVED_LAB)]), INDEX);
  assert.deepEqual(plain(view.cards[0].moves), [
    `COMP 2611 Lab: Mon ${displayTimeRange('12:00', '14:00')} to Wed ${displayTimeRange('09:00', '11:00')}`,
  ]);
});

test('moves are sorted by course code, then class type', () => {
  const view = weekOptionsView(resultOf([week(120, 4, MOVED_TWO)]), INDEX);
  assert.deepEqual(plain(view.cards[0].moves), [
    `COMP 1601 Tutorial: Mon ${displayTimeRange('15:00', '16:00')} to Tue ${displayTimeRange('15:00', '16:00')}`,
    `COMP 2611 Lab: Mon ${displayTimeRange('12:00', '14:00')} to Fri ${displayTimeRange('13:00', '15:00')}`,
    `COMP 2611 Lecture: Tue ${displayTimeRange('10:00', '12:00')} to Thu ${displayTimeRange('10:00', '12:00')}`,
  ]);
});

test('the order of the placements is not a move', () => {
  const view = weekOptionsView(resultOf([week(300, 4, [...NOW].reverse())]), INDEX);
  assert.deepEqual(plain(view.cards[0].moves), []);
  assert.equal(view.cards[0].isCurrent, true);
});

test('a class the grid does not hold reads as added', () => {
  const current = week(240, 3, [placed(LECTURE, 4), placed(TUTORIAL, 6)]);
  const view = weekOptionsView(resultOf([week(240, 4, MOVED_LAB)], { current }), INDEX);
  assert.deepEqual(plain(view.cards[0].moves), [
    `COMP 2611 Lab: added Wed ${displayTimeRange('09:00', '11:00')}`,
  ]);
});

test('a pinned class is never listed as a move', () => {
  const current = week(300, 4, [placed(LAB, 1, true), placed(LECTURE, 4), placed(TUTORIAL, 6)]);
  const option = week(120, 4, [placed(LAB, 1, true), placed(LECTURE, 5), placed(TUTORIAL, 6)]);
  const view = weekOptionsView(resultOf([option], { current }), INDEX);
  assert.deepEqual(plain(view.cards[0].moves), [
    `COMP 2611 Lecture: Tue ${displayTimeRange('10:00', '12:00')} to Thu ${displayTimeRange('10:00', '12:00')}`,
  ]);
});

test('the option that is the current week says so and lists no moves', () => {
  const view = weekOptionsView(resultOf([
    week(120, 5, MOVED_LAB),
    week(300, 4, NOW.map((p) => ({ ...p }))),
  ]), INDEX);
  assert.deepEqual(view.cards.map((c) => c.isCurrent), [false, true]);
  assert.equal(view.cards[0].moves.length, 1);
  assert.deepEqual(plain(view.cards[1].moves), []);
  assert.equal(view.nothingToGain, false);
  assert.equal('toast' in view, false);
});

test('each card carries its option, for applyArrangement', () => {
  const options = [week(120, 5, MOVED_LAB), week(240, 3, MOVED_TWO)];
  const view = weekOptionsView(resultOf(options), INDEX);
  assert.strictEqual(view.cards[0].option, options[0]);
  assert.strictEqual(view.cards[1].option, options[1]);
});

test('nothing to gain says it is already the best week', () => {
  const view = weekOptionsView(resultOf([week(300, 4, NOW)]), INDEX);
  assert.equal(view.nothingToGain, true);
  assert.deepEqual(plain(view.toast), {
    message: 'This is already the best week for these courses.',
    detail: '',
  });
});

test('nothing to gain around a pinned class says so', () => {
  const pinnedNow = [placed(LAB, 1, true), placed(LECTURE, 4), placed(TUTORIAL, 6)];
  const view = weekOptionsView(resultOf([week(300, 4, pinnedNow)], {
    current: week(300, 4, pinnedNow),
  }), INDEX);
  assert.equal(view.nothingToGain, true);
  assert.deepEqual(plain(view.toast), {
    message: 'This is already the best week for these courses.',
    detail: 'Classes you locked were left where they are.',
  });
});

test('an unproven search says there may be a better week', () => {
  const proven = weekOptionsView(resultOf([week(120, 4, MOVED_LAB)]), INDEX);
  assert.equal(proven.unproven, null);
  const unproven = weekOptionsView(resultOf([week(120, 4, MOVED_LAB)], { proven: false }), INDEX);
  assert.equal(unproven.unproven, 'These are the best weeks found. There may be a better one.');
});

// ---- A real state ----

function coursesOf(...codes) {
  return TimetableState.fromWarehouseResponse({
    publicationId: warehouse.publicationId,
    courses: codes.map(course),
    notFound: [],
  }).courses;
}

const FIRST_YEAR = [
  'COMP 1601',
  'COMP 1602',
  'MATH 1115',
  'FOUN 1101',
  'FOUN 1001 (FULL & PART-TIME)',
];

/** A first-year week with one unpinned class moved somewhere else by hand. */
function disturbedState() {
  const state = new TimetableState({ courses: [] });
  state.addCourses(coursesOf(...FIRST_YEAR));
  const menu = state.optionGroups.find((g) => g.sessions.length > 2);
  const placedNow = state.placements.find((p) => p.groupId === menu.groupId);
  const other = menu.sessions.find((s) => s.sessionId !== placedNow.selectedSessionId);
  state.moveEvent(menu.groupId, other.sessionId);
  state.setPinned(menu.groupId, false);
  return state;
}

test('moves from a real state name real courses and both times', () => {
  const state = disturbedState();
  const result = state.rearrangeOptions();
  const view = weekOptionsView(result, state.groupIndex);
  const index = state.groupIndex;
  const eventForPlacement = api.get('eventForPlacement');

  // Every way a placement could be described, from the grid and the options.
  const said = new Set();
  for (const p of [...result.current.placements, ...result.options.flatMap((o) => o.placements)]) {
    const e = eventForPlacement(p, index);
    said.add(`${e.courseKey} ${e.type}|${e.day.slice(0, 3)} ${displayTimeRange(e.startTime, e.endTime)}`);
  }

  const moves = view.cards.flatMap((c) => c.moves);
  assert.ok(moves.length > 0, 'expected the disturbed week to have something to move');
  for (const move of moves) {
    const match = /^(.+?): (.+) to (.+)$/.exec(move);
    assert.ok(match, `"${move}" is not a move`);
    const [, name, from, to] = match;
    assert.ok(FIRST_YEAR.some((code) => name.startsWith(code + ' ')), `${name} is not a course on the grid`);
    assert.ok(said.has(`${name}|${from}`), `${name} was never at ${from}`);
    assert.ok(said.has(`${name}|${to}`), `${name} is never offered at ${to}`);
    assert.notEqual(from, to);
  }
});

test('a real state straight after adding has a current option', () => {
  const state = new TimetableState({ courses: [] });
  state.addCourses(coursesOf(...FIRST_YEAR));
  const view = weekOptionsView(state.rearrangeOptions(), state.groupIndex);
  assert.ok(view.cards.some((c) => c.isCurrent));
  for (const card of view.cards.filter((c) => c.isCurrent)) {
    assert.deepEqual(plain(card.moves), []);
  }
});

// ---- Typography ----

const FORBIDDEN = /[\u2014\u2190-\u21FF\u27F0-\u27FF\u2900-\u297F\u2B00-\u2BFF]|->|=>/;

/** Every string anywhere in a view, the option objects left out. */
function stringsOf(view) {
  const out = [];
  const walk = (value) => {
    if (typeof value === 'string') out.push(value);
    else if (Array.isArray(value)) value.forEach(walk);
    else if (value && typeof value === 'object') {
      for (const [key, inner] of Object.entries(value)) {
        if (key !== 'option') walk(inner);
      }
    }
  };
  walk(view);
  return out;
}

test('no string the view can produce has an em dash or an arrow', () => {
  const pinnedNow = [placed(LAB, 1, true), placed(LECTURE, 4), placed(TUTORIAL, 6)];
  const views = [
    weekOptionsView(resultOf([week(120, 5, MOVED_LAB, 1), week(180, 4, MOVED_TWO, 1), week(240, 3, NOW, 1)], { proven: false }), INDEX),
    weekOptionsView(resultOf([week(150, 1, MOVED_LAB, 2), week(61, 2, MOVED_TWO, 2)]), INDEX),
    weekOptionsView(resultOf([week(30, 1, MOVED_LAB)], { current: week(240, 3, [placed(LECTURE, 4)]) }), INDEX),
    weekOptionsView(resultOf([week(300, 4, NOW)]), INDEX),
    weekOptionsView(resultOf([week(300, 4, pinnedNow)], { current: week(300, 4, pinnedNow) }), INDEX),
  ];
  const state = disturbedState();
  views.push(weekOptionsView(state.rearrangeOptions(), state.groupIndex));

  const strings = views.flatMap(stringsOf);
  assert.ok(strings.length > 20);
  for (const text of strings) {
    assert.ok(!FORBIDDEN.test(text), `"${text}" has an em dash or an arrow`);
  }
});

// ---- What the dialog adds ----

test('a week that clashes now says so before its figures', () => {
  // A clashing week can have shorter runs and fewer days than every option,
  // so without the clash the options would read as worse.
  const one = weekOptionsView(resultOf([week(120, 4, MOVED_LAB)], {
    current: week(120, 3, NOW, 1),
  }), INDEX);
  assert.equal(one.now, 'Now: 1 clash, up to 2 hours in a row, class on 3 days.');
  const two = weekOptionsView(resultOf([week(120, 4, MOVED_LAB)], {
    current: week(120, 3, NOW, 2),
  }), INDEX);
  assert.equal(two.now, 'Now: 2 clashes, up to 2 hours in a row, class on 3 days.');
});

test('a class the option does not keep reads as removed', () => {
  // An unlocked extra sitting leaves a group holding two loose classes, and
  // re-arranging places one of them.
  const current = week(300, 4, [placed(LAB, 1), placed(LAB, 3), placed(LECTURE, 4), placed(TUTORIAL, 6)]);
  const view = weekOptionsView(resultOf([week(120, 4, MOVED_LAB)], { current }), INDEX);
  assert.deepEqual(plain(view.cards[0].moves), [
    `COMP 2611 Lab: Mon ${displayTimeRange('12:00', '14:00')} to Wed ${displayTimeRange('09:00', '11:00')}`,
    `COMP 2611 Lab: removed Fri ${displayTimeRange('13:00', '15:00')}`,
  ]);
});

test('an unfinished search does not call the week the best', () => {
  const view = weekOptionsView(resultOf([week(300, 4, NOW)], { proven: false }), INDEX);
  assert.equal(view.nothingToGain, true);
  assert.equal(view.toast.message, 'No better week was found for these courses.');
});

function renderWeekOptions(view) {
  return api.get('renderWeekOptions')(view);
}

test('the dialog shows the line for now and one card per option', () => {
  const view = weekOptionsView(resultOf([
    week(120, 5, MOVED_LAB),
    week(180, 4, MOVED_TWO),
    week(300, 4, NOW.map((p) => ({ ...p }))),
  ]), INDEX);
  const html = renderWeekOptions(view);

  assert.ok(html.includes('Now: up to 5 hours in a row, class on 4 days.'));
  assert.equal(html.match(/<section class="week-option/g).length, 3);
  for (const title of ['Shortest stretches', 'In between', 'Fewest days']) {
    assert.ok(html.includes(`<h3 class="week-option-title">${title}</h3>`));
  }
  assert.ok(html.includes('Moves 1 class:'));
  assert.ok(html.includes('Moves 3 classes:'));
  assert.ok(html.includes('class="resolve-close"'));
});

test('a card has one button naming its option, and the current week has none', () => {
  const view = weekOptionsView(resultOf([
    week(120, 5, MOVED_LAB),
    week(300, 4, NOW.map((p) => ({ ...p }))),
  ]), INDEX);
  const html = renderWeekOptions(view);

  const buttons = html.match(/<button type="button" class="btn btn-sm btn-accent week-option-use"[^>]*>/g);
  assert.equal(buttons.length, 1);
  assert.ok(buttons[0].includes('data-option="0"'));
  assert.ok(buttons[0].includes('aria-label="Use this week: Shortest stretches"'));
  assert.ok(html.includes('This is the week you have now.'));
  assert.ok(html.includes('week-option is-current'));
});

test('the dialog states an unavoidable clash and an unfinished search', () => {
  const view = weekOptionsView(resultOf([week(120, 4, MOVED_LAB, 1)], { proven: false }), INDEX);
  const html = renderWeekOptions(view);
  assert.ok(html.includes('1 clash that cannot be avoided'));
  assert.ok(html.includes('These are the best weeks found. There may be a better one.'));

  const clean = renderWeekOptions(weekOptionsView(resultOf([week(120, 4, MOVED_LAB)]), INDEX));
  assert.ok(!clean.includes('week-option-clash'));
  assert.ok(!clean.includes('week-options-unproven'));
});

test('text from the timetable is escaped in the dialog', () => {
  const index = indexGroups([{
    groupId: 'X|Lab|all',
    courseKey: '<b>X & Y</b>',
    type: 'Lab',
    sessions: [session(1, 'Monday', '09:00', '10:00'), session(2, 'Tuesday', '09:00', '10:00')],
  }]);
  const at = (id) => [{ courseKey: '<b>X & Y</b>', groupId: 'X|Lab|all', selectedSessionId: id, pinned: false }];
  const view = weekOptionsView({ current: week(60, 1, at(1)), options: [week(60, 1, at(2))], proven: true }, index);
  const html = renderWeekOptions(view);
  assert.ok(html.includes('&lt;b&gt;X &amp; Y&lt;/b&gt; Lab'));
  assert.ok(!html.includes('<b>X'));
});
