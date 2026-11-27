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
  assert.equal(view.message, 'This is already the best week for these choices.');
  assert.equal('toast' in view, false);
});

test('nothing to gain around a pinned class says the same, inside the dialog', () => {
  const pinnedNow = [placed(LAB, 1, true), placed(LECTURE, 4), placed(TUTORIAL, 6)];
  const view = weekOptionsView(resultOf([week(300, 4, pinnedNow)], {
    current: week(300, 4, pinnedNow),
  }), INDEX);
  assert.equal(view.nothingToGain, true);
  assert.equal(view.message, 'This is already the best week for these choices.');
  assert.equal('toast' in view, false);
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
  assert.equal(view.message, 'No better week was found for these choices.');
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

// ---- The student's preferences. WEEK-OPTIMISER-SPEC 14 ----

/** A page function read lazily, so each test fails on its own before it exists. */
function lazy(name) {
  return (...args) => api.get(name)(...args);
}
const loadWeekPrefs = lazy('loadWeekPrefs');
const saveWeekPrefs = lazy('saveWeekPrefs');
const weekOptionsDays = lazy('weekOptionsDays');
const renderWeekOptionsChoices = lazy('renderWeekOptionsChoices');
const renderWeekOptionsResults = lazy('renderWeekOptionsResults');

const DEFAULTS = { freeDays: [], breakMins: 60 };
const KEY = 'celcat_week_prefs_v1';

/** A Storage stand-in holding the given items. */
function memoryStorage(items = {}) {
  const data = new Map(Object.entries(items));
  return {
    getItem: (key) => (data.has(key) ? data.get(key) : null),
    setItem: (key, value) => { data.set(key, String(value)); },
    data,
  };
}

const throwingStorage = {
  getItem() { throw new Error('SecurityError'); },
  setItem() { throw new Error('QuotaExceededError'); },
};

test('remembered choices come back as they were saved', () => {
  const storage = memoryStorage();
  const chosen = { freeDays: ['Monday', 'Saturday'], breakMins: 120 };
  assert.equal(saveWeekPrefs(storage, chosen), true);
  assert.ok(storage.data.has(KEY));
  assert.deepEqual(plain(loadWeekPrefs(storage)), chosen);
});

test('saved days are kept in week order, once each', () => {
  const storage = memoryStorage();
  saveWeekPrefs(storage, { freeDays: ['Friday', 'Monday', 'Friday'], breakMins: 60 });
  assert.deepEqual(plain(loadWeekPrefs(storage)), { freeDays: ['Monday', 'Friday'], breakMins: 60 });
});

test('nothing remembered reads as the defaults', () => {
  assert.deepEqual(plain(loadWeekPrefs(memoryStorage())), DEFAULTS);
  assert.deepEqual(plain(loadWeekPrefs(null)), DEFAULTS);
  assert.deepEqual(plain(loadWeekPrefs(undefined)), DEFAULTS);
});

test('a malformed or wrongly typed value reads as the defaults', () => {
  const read = (raw) => plain(loadWeekPrefs(memoryStorage({ [KEY]: raw })));
  assert.deepEqual(read('{not json'), DEFAULTS);
  assert.deepEqual(read('null'), DEFAULTS);
  assert.deepEqual(read('"Monday"'), DEFAULTS);
  assert.deepEqual(read('[1,2]'), DEFAULTS);
  assert.deepEqual(read('{"freeDays":"Monday","breakMins":"120"}'), DEFAULTS);
  assert.deepEqual(read('{"freeDays":[1,null,{}],"breakMins":90}'), DEFAULTS);
  assert.deepEqual(read('{"freeDays":["Funday","monday","Mon"],"breakMins":0}'), DEFAULTS);
});

test('only real day names and a 1 or 2 hour break are taken', () => {
  const read = (value) => plain(loadWeekPrefs(memoryStorage({ [KEY]: JSON.stringify(value) })));
  assert.deepEqual(read({ freeDays: ['Funday', 'Sunday'], breakMins: 120 }), { freeDays: ['Sunday'], breakMins: 120 });
  assert.deepEqual(read({ freeDays: ['Tuesday'], breakMins: 180 }), { freeDays: ['Tuesday'], breakMins: 60 });
});

test('a storage that throws reads as the defaults and saving says it failed', () => {
  assert.deepEqual(plain(loadWeekPrefs(throwingStorage)), DEFAULTS);
  assert.equal(saveWeekPrefs(throwingStorage, { freeDays: ['Monday'], breakMins: 120 }), false);
  assert.equal(saveWeekPrefs(null, { freeDays: ['Monday'], breakMins: 120 }), false);
});

test('Sunday is offered only when some class could fall on a Sunday', () => {
  const MON_TO_SAT = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
  assert.deepEqual(plain(weekOptionsDays([...INDEX.values()])), MON_TO_SAT);
  assert.deepEqual(plain(weekOptionsDays([])), MON_TO_SAT);
  const withSunday = [...INDEX.values(), {
    groupId: 'X|Lab|all', courseKey: 'X', type: 'Lab',
    sessions: [session(9, 'Sunday', '10:00', '11:00')],
  }];
  assert.deepEqual(plain(weekOptionsDays(withSunday)), [...MON_TO_SAT, 'Sunday']);
});

test('figures with a 2-hour break say so, in the cards, the line for now and the toast', () => {
  const prefs = { freeDays: [], breakMins: 120 };
  const view = weekOptionsView(resultOf([week(240, 3, MOVED_LAB)], {
    current: week(300, 4, NOW, 1),
  }), INDEX, prefs);
  assert.equal(view.cards[0].figures, 'up to 4 hours without a 2-hour break, class on 3 days');
  assert.equal(view.now, 'Now: 1 clash, up to 5 hours without a 2-hour break, class on 4 days.');
  assert.equal(view.cards[0].applied, 'Up to 4 hours without a 2-hour break, class on 3 days.');
});

test('figures with a 1-hour break read exactly as before', () => {
  const view = weekOptionsView(resultOf([week(240, 3, MOVED_LAB)]), INDEX, { freeDays: [], breakMins: 60 });
  assert.equal(view.cards[0].figures, 'up to 4 hours in a row, class on 3 days');
  assert.equal(view.now, 'Now: up to 5 hours in a row, class on 4 days.');
  assert.equal(view.cards[0].applied, 'Up to 4 hours in a row, class on 3 days.');
});

// Groups for the free-day lines: one that only runs on Monday, one on Monday
// or Friday, one on three free days, and one locked on a Saturday.
const ONLY_MON = 'COMP 1601|Lecture|all';
const MON_FRI = 'MATH 1115|Tutorial|all';
const THREE_DAYS = 'FOUN 1101|Seminar|all';
const SAT_LAB = 'COMP 1602|Lab|all';
const FREE_INDEX = indexGroups([
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
  { groupId: ONLY_MON, courseKey: 'COMP 1601', type: 'Lecture', sessions: [session(10, 'Monday', '12:00', '13:00')] },
  {
    groupId: MON_FRI,
    courseKey: 'MATH 1115',
    type: 'Tutorial',
    sessions: [session(20, 'Monday', '09:00', '10:00'), session(21, 'Friday', '09:00', '10:00')],
  },
  {
    groupId: THREE_DAYS,
    courseKey: 'FOUN 1101',
    type: 'Seminar',
    sessions: [
      session(40, 'Saturday', '15:00', '16:00'),
      session(41, 'Monday', '15:00', '16:00'),
      session(42, 'Friday', '15:00', '16:00'),
    ],
  },
  {
    groupId: SAT_LAB,
    courseKey: 'COMP 1602',
    type: 'Lab',
    sessions: [session(30, 'Saturday', '09:00', '11:00'), session(31, 'Tuesday', '09:00', '11:00')],
  },
]);
const FREE = { freeDays: ['Monday', 'Friday', 'Saturday'], breakMins: 60 };
const FREE_NOW = [
  placed(LAB, 1), placed(ONLY_MON, 10), placed(MON_FRI, 20), placed(THREE_DAYS, 41), placed(SAT_LAB, 30, true),
];
const FREE_OPTION = [
  placed(LAB, 2), placed(ONLY_MON, 10), placed(MON_FRI, 21), placed(THREE_DAYS, 42), placed(SAT_LAB, 30, true),
];

function freeView(options = [week(120, 4, FREE_OPTION)], extra = {}) {
  return weekOptionsView(
    resultOf(options, { current: week(240, 4, FREE_NOW), ...extra }),
    FREE_INDEX,
    FREE
  );
}

test('a card lists each of its loose classes on a free day', () => {
  const view = freeView();
  assert.deepEqual(plain(view.cards[0].freeDayClasses), [
    `On a day you wanted free: COMP 1601 Lecture, Mon ${displayTimeRange('12:00', '13:00')}`,
    `On a day you wanted free: FOUN 1101 Seminar, Fri ${displayTimeRange('15:00', '16:00')}`,
    `On a day you wanted free: MATH 1115 Tutorial, Fri ${displayTimeRange('09:00', '10:00')}`,
  ]);
});

test('a class left on a free day that also runs on another day says its other times clash', () => {
  // The lab runs Monday, Wednesday and Friday; with Monday and Friday free it
  // sits on Monday only because Wednesday would clash.
  const option = [placed(LAB, 1), placed(ONLY_MON, 10), placed(MON_FRI, 21), placed(THREE_DAYS, 42), placed(SAT_LAB, 30, true)];
  const lab = `On a day you wanted free: COMP 2611 Lab, Mon ${displayTimeRange('12:00', '14:00')}`;
  const proven = freeView([week(120, 4, option)]);
  assert.ok(proven.cards[0].freeDayClasses.includes(`${lab}. Its other times clash with your classes.`));
  // A class with no other day gets no reason; the note above the cards says it.
  assert.ok(proven.cards[0].freeDayClasses.includes(
    `On a day you wanted free: COMP 1601 Lecture, Mon ${displayTimeRange('12:00', '13:00')}`
  ));
  // An unfinished search cannot claim the other times clash.
  const unproven = freeView([week(120, 4, option)], { proven: false });
  assert.ok(unproven.cards[0].freeDayClasses.includes(lab));
});

test('a card with no class on a free day lists none, and no free days lists none', () => {
  const kept = [placed(LAB, 2), placed(SAT_LAB, 31)];
  const view = weekOptionsView(
    resultOf([week(120, 2, kept)], { current: week(120, 2, [placed(LAB, 1), placed(SAT_LAB, 31)]) }),
    FREE_INDEX,
    FREE
  );
  assert.deepEqual(plain(view.cards[0].freeDayClasses), []);
  assert.deepEqual(plain(view.notes), []);

  const none = weekOptionsView(resultOf([week(120, 4, MOVED_LAB)]), INDEX);
  assert.deepEqual(plain(none.cards[0].freeDayClasses), []);
  assert.deepEqual(plain(none.notes), []);
});

test('notes name the classes that only run on a free day, and the locked ones on one', () => {
  assert.deepEqual(plain(freeView().notes), [
    'COMP 1601 Lecture only runs on Monday.',
    'FOUN 1101 Seminar only runs on Monday, Friday or Saturday.',
    'MATH 1115 Tutorial only runs on Monday or Friday.',
    'You locked COMP 1602 Lab on Saturday.',
  ]);
});

test('a class with any sitting off the free days gets no note', () => {
  const view = weekOptionsView(
    resultOf([week(120, 4, FREE_OPTION)], { current: week(240, 4, FREE_NOW) }),
    FREE_INDEX,
    { freeDays: ['Monday'], breakMins: 60 }
  );
  assert.deepEqual(plain(view.notes), ['COMP 1601 Lecture only runs on Monday.']);
});

test('the nothing-to-gain message reads the same with free days chosen', () => {
  const proven = freeView([week(240, 4, FREE_NOW)]);
  assert.equal(proven.nothingToGain, true);
  assert.equal(proven.message, 'This is already the best week for these choices.');
  const unproven = freeView([week(240, 4, FREE_NOW)], { proven: false });
  assert.equal(unproven.message, 'No better week was found for these choices.');
  const choosing = freeView();
  assert.equal(choosing.nothingToGain, false);
  assert.equal(choosing.message, null);
});

test('no string the preferences add has an em dash or an arrow', () => {
  const views = [freeView(), freeView([week(240, 4, FREE_NOW)], { proven: false })];
  const strings = views.flatMap(stringsOf);
  assert.ok(strings.length > 10);
  for (const text of strings) {
    assert.ok(!FORBIDDEN.test(text), `"${text}" has an em dash or an arrow`);
  }
});

// The dialog's choices and results

const ALL_DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

test('the choices have one checkbox per day offered, named in full', () => {
  const html = renderWeekOptionsChoices(ALL_DAYS.slice(0, 6), { freeDays: ['Monday', 'Friday'], breakMins: 60 });
  const boxes = html.match(/<input type="checkbox"[^>]*>/g);
  assert.equal(boxes.length, 6);
  ALL_DAYS.slice(0, 6).forEach((day, i) => {
    assert.ok(boxes[i].includes(`value="${day}"`), `${day} is not box ${i + 1}`);
    assert.ok(boxes[i].includes(`aria-label="${day}"`), `${day} has no full name`);
    assert.equal(boxes[i].includes(' checked'), day === 'Monday' || day === 'Friday', day);
  });
  assert.ok(html.includes('>Mon<'));
  assert.ok(html.includes('>Sat<'));
  assert.ok(!html.includes('Sunday'));
  assert.ok(html.includes('<legend class="week-options-legend">Days to keep free</legend>'));
});

test('Sunday gets a checkbox when it is offered', () => {
  const html = renderWeekOptionsChoices(ALL_DAYS, DEFAULTS);
  assert.equal(html.match(/<input type="checkbox"/g).length, 7);
  assert.ok(html.includes('aria-label="Sunday"'));
  assert.ok(html.includes('>Sun<'));
});

test('the break is a pair of radio buttons with the current choice checked', () => {
  const radios = (prefs) => renderWeekOptionsChoices(ALL_DAYS.slice(0, 6), prefs)
    .match(/<label class="week-options-break">[\s\S]*?<\/label>/g);
  const one = radios({ freeDays: [], breakMins: 60 });
  assert.equal(one.length, 2);
  assert.ok(one[0].includes('type="radio"') && one[0].includes('value="60"') && one[0].includes(' checked'));
  assert.ok(one[0].includes('1 hour'));
  assert.ok(one[1].includes('value="120"') && !one[1].includes(' checked'));
  assert.ok(one[1].includes('2 hours'));

  const two = radios({ freeDays: [], breakMins: 120 });
  assert.ok(!two[0].includes(' checked'));
  assert.ok(two[1].includes(' checked'));
  const html = renderWeekOptionsChoices(ALL_DAYS.slice(0, 6), DEFAULTS);
  assert.ok(html.includes('<legend class="week-options-legend">Count as a break</legend>'));
});

test('the dialog holds the choices and a results container the page can redraw', () => {
  const view = freeView();
  const html = renderWeekOptions(view, ALL_DAYS.slice(0, 6));
  assert.ok(html.includes('class="week-options-now"'));
  assert.ok(html.includes('Days to keep free'));
  assert.ok(html.includes('Count as a break'));
  const results = renderWeekOptionsResults(view);
  assert.ok(html.includes(`<div class="week-options-results">${results}</div>`));
  // The choices are outside the results, so redrawing those keeps them.
  assert.ok(!results.includes('<input'));
  assert.ok(html.indexOf('Days to keep free') < html.indexOf('week-options-results'));
});

test('the results put the notes first, then the cards, then the unproven line', () => {
  const html = renderWeekOptionsResults(freeView(undefined, { proven: false }));
  const notes = html.indexOf('COMP 1601 Lecture only runs on Monday.');
  const card = html.indexOf('<section class="week-option');
  const unproven = html.indexOf('These are the best weeks found.');
  assert.ok(notes >= 0 && card > notes && unproven > card, `${notes} ${card} ${unproven}`);
  assert.ok(html.includes('On a day you wanted free: COMP 1601 Lecture'));
});

test('with nothing to gain the results say so in place of the cards', () => {
  const html = renderWeekOptionsResults(freeView([week(240, 4, FREE_NOW)]));
  assert.ok(html.includes('This is already the best week for these choices.'));
  assert.ok(!html.includes('<section class="week-option'));
  assert.ok(!html.includes('week-option-use'));

  const unproven = renderWeekOptionsResults(freeView([week(240, 4, FREE_NOW)], { proven: false }));
  assert.ok(unproven.includes('No better week was found for these choices.'));
  assert.ok(!unproven.includes('These are the best weeks found.'));
});

test('free-day lines and notes are escaped', () => {
  const index = indexGroups([
    { groupId: 'X|Lab|all', courseKey: '<b>X & Y</b>', type: 'Lab', sessions: [session(1, 'Monday', '09:00', '10:00')] },
    {
      groupId: 'Z|Lab|all',
      courseKey: '<i>Z</i>',
      type: 'Lab',
      sessions: [session(2, 'Friday', '09:00', '10:00'), session(3, 'Tuesday', '09:00', '10:00')],
    },
  ]);
  const at = [
    { courseKey: '<b>X & Y</b>', groupId: 'X|Lab|all', selectedSessionId: 1, pinned: false },
    { courseKey: '<i>Z</i>', groupId: 'Z|Lab|all', selectedSessionId: 2, pinned: true },
  ];
  const prefs = { freeDays: ['Monday', 'Friday'], breakMins: 60 };
  const view = weekOptionsView({ current: week(60, 2, at), options: [week(60, 2, at)], proven: true }, index, prefs);
  const html = renderWeekOptionsResults(view);
  assert.ok(html.includes('&lt;b&gt;X &amp; Y&lt;/b&gt; Lab only runs on Monday.'));
  assert.ok(html.includes('You locked &lt;i&gt;Z&lt;/i&gt; Lab on Friday.'));
  assert.ok(!html.includes('<b>') && !html.includes('<i>Z'));

  // A card, rather than the nothing-to-gain message, to show its free-day line.
  const moved = [{ ...at[1], selectedSessionId: 3 }, at[0]];
  const cards = renderWeekOptionsResults(weekOptionsView(
    { current: week(60, 2, moved), options: [week(60, 2, at)], proven: true },
    index,
    prefs
  ));
  assert.ok(cards.includes('On a day you wanted free: &lt;b&gt;X &amp; Y&lt;/b&gt; Lab'));
  assert.ok(!cards.includes('<b>'));
});

test('the choices escape the day names they are given', () => {
  const html = renderWeekOptionsChoices(['Monday', '<x>"'], DEFAULTS);
  assert.ok(!html.includes('<x>'));
  assert.ok(html.includes('&lt;x&gt;&quot;'));
});

test('a real five-course load with three free days and a 2-hour break', () => {
  const state = new TimetableState({ courses: [] });
  state.addCourses(coursesOf(...FIRST_YEAR));
  const prefs = { freeDays: ['Monday', 'Friday', 'Saturday'], breakMins: 120 };
  const result = state.rearrangeOptions(prefs);
  const view = weekOptionsView(result, state.groupIndex, prefs);

  assert.match(view.now, /^Now: (\d+ clash(es)?, )?up to .+ without a 2-hour break, class on \d days?\.$/);
  view.cards.forEach((card, i) => {
    assert.match(card.figures, /without a 2-hour break/);
    assert.equal(card.freeDayClasses.length, result.options[i].blocked);
    for (const line of card.freeDayClasses) {
      assert.match(line, /^On a day you wanted free: .+, (Mon|Fri|Sat) /);
    }
  });
  const html = renderWeekOptions(view, weekOptionsDays(state.optionGroups));
  assert.ok(html.includes('value="Monday" aria-label="Monday" checked'));
  assert.ok(html.includes('value="120" checked'));
});
