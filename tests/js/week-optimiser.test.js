'use strict';

/**
 * How hard a week an arrangement makes.
 *
 * The hand-built days state their answers outright. The fixture test ties
 * weekQuality to the independent brute-force scorer that built
 * week_loads.json, so the two cannot agree by sharing a mistake.
 */

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const { load, warehouse } = require('./harness.js');

// In the browser's order: the solver sorts candidates with option-groups.js
// and sits after placement.js in calendar.html.
const api = load('calendar-utils.js', 'option-groups.js', 'placement.js', 'week-optimiser.js');
const {
  weekQuality,
  RUN_BREAK_MINS,
  eventsCollide,
  findConflicts,
  weeklyOptionGroups,
  indexGroups,
  eventsFor,
  placeCourses,
} = api.take(
  'weekQuality',
  'RUN_BREAK_MINS',
  'eventsCollide',
  'findConflicts',
  'weeklyOptionGroups',
  'indexGroups',
  'eventsFor',
  'placeCourses'
);

function ev(day, startTime, endTime, weeks = null) {
  return { day, startTime, endTime, weeks };
}

// vm contexts have their own Object.prototype, so compare field by field.
function assertQuality(events, runMins, days) {
  const got = weekQuality(events);
  assert.strictEqual(got.runMins, runMins);
  assert.strictEqual(got.days, days);
}

test('a free hour ends a run', () => {
  assert.strictEqual(RUN_BREAK_MINS, 60);
});

test('two classes back to back are one run of four hours', () => {
  assertQuality([ev('Monday', '08:00', '10:00'), ev('Monday', '10:00', '12:00')], 240, 1);
});

test('a 30 minute gap does not end the run', () => {
  assertQuality([ev('Monday', '08:00', '10:00'), ev('Monday', '10:30', '12:30')], 270, 1);
});

test('a 60 minute gap ends the run, so the longest is one class', () => {
  assertQuality([ev('Monday', '08:00', '10:00'), ev('Monday', '11:00', '13:00')], 120, 1);
});

test('overlapping classes are one run', () => {
  assertQuality([ev('Monday', '08:00', '10:00'), ev('Monday', '09:00', '11:00')], 180, 1);
});

test('a class inside another does not change the run', () => {
  assertQuality([ev('Monday', '08:00', '12:00'), ev('Monday', '09:00', '10:00')], 240, 1);
});

test('a class inside another does not shorten the reach for the next one', () => {
  // 8-12 holds 9-10; the 12:30 class starts 30 minutes after 12:00, not
  // 150 after 10:00, so it joins: 08:00 to 13:30.
  assertQuality(
    [ev('Monday', '08:00', '12:00'), ev('Monday', '09:00', '10:00'), ev('Monday', '12:30', '13:30')],
    330,
    1
  );
});

test('in three classes only the first two are joined', () => {
  assertQuality(
    [ev('Monday', '08:00', '10:00'), ev('Monday', '10:30', '11:30'), ev('Monday', '12:30', '14:30')],
    210,
    1
  );
});

test('events given out of order are sorted by start time', () => {
  assertQuality([ev('Monday', '10:00', '12:00'), ev('Monday', '08:00', '10:00')], 240, 1);
});

test('runs on different days are not joined', () => {
  assertQuality([ev('Monday', '08:00', '10:00'), ev('Tuesday', '10:00', '12:00')], 120, 2);
});

test('classes that never share a week are scored week by week', () => {
  assertQuality(
    [
      ev('Monday', '08:00', '10:00', [1, 2, 3, 4]),
      ev('Monday', '10:00', '12:00', [5, 6, 7, 8]),
    ],
    120,
    1
  );
});

test('classes that share some weeks join in those weeks', () => {
  assertQuality(
    [
      ev('Monday', '08:00', '10:00', [1, 2, 3]),
      ev('Monday', '10:00', '12:00', [3, 4]),
    ],
    240,
    1
  );
});

test('an event with no weeks counts in every week another event names', () => {
  assertQuality(
    [
      ev('Monday', '08:00', '10:00', null),
      ev('Monday', '10:00', '12:00', [2]),
    ],
    240,
    1
  );
  assertQuality(
    [
      ev('Monday', '08:00', '10:00', []),
      ev('Monday', '10:00', '12:00', [2]),
    ],
    240,
    1
  );
  assertQuality(
    [{ day: 'Monday', startTime: '08:00', endTime: '10:00' }, ev('Monday', '10:00', '12:00', [2])],
    240,
    1
  );
});

test('all events with no weeks make one undated week', () => {
  assertQuality(
    [ev('Monday', '08:00', '10:00'), ev('Monday', '10:00', '12:00'), ev('Friday', '09:00', '10:00')],
    240,
    2
  );
});

test('days is the worst week, not the distinct days across the semester', () => {
  assertQuality(
    [
      ev('Monday', '08:00', '09:00', [1]),
      ev('Tuesday', '08:00', '09:00', [2]),
      ev('Wednesday', '08:00', '09:00', [3]),
    ],
    60,
    1
  );
});

test('days takes the largest week and counts a day once', () => {
  assertQuality(
    [
      ev('Monday', '08:00', '09:00', [1, 2]),
      ev('Monday', '14:00', '15:00', [1, 2]),
      ev('Tuesday', '08:00', '09:00', [2]),
    ],
    60,
    2
  );
});

test('no events', () => {
  assertQuality([], 0, 0);
});

// ---- agreement with the independent scorer ----

const FIXTURE = JSON.parse(
  fs.readFileSync(path.join(__dirname, '..', 'fixtures', 'week_loads.json'), 'utf8')
);
const MAX_ARRANGEMENTS = 25000;

function countClashes(events) {
  let n = 0;
  for (let i = 0; i < events.length; i++) {
    for (let j = i + 1; j < events.length; j++) {
      if (eventsCollide(events[i], events[j])) n++;
    }
  }
  return n;
}

function frontOf(pairs) {
  const distinct = new Map();
  for (const [r, d] of pairs) distinct.set(`${r}|${d}`, [r, d]);
  const all = [...distinct.values()];
  return all
    .filter(([r, d]) => !all.some(([r2, d2]) => (r2 !== r || d2 !== d) && r2 <= r && d2 <= d))
    .sort((a, b) => a[0] - b[0])
    .map(([runMins, days]) => ({ runMins, days }));
}

function bruteForce(c) {
  let best = Infinity;
  let pairs = [];
  let seen = 0;
  const chosen = [...c.fixed];
  function walk(i) {
    if (i === c.groups.length) {
      seen++;
      const clashes = countClashes(chosen);
      if (clashes > best) return;
      const q = weekQuality(chosen);
      if (clashes < best) {
        best = clashes;
        pairs = [];
      }
      pairs.push([q.runMins, q.days]);
      return;
    }
    for (const sitting of c.groups[i].sittings) {
      chosen.push(sitting);
      walk(i + 1);
      chosen.pop();
    }
  }
  walk(0);
  return { clashes: best, front: frontOf(pairs), seen };
}

for (const c of FIXTURE.cases) {
  if (c.arrangements > MAX_ARRANGEMENTS) continue;
  // A case with preferences is scored with them, further down.
  if (c.preferences) continue;
  test(`weekQuality agrees with the fixture: ${c.name}`, () => {
    assert.strictEqual(FIXTURE.runBreakMins, RUN_BREAK_MINS);
    const got = bruteForce(c);
    assert.strictEqual(got.seen, c.arrangements);
    assert.strictEqual(got.clashes, c.expected.clashes);
    assert.deepStrictEqual(
      JSON.parse(JSON.stringify(got.front)),
      c.expected.front.map(({ runMins, days }) => ({ runMins, days }))
    );
  });
}

// ---- bestWeeks: the exact search ----

const { buildInstances } = require('../fixtures/build_week_loads.js');

// Read lazily so the tests above still run, and fail one by one, while the
// solver does not exist yet.
function bestWeeks(...args) {
  return api.get('bestWeeks')(...args);
}

/** vm objects carry another realm's prototypes; compare plain copies. */
function plain(value) {
  return JSON.parse(JSON.stringify(value));
}

/** The fixture's `{ groupId, sittings }` in the app's option-group shape. */
function asAppGroups(groups) {
  return groups.map((g) => ({ groupId: g.groupId, sessions: g.sittings }));
}

/** The events an arrangement puts on the grid: fixed plus one per group. */
function eventsOf(fixed, groups, sessionIds) {
  const events = [...fixed];
  for (const group of groups) {
    assert.ok(
      Object.prototype.hasOwnProperty.call(sessionIds, group.groupId),
      `no session chosen for ${group.groupId}`
    );
    const session = group.sessions.find((s) => s.sessionId === sessionIds[group.groupId]);
    assert.ok(session, `${sessionIds[group.groupId]} is not a sitting of ${group.groupId}`);
    events.push(session);
  }
  assert.strictEqual(Object.keys(sessionIds).length, groups.length);
  return events;
}

/** Each entry's arrangement really scores what the entry claims. */
function assertEntriesScore(result, fixed, groups) {
  for (const entry of result.front) {
    const events = eventsOf(fixed, groups, entry.sessionIds);
    assert.strictEqual(findConflicts(events).length, result.clashes);
    const q = weekQuality(events);
    assert.strictEqual(q.runMins, entry.runMins);
    assert.strictEqual(q.days, entry.days);
  }
}

function pairsOf(result) {
  return plain(result.front.map(({ runMins, days }) => ({ runMins, days })));
}

const BEST_TIMINGS = [];

for (const c of FIXTURE.cases) {
  // A case with preferences is searched with them, further down.
  if (c.preferences) continue;
  test(`bestWeeks matches the fixture: ${c.name}`, () => {
    const groups = asAppGroups(c.groups);
    const started = process.hrtime.bigint();
    const got = bestWeeks(c.fixed, groups);
    const ms = Number(process.hrtime.bigint() - started) / 1e6;
    BEST_TIMINGS.push(`${c.name}: ${got.nodes} nodes, ${ms.toFixed(1)} ms`);
    assert.strictEqual(got.proven, true);
    assert.strictEqual(got.clashes, c.expected.clashes);
    assert.deepStrictEqual(pairsOf(got), plain(c.expected.front));
    assertEntriesScore(got, c.fixed, groups);
  });
}

test('per-case node counts and times, printed on request', () => {
  if (process.env.WEEK_OPTIMISER_TIMINGS) console.log(BEST_TIMINGS.join('\n'));
});

// Two groups, four arrangements. One day needs both sittings on the same day:
// Monday (m1, t1) or Tuesday (m2, t2), each a 60 minute run on one day.
// Mixing days scores (60, 2), which the one-day entries beat.
const TWO_DAYS = [
  {
    groupId: 'g1',
    sessions: [
      { sessionId: 'm1', day: 'Monday', startTime: '08:00', endTime: '09:00', weeks: null },
      { sessionId: 'm2', day: 'Tuesday', startTime: '08:00', endTime: '09:00', weeks: null },
    ],
  },
  {
    groupId: 'g2',
    sessions: [
      { sessionId: 't1', day: 'Monday', startTime: '12:00', endTime: '13:00', weeks: null },
      { sessionId: 't2', day: 'Tuesday', startTime: '12:00', endTime: '13:00', weeks: null },
    ],
  },
];

test('with no reference the canonical-first arrangement stands for the entry', () => {
  const got = bestWeeks([], TWO_DAYS);
  assert.deepStrictEqual(plain(got.front), [
    { runMins: 60, days: 1, sessionIds: { g1: 'm1', g2: 't1' } },
  ]);
});

test('a reference that reaches a front entry is returned unchanged', () => {
  const got = bestWeeks([], TWO_DAYS, [{ g1: 'm2', g2: 't2' }]);
  assert.strictEqual(got.proven, true);
  assert.deepStrictEqual(plain(got.front), [
    { runMins: 60, days: 1, sessionIds: { g1: 'm2', g2: 't2' } },
  ]);
});

test('a partial only matched by a held entry is abandoned, not just one beaten', () => {
  // The reference holds (60, 1). Each first sitting alone already scores
  // (60, 1), so after the empty root both partials stop: three nodes. Pruning
  // only on strictly beaten would go on to every leaf and visit seven.
  const got = bestWeeks([], TWO_DAYS, [{ g1: 'm1', g2: 't1' }]);
  assert.strictEqual(got.proven, true);
  assert.strictEqual(got.nodes, 3);
});

test('of two references reaching the same entry the earlier wins', () => {
  const first = bestWeeks([], TWO_DAYS, [{ g1: 'm2', g2: 't2' }, { g1: 'm1', g2: 't1' }]);
  assert.deepStrictEqual(plain(first.front[0].sessionIds), { g1: 'm2', g2: 't2' });
  const second = bestWeeks([], TWO_DAYS, [{ g1: 'm1', g2: 't1' }, { g1: 'm2', g2: 't2' }]);
  assert.deepStrictEqual(plain(second.front[0].sessionIds), { g1: 'm1', g2: 't1' });
});

test('an invalid reference is ignored', () => {
  const invalid = [
    { g1: 'm2' },
    { g1: 'm2', g2: 'nope' },
    { g1: 't2', g2: 't2' },
    {},
    null,
  ];
  for (const reference of invalid) {
    const got = bestWeeks([], TWO_DAYS, [reference]);
    assert.deepStrictEqual(plain(got.front[0].sessionIds), { g1: 'm1', g2: 't1' });
  }
  // A valid reference after an invalid one still counts.
  const got = bestWeeks([], TWO_DAYS, [{ g1: 'nope', g2: 't2' }, { g1: 'm2', g2: 't2' }]);
  assert.deepStrictEqual(plain(got.front[0].sessionIds), { g1: 'm2', g2: 't2' });
});

test('a reference worse than the front does not appear', () => {
  const got = bestWeeks([], TWO_DAYS, [{ g1: 'm1', g2: 't2' }]);
  assert.deepStrictEqual(plain(got.front), [
    { runMins: 60, days: 1, sessionIds: { g1: 'm1', g2: 't1' } },
  ]);
});

test('a reference with more clashes than the best does not appear', () => {
  const fixed = [{ day: 'Tuesday', startTime: '08:00', endTime: '09:00', weeks: null }];
  const got = bestWeeks(fixed, TWO_DAYS, [{ g1: 'm2', g2: 't2' }]);
  assert.strictEqual(got.clashes, 0);
  for (const entry of got.front) assert.notStrictEqual(entry.sessionIds.g1, 'm2');
  assertEntriesScore(got, fixed, TWO_DAYS);
});

// Group 'a' (x) and group 'B' (y), all on Monday. x1 then y1 join into a two
// hour run, x2 and y2 clash, and the other two arrangements tie at (60, 1).
// Plain comparison puts 'B' before 'a', so the first of the tie is (x2, y1);
// localeCompare would put 'a' first and pick (x1, y2).
const X_SITTINGS = [
  { sessionId: 'x1', day: 'Monday', startTime: '08:00', endTime: '09:00', weeks: null },
  { sessionId: 'x2', day: 'Monday', startTime: '15:00', endTime: '16:00', weeks: null },
];
const Y_SITTINGS = [
  { sessionId: 'y1', day: 'Monday', startTime: '09:00', endTime: '10:00', weeks: null },
  { sessionId: 'y2', day: 'Monday', startTime: '15:00', endTime: '16:00', weeks: null },
];

test('group ids are ordered as plain strings, not by localeCompare', () => {
  assert.ok('B' < 'a' && 'a'.localeCompare('B') < 0, 'the ids must disagree between the two orders');
  const groups = [
    { groupId: 'a', sessions: X_SITTINGS },
    { groupId: 'B', sessions: Y_SITTINGS },
  ];
  const got = bestWeeks([], groups);
  assert.strictEqual(got.clashes, 0);
  assert.deepStrictEqual(plain(got.front), [
    { runMins: 60, days: 1, sessionIds: { a: 'x2', B: 'y1' } },
  ]);
  // The order the groups arrive in does not matter.
  assert.deepStrictEqual(plain(bestWeeks([], [...groups].reverse())), plain(got));
});

test('the group with fewer candidates comes first whatever its id', () => {
  // A third y sitting puts 'B' after 'a', so the first of the tie is (x1, y2).
  const groups = [
    {
      groupId: 'B',
      sessions: [
        ...Y_SITTINGS,
        { sessionId: 'y3', day: 'Monday', startTime: '18:00', endTime: '19:00', weeks: null },
      ],
    },
    { groupId: 'a', sessions: X_SITTINGS },
  ];
  const got = bestWeeks([], groups);
  assert.deepStrictEqual(plain(got.front), [
    { runMins: 60, days: 1, sessionIds: { a: 'x1', B: 'y2' } },
  ]);
});

test('candidates are tried in timetable order, not the order given', () => {
  const groups = [
    { groupId: 'a', sessions: [...X_SITTINGS].reverse() },
    { groupId: 'B', sessions: [...Y_SITTINGS].reverse() },
  ];
  assert.deepStrictEqual(plain(bestWeeks([], groups).front[0].sessionIds), { a: 'x2', B: 'y1' });
});

const LARGE = FIXTURE.cases.find((c) => c.name === 'first-year-large');

/** A valid reference: the last sitting of every group, far from canonical. */
function lastSittings(groups) {
  return Object.fromEntries(
    groups.map((g) => [g.groupId, g.sessions[g.sessions.length - 1].sessionId])
  );
}

test('with a tiny budget the result is unproven and no worse than the references', () => {
  const groups = asAppGroups(LARGE.groups);
  const reference = lastSittings(groups);
  const refEvents = eventsOf(LARGE.fixed, groups, reference);
  const refClashes = findConflicts(refEvents).length;
  const refQuality = weekQuality(refEvents);
  for (const budget of [1, 3, 5, 50]) {
    const got = bestWeeks(LARGE.fixed, groups, [reference], budget);
    assert.strictEqual(got.proven, false);
    assert.ok(got.nodes <= budget, `${got.nodes} nodes on a budget of ${budget}`);
    assert.ok(got.front.length >= 1);
    assert.ok(got.clashes <= refClashes);
    if (got.clashes === refClashes) {
      assert.ok(
        got.front.some((e) => e.runMins <= refQuality.runMins && e.days <= refQuality.days),
        'the reference beats every entry'
      );
    }
    assertEntriesScore(got, LARGE.fixed, groups);
  }
});

test('with no references and a tiny budget the canonical-first arrangement is still finished', () => {
  // Documented in bestWeeks: the budget is not enforced until one complete
  // arrangement is held, so the result is never empty.
  const groups = asAppGroups(LARGE.groups);
  const got = bestWeeks(LARGE.fixed, groups, [], 1);
  assert.strictEqual(got.proven, false);
  assert.strictEqual(got.nodes, groups.length + 1);
  assert.strictEqual(got.front.length, 1);
  assertEntriesScore(got, LARGE.fixed, groups);
  const sessionsInTimetableOrder = api.get('sessionsInTimetableOrder');
  const first = Object.fromEntries(
    groups.map((g) => [g.groupId, sessionsInTimetableOrder(g.sessions)[0].sessionId])
  );
  assert.deepStrictEqual(plain(got.front[0].sessionIds), plain(first));
});

test('the budget is a count of nodes, and enough of them proves the answer', () => {
  const c = FIXTURE.cases.find((k) => k.name === 'comp-year-two-three-with-foun');
  const groups = asAppGroups(c.groups);
  const full = bestWeeks(c.fixed, groups);
  assert.strictEqual(full.proven, true);
  const exact = bestWeeks(c.fixed, groups, [], full.nodes);
  assert.deepStrictEqual(plain(exact), plain(full));
  const short = bestWeeks(c.fixed, groups, [], full.nodes - 1);
  assert.strictEqual(short.proven, false);
  assert.strictEqual(short.nodes, full.nodes - 1);
});

test('the same input twice gives the same output', () => {
  const groups = asAppGroups(LARGE.groups);
  const reference = lastSittings(groups);
  for (const budget of [undefined, 40]) {
    const a = bestWeeks(LARGE.fixed, groups, [reference], budget);
    const b = bestWeeks(LARGE.fixed, groups, [reference], budget);
    assert.deepStrictEqual(plain(a), plain(b));
  }
});

test('no events and no groups is one empty arrangement', () => {
  const got = bestWeeks([], []);
  assert.deepStrictEqual(plain(got), {
    clashes: 0,
    front: [{ runMins: 0, days: 0, sessionIds: {} }],
    proven: true,
    nodes: 1,
  });
  assert.deepStrictEqual(plain(bestWeeks([], [], [])), plain(got));
});

test('clashes among the fixed events count', () => {
  const fixed = [
    { day: 'Monday', startTime: '08:00', endTime: '10:00', weeks: null },
    { day: 'Monday', startTime: '09:00', endTime: '11:00', weeks: null },
  ];
  const got = bestWeeks(fixed, []);
  assert.strictEqual(got.clashes, 1);
  assert.deepStrictEqual(plain(got.front), [{ runMins: 180, days: 1, sessionIds: {} }]);
});

// The search scores weeks incrementally, one class of identical weeks at a
// time, and works clashes out once per pair. These small seeded instances are
// checked against a plain walk over every arrangement with weekQuality and
// findConflicts, including the arrangement that stands for each entry (spec
// 3.4). Half-hour times, gaps either side of an hour, weeks that differ, and
// weekless events are what the shortcuts could get wrong.
function randomInstance(random) {
  const days = ['Monday', 'Tuesday', 'Wednesday'];
  const clock = (mins) =>
    `${String(Math.floor(mins / 60)).padStart(2, '0')}:${String(mins % 60).padStart(2, '0')}`;
  let nextId = 1;
  const event = () => {
    const start = 480 + 30 * Math.floor(random() * 20);
    const kind = random();
    let weeks = null;
    if (kind < 0.15) weeks = [];
    else if (kind > 0.3) weeks = [1, 2, 3, 4, 5, 6].filter(() => random() < 0.6);
    return {
      sessionId: nextId++,
      day: days[Math.floor(random() * days.length)],
      startTime: clock(start),
      endTime: clock(start + 30 * (1 + Math.floor(random() * 5))),
      weeks,
    };
  };
  const fixed = Array.from({ length: Math.floor(random() * 3) }, event);
  const ids = ['a', 'B', 'c', 'D', 'e'];
  const groups = Array.from({ length: 1 + Math.floor(random() * 5) }, (_, i) => ({
    groupId: `${ids[i]}${Math.floor(random() * 3)}`,
    sessions: Array.from({ length: 1 + Math.floor(random() * 4) }, event),
  }));
  return { fixed, groups };
}

/** Every arrangement in canonical order (spec 3.4), with its score. */
function everyArrangement(fixed, groups) {
  const sessionsInTimetableOrder = api.get('sessionsInTimetableOrder');
  const ordered = groups
    .map((g) => ({ groupId: g.groupId, sessions: sessionsInTimetableOrder(g.sessions) }))
    .sort(
      (a, b) =>
        a.sessions.length - b.sessions.length ||
        (a.groupId < b.groupId ? -1 : a.groupId > b.groupId ? 1 : 0)
    );
  const out = [];
  const chosen = [];
  (function walk(i) {
    if (i === ordered.length) {
      const events = [...fixed, ...chosen.map((c) => c.session)];
      const q = weekQuality(events);
      const sessionIds = {};
      for (const c of chosen) sessionIds[c.groupId] = c.session.sessionId;
      out.push({ clashes: findConflicts(events).length, runMins: q.runMins, days: q.days, sessionIds });
      return;
    }
    for (const session of ordered[i].sessions) {
      chosen.push({ groupId: ordered[i].groupId, session });
      walk(i + 1);
      chosen.pop();
    }
  })(0);
  return out;
}

/** sessionIds with its keys in one order, since the two sides list them differently. */
function sortedIds(entry) {
  return { ...entry, sessionIds: Object.entries(entry.sessionIds).sort() };
}

test('bestWeeks agrees with a walk over every arrangement on seeded random instances', () => {
  const random = seeded(6925);
  let checked = 0;
  let multiEntry = 0;
  let referenceWon = 0;
  for (let trial = 0; trial < 300; trial++) {
    const { fixed, groups } = randomInstance(random);
    // Two groups drawn with one id would be one group to the app.
    if (new Set(groups.map((g) => g.groupId)).size < groups.length) continue;
    const all = everyArrangement(fixed, groups);
    const references = [];
    if (random() < 0.5) references.push(all[Math.floor(random() * all.length)].sessionIds);
    const got = bestWeeks(fixed, groups, references);
    assert.strictEqual(got.proven, true);

    const clashes = Math.min(...all.map((a) => a.clashes));
    const best = all.filter((a) => a.clashes === clashes);
    const expected = frontOf(best.map((a) => [a.runMins, a.days])).map(({ runMins, days }) => {
      const reaches = (a) => a.clashes === clashes && a.runMins === runMins && a.days === days;
      const fromReference = references
        .map((ids) => all.find((a) => JSON.stringify(a.sessionIds) === JSON.stringify(ids)))
        .find(reaches);
      if (fromReference) referenceWon += 1;
      return { runMins, days, sessionIds: (fromReference || best.find(reaches)).sessionIds };
    });
    if (expected.length > 1) multiEntry += 1;
    assert.strictEqual(got.clashes, clashes, `trial ${trial}`);
    assert.deepStrictEqual(plain(got.front).map(sortedIds), plain(expected).map(sortedIds), `trial ${trial}`);
    checked += 1;
  }
  // Without these the instances would be too easy to say much.
  assert.ok(checked > 150, `only ${checked} instances checked`);
  assert.ok(multiEntry > 10, `only ${multiEntry} instances had a front of two or more`);
  assert.ok(referenceWon > 10, `a reference stood for an entry only ${referenceWon} times`);
});

test('the fixture is current', () => {
  const rebuilt = plain(buildInstances());
  const committed = FIXTURE.cases.map(({ arrangements, expected, ...instance }) => instance);
  assert.deepStrictEqual(rebuilt.map((i) => i.name), committed.map((i) => i.name));
  for (let i = 0; i < committed.length; i++) {
    assert.deepStrictEqual(rebuilt[i], committed[i], `${committed[i].name} differs`);
  }
});

// ---- preferences: days to keep free and what counts as a break ----

/** No free days and the one-hour break: the model without preferences. */
const DEFAULT_PREFS = { freeDays: [], breakMins: 60 };

/** How many of the chosen sittings fall on a free day. Fixed events never count. */
function blockedOf(chosen, freeDays) {
  return chosen.filter((s) => freeDays.includes(s.day)).length;
}

test('a 2-hour break joins classes an hour apart and not two hours apart', () => {
  const hourApart = [ev('Monday', '08:00', '10:00'), ev('Monday', '11:00', '13:00')];
  const twoApart = [ev('Monday', '08:00', '10:00'), ev('Monday', '12:00', '14:00')];
  const quality = (events, breakMins) => plain(weekQuality(events, breakMins));
  assert.deepStrictEqual(quality(hourApart, 120), { runMins: 300, days: 1 });
  assert.deepStrictEqual(quality(twoApart, 120), { runMins: 120, days: 1 });
  // A 90-minute gap is under two hours and joins; with one hour it does not.
  const ninety = [ev('Monday', '08:00', '09:30'), ev('Monday', '11:00', '12:00')];
  assert.deepStrictEqual(quality(ninety, 120), { runMins: 240, days: 1 });
  assert.deepStrictEqual(quality(ninety, 60), { runMins: 90, days: 1 });
  // Left out, the break is the hour it always was.
  assert.deepStrictEqual(quality(hourApart), quality(hourApart, RUN_BREAK_MINS));
  assert.deepStrictEqual(quality(hourApart), { runMins: 120, days: 1 });
});

/** C*, B* and the front over every arrangement, scored with weekQuality. */
function bruteForceWith(c, prefs) {
  let best = Infinity;
  let bestBlocked = Infinity;
  let pairs = [];
  let seen = 0;
  const chosen = [];
  function walk(i) {
    if (i === c.groups.length) {
      seen++;
      const events = [...c.fixed, ...chosen];
      const clashes = countClashes(events);
      const blocked = blockedOf(chosen, prefs.freeDays);
      if (clashes > best || (clashes === best && blocked > bestBlocked)) return;
      if (clashes < best || blocked < bestBlocked) {
        best = clashes;
        bestBlocked = blocked;
        pairs = [];
      }
      const q = weekQuality(events, prefs.breakMins);
      pairs.push([q.runMins, q.days]);
      return;
    }
    for (const sitting of c.groups[i].sittings) {
      chosen.push(sitting);
      walk(i + 1);
      chosen.pop();
    }
  }
  walk(0);
  return { clashes: best, blocked: bestBlocked, front: frontOf(pairs), seen };
}

for (const c of FIXTURE.cases) {
  if (!c.preferences || c.arrangements > MAX_ARRANGEMENTS) continue;
  test(`weekQuality and the free-day count agree with the fixture: ${c.name}`, () => {
    const got = bruteForceWith(c, c.preferences);
    assert.strictEqual(got.seen, c.arrangements);
    assert.strictEqual(got.clashes, c.expected.clashes);
    assert.strictEqual(got.blocked, c.expected.blocked);
    assert.deepStrictEqual(plain(got.front), plain(c.expected.front));
  });
}

test('every case in the fixture states B*, and it is 0 wherever no day is free', () => {
  for (const c of FIXTURE.cases) {
    assert.strictEqual(typeof c.expected.blocked, 'number', c.name);
    if (!c.preferences || c.preferences.freeDays.length === 0) {
      assert.strictEqual(c.expected.blocked, 0, c.name);
    }
  }
});

/** Each entry's arrangement scores what it claims, with the preferences. */
function assertEntriesScoreWith(result, fixed, groups, prefs) {
  for (const entry of result.front) {
    const events = eventsOf(fixed, groups, entry.sessionIds);
    assert.strictEqual(findConflicts(events).length, result.clashes);
    assert.strictEqual(blockedOf(events.slice(fixed.length), prefs.freeDays), result.blocked);
    const q = weekQuality(events, prefs.breakMins);
    assert.strictEqual(q.runMins, entry.runMins);
    assert.strictEqual(q.days, entry.days);
  }
}

for (const c of FIXTURE.cases) {
  test(`bestWeeks matches the fixture with its preferences: ${c.name}`, () => {
    const prefs = c.preferences || DEFAULT_PREFS;
    const groups = asAppGroups(c.groups);
    const got = bestWeeks(c.fixed, groups, [], undefined, prefs);
    assert.strictEqual(got.proven, true);
    assert.strictEqual(got.clashes, c.expected.clashes);
    assert.strictEqual(got.blocked, c.expected.blocked);
    assert.deepStrictEqual(pairsOf(got), plain(c.expected.front));
    assertEntriesScoreWith(got, c.fixed, groups, prefs);
  });
}

// Nodes each case without preferences took before preferences existed,
// recorded from the solver as it was then. The search with nothing to prefer
// has to be the same search, not merely reach the same answer.
const NODES_WITHOUT_PREFERENCES = {
  'one-arrangement': 4,
  'comp-year-two-three': 48,
  'comp-year-two-three-pinned-lecture': 54,
  'comp-year-two-three-with-foun': 268,
  'first-year-large': 760,
  'agbu-weeks-differ': 18,
  'agbu-with-biol': 67,
  'split-lecture': 39,
  'unavoidable-clash': 31,
  'pinned-extra-sitting': 21,
  'biol-alternate-weeks': 1988,
  'psychology-and-foundation': 124,
  'sciences-mixed': 247,
  'paper-two-by-two': 7,
  'paper-forced-clash': 3,
  'gap-thirty-minutes': 3,
  'gap-sixty-minutes': 3,
  'uploaded-no-weeks': 7,
  'uploaded-beside-dated': 3,
};

test('without preferences every original case takes the nodes it always took', () => {
  const original = FIXTURE.cases.filter((c) => !c.preferences);
  assert.deepStrictEqual(original.map((c) => c.name), Object.keys(NODES_WITHOUT_PREFERENCES));
  for (const c of original) {
    const groups = asAppGroups(c.groups);
    const omitted = bestWeeks(c.fixed, groups);
    assert.strictEqual(omitted.nodes, NODES_WITHOUT_PREFERENCES[c.name], c.name);
    assert.ok(!('blocked' in omitted), `${c.name}: blocked is only reported when preferences are given`);
    // The default preferences given outright are the same search too.
    const given = bestWeeks(c.fixed, groups, [], undefined, DEFAULT_PREFS);
    const { blocked, ...rest } = plain(given);
    assert.strictEqual(blocked, 0, c.name);
    assert.deepStrictEqual(rest, plain(omitted), c.name);
  }
});

// Nodes each case with preferences takes. A search that stopped pruning on
// classes on free days would still find the answers above, only by visiting
// more partial arrangements, so the counts are pinned to catch that.
const NODES_WITH_PREFERENCES = {
  'sciences-mixed-monday-friday-free': 313,
  'comp-year-two-three-tuesday-free': 100,
  'comp-year-two-three-monday-friday-free': 76,
  'comp-year-two-three-pinned-lecture-wednesday-free': 34,
  'comp-year-two-three-two-hour-break': 60,
  'agbu-with-biol-both-choices': 117,
  'paper-clash-free-on-free-day': 5,
  'gap-ninety-two-hour-break': 4,
};

test('with preferences every case takes the nodes it was measured at', () => {
  const withPrefs = FIXTURE.cases.filter((c) => c.preferences);
  assert.deepStrictEqual(withPrefs.map((c) => c.name), Object.keys(NODES_WITH_PREFERENCES));
  for (const c of withPrefs) {
    const got = bestWeeks(c.fixed, asAppGroups(c.groups), [], undefined, c.preferences);
    assert.strictEqual(got.nodes, NODES_WITH_PREFERENCES[c.name], c.name);
  }
});

test('a free day never raises clashes: the only clash-free sitting is taken though its day is free', () => {
  const c = FIXTURE.cases.find((k) => k.name === 'paper-clash-free-on-free-day');
  const groups = asAppGroups(c.groups);
  const got = bestWeeks(c.fixed, groups, [], undefined, c.preferences);
  const without = bestWeeks(c.fixed, groups);
  assert.strictEqual(got.clashes, 0);
  assert.strictEqual(got.clashes, without.clashes);
  assert.strictEqual(got.blocked, 1);
  // The Monday lab, on the free day, rather than the Tuesday one that clashes.
  assert.deepStrictEqual(plain(got.front), [
    { runMins: 120, days: 3, sessionIds: { 'HAND 0006|Lab|all': 61, 'HAND 0006|Tutorial|all': 64 } },
  ]);
});

test('a reference with more classes on free days than the best does not appear', () => {
  // m2 then t2 ties with m1 then t1 without preferences, and as the reference
  // would stand for the entry. A free Tuesday puts both its classes on a
  // free day, so the Monday week is the only one left.
  const got = bestWeeks([], TWO_DAYS, [{ g1: 'm2', g2: 't2' }], undefined, {
    freeDays: ['Tuesday'],
    breakMins: 60,
  });
  assert.strictEqual(got.blocked, 0);
  assert.deepStrictEqual(plain(got.front), [
    { runMins: 60, days: 1, sessionIds: { g1: 'm1', g2: 't1' } },
  ]);
});

test('preferences that are missing or malformed mean the defaults', () => {
  const c = FIXTURE.cases.find((k) => k.name === 'comp-year-two-three');
  const groups = asAppGroups(c.groups);
  const expected = plain(bestWeeks(c.fixed, groups, [], undefined, DEFAULT_PREFS));
  for (const prefs of [{}, { freeDays: 'Monday' }, { breakMins: -5 }, { breakMins: '120' }, { freeDays: null, breakMins: null }]) {
    assert.deepStrictEqual(plain(bestWeeks(c.fixed, groups, [], undefined, prefs)), expected, JSON.stringify(prefs));
  }
});

/** Every arrangement in canonical order, scored with the preferences. */
function everyArrangementWith(fixed, groups, prefs) {
  const sessionsInTimetableOrder = api.get('sessionsInTimetableOrder');
  const ordered = groups
    .map((g) => ({ groupId: g.groupId, sessions: sessionsInTimetableOrder(g.sessions) }))
    .sort(
      (a, b) =>
        a.sessions.length - b.sessions.length ||
        (a.groupId < b.groupId ? -1 : a.groupId > b.groupId ? 1 : 0)
    );
  const out = [];
  const chosen = [];
  (function walk(i) {
    if (i === ordered.length) {
      const sessions = chosen.map((c) => c.session);
      const events = [...fixed, ...sessions];
      const q = weekQuality(events, prefs.breakMins);
      const sessionIds = {};
      for (const c of chosen) sessionIds[c.groupId] = c.session.sessionId;
      out.push({
        clashes: findConflicts(events).length,
        blocked: blockedOf(sessions, prefs.freeDays),
        runMins: q.runMins,
        days: q.days,
        sessionIds,
      });
      return;
    }
    for (const session of ordered[i].sessions) {
      chosen.push({ groupId: ordered[i].groupId, session });
      walk(i + 1);
      chosen.pop();
    }
  })(0);
  return out;
}

test('bestWeeks agrees with a walk over every arrangement on seeded random instances with preferences', () => {
  const random = seeded(14692);
  let checked = 0;
  let blockedSome = 0;
  let multiEntry = 0;
  let referenceWon = 0;
  for (let trial = 0; trial < 300; trial++) {
    const { fixed, groups } = randomInstance(random);
    if (new Set(groups.map((g) => g.groupId)).size < groups.length) continue;
    const prefs = {
      freeDays: ['Monday', 'Tuesday', 'Wednesday'].filter(() => random() < 0.4),
      breakMins: random() < 0.5 ? 60 : 120,
    };
    const all = everyArrangementWith(fixed, groups, prefs);
    const references = [];
    if (random() < 0.5) references.push(all[Math.floor(random() * all.length)].sessionIds);
    const got = bestWeeks(fixed, groups, references, undefined, prefs);
    assert.strictEqual(got.proven, true);

    const clashes = Math.min(...all.map((a) => a.clashes));
    const blocked = Math.min(...all.filter((a) => a.clashes === clashes).map((a) => a.blocked));
    const best = all.filter((a) => a.clashes === clashes && a.blocked === blocked);
    const expected = frontOf(best.map((a) => [a.runMins, a.days])).map(({ runMins, days }) => {
      const reaches = (a) =>
        a.clashes === clashes && a.blocked === blocked && a.runMins === runMins && a.days === days;
      const fromReference = references
        .map((ids) => all.find((a) => JSON.stringify(a.sessionIds) === JSON.stringify(ids)))
        .find(reaches);
      if (fromReference) referenceWon += 1;
      return { runMins, days, sessionIds: (fromReference || best.find(reaches)).sessionIds };
    });
    if (expected.length > 1) multiEntry += 1;
    if (blocked > 0) blockedSome += 1;
    assert.strictEqual(got.clashes, clashes, `trial ${trial}`);
    assert.strictEqual(got.blocked, blocked, `trial ${trial}`);
    assert.deepStrictEqual(plain(got.front).map(sortedIds), plain(expected).map(sortedIds), `trial ${trial}`);
    checked += 1;
  }
  assert.ok(checked > 150, `only ${checked} instances checked`);
  assert.ok(blockedSome > 10, `only ${blockedSome} instances kept a class on a free day`);
  assert.ok(multiEntry > 10, `only ${multiEntry} instances had a front of two or more`);
  assert.ok(referenceWon > 10, `a reference stood for an entry only ${referenceWon} times`);
});

// ---- placeCoursesBest: the default pick around what is already placed ----

// Read lazily, like bestWeeks, so these fail one by one before it exists.
function placeCoursesBest(...args) {
  return api.get('placeCoursesBest')(...args);
}

/** mulberry32: a small seeded generator, so a failing load can be replayed. */
function seeded(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function shuffled(items, random) {
  const out = [...items];
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(random() * (i + 1));
    [out[i], out[j]] = [out[j], out[i]];
  }
  return out;
}

/** Course groups and an index over them, built the way the app builds them. */
function loadOf(codes) {
  const perCourse = codes.map((code) => {
    const found = warehouse.courses.find((c) => c.code === code);
    assert.ok(found, `no fixture for ${code}`);
    return {
      courseKey: code,
      groups: weeklyOptionGroups({ courseKey: code, sessions: found.sessions }),
    };
  });
  return { perCourse, index: indexGroups(perCourse.flatMap((c) => c.groups)) };
}

/** [clashes, runMins, days] of a set of placements, scored independently. */
function scoreOf(placements, index) {
  const events = eventsFor(placements, index);
  const q = weekQuality(events);
  return [findConflicts(events).length, q.runMins, q.days];
}

/** Negative when a is the better week: clashes, then run, then days. */
function compareScores(a, b) {
  for (let i = 0; i < 3; i++) {
    if (a[i] !== b[i]) return a[i] - b[i];
  }
  return 0;
}

const LOAD_COUNT = 200;
const COURSE_CODES = warehouse.courses.map((c) => c.code);

let _loads = null;

/** Two hundred seeded loads, each placed both ways, computed once. */
function randomLoads() {
  if (_loads) return _loads;
  _loads = [];
  for (let seed = 1; seed <= LOAD_COUNT; seed++) {
    const random = seeded(seed);
    const size = 4 + Math.floor(random() * 3);
    const codes = shuffled(COURSE_CODES, random).slice(0, size);
    const { perCourse, index } = loadOf(codes);
    const base = placeCourses([], perCourse, index);
    const started = process.hrtime.bigint();
    const best = placeCoursesBest([], perCourse, index);
    const ms = Number(process.hrtime.bigint() - started) / 1e6;
    _loads.push({ seed, codes, perCourse, index, base, best, ms });
  }
  return _loads;
}

test('placeCoursesBest is never worse than placeCourses on 200 seeded loads', () => {
  let better = 0;
  let unproven = 0;
  for (const load of randomLoads()) {
    const was = scoreOf(load.base.placements, load.index);
    const now = scoreOf(load.best.placements, load.index);
    const verdict = compareScores(now, was);
    assert.ok(verdict <= 0, `seed ${load.seed} (${load.codes}): ${was} became ${now}`);
    if (verdict < 0) better += 1;
    if (!load.best.summary.proven) unproven += 1;
  }
  // Without this the test would pass if placeCoursesBest only returned
  // placeCourses's answer.
  assert.ok(better > 0, 'no load was strictly better, so the test proves nothing');
  if (process.env.WEEK_OPTIMISER_TIMINGS) {
    const slowest = [...randomLoads()].sort((a, b) => b.ms - a.ms).slice(0, 5);
    console.log(
      `${better} of ${LOAD_COUNT} loads strictly better, ${unproven} unproven\n` +
        slowest.map((l) => `seed ${l.seed}: ${l.ms.toFixed(0)} ms (${l.codes.join(', ')})`).join('\n')
    );
  }
});

test('the quality in the summary is a rescoring of the returned placements', () => {
  for (const load of randomLoads()) {
    const [clashes, runMins, days] = scoreOf(load.best.placements, load.index);
    const { summary } = load.best;
    assert.strictEqual(summary.quality.runMins, runMins, `seed ${load.seed}`);
    assert.strictEqual(summary.quality.days, days, `seed ${load.seed}`);
    assert.strictEqual(summary.conflictsAfter, clashes, `seed ${load.seed}`);
  }
});

test('clashing on each placed entry agrees with a recount', () => {
  for (const load of randomLoads()) {
    const clashing = new Set();
    for (const c of findConflicts(eventsFor(load.best.placements, load.index))) {
      clashing.add(c.a.groupId);
      clashing.add(c.b.groupId);
    }
    for (const p of load.best.placed) {
      assert.strictEqual(p.clashing, clashing.has(p.groupId), `seed ${load.seed} ${p.groupId}`);
      const shown = load.best.placements.find((q) => q.groupId === p.groupId);
      assert.strictEqual(p.selectedSessionId, shown.selectedSessionId);
    }
  }
});

test('the options are the front in order and the first is the answer', () => {
  for (const load of randomLoads()) {
    const { options } = load.best.summary;
    assert.ok(options.length >= 1 && options.length <= 7, `seed ${load.seed}`);
    assert.deepStrictEqual(plain(options[0].placements), plain(load.best.placements));
    for (let i = 0; i < options.length; i++) {
      const [clashes, runMins, days] = scoreOf(options[i].placements, load.index);
      assert.strictEqual(clashes, load.best.summary.conflictsAfter, `seed ${load.seed} option ${i}`);
      assert.strictEqual(options[i].runMins, runMins);
      assert.strictEqual(options[i].days, days);
      if (i > 0) assert.ok(options[i].runMins > options[i - 1].runMins);
    }
  }
});

test('every field placeCourses returns is still there', () => {
  for (const load of randomLoads()) {
    const { base, best } = load;
    for (const key of Object.keys(base)) assert.ok(key in best, `top level ${key}`);
    for (const key of Object.keys(base.summary)) assert.ok(key in best.summary, `summary ${key}`);
    for (const key of ['quality', 'proven', 'options']) assert.ok(key in best.summary, key);
    assert.strictEqual(best.placed.length, base.placed.length);
    best.placed.forEach((p, i) => {
      for (const key of Object.keys(base.placed[i])) assert.ok(key in p, `placed ${key}`);
      assert.strictEqual(p.groupId, base.placed[i].groupId);
      assert.strictEqual(p.options, base.placed[i].options);
    });
    for (const key of ['courses', 'groups', 'conflictsBefore', 'repairAttempts', 'repairCapped']) {
      assert.strictEqual(best.summary[key], base.summary[key], key);
    }
    assert.strictEqual(best.placements.length, base.placements.length);
    best.placements.forEach((p, i) => {
      assert.strictEqual(p.groupId, base.placements[i].groupId, 'same order');
      assert.strictEqual(p.pinned, base.placements[i].pinned);
      assert.strictEqual(p.courseKey, base.placements[i].courseKey);
    });
  }
});

test('unavoidable names the lone sittings that clash in the final week', () => {
  for (const load of randomLoads()) {
    const { placed, summary } = load.best;
    for (const p of placed) {
      assert.strictEqual(p.unavoidable, p.clashing && p.options === 1, `seed ${load.seed}`);
    }
    assert.deepStrictEqual(
      plain(summary.unavoidable),
      plain(placed.filter((p) => p.unavoidable).map((p) => p.groupId))
    );
  }
});

test('when placeCourses already has the default pick its placements come back as they were', () => {
  let same = 0;
  for (const load of randomLoads()) {
    const was = scoreOf(load.base.placements, load.index);
    const now = scoreOf(load.best.placements, load.index);
    if (compareScores(was, now) !== 0) continue;
    same += 1;
    assert.deepStrictEqual(plain(load.best.placements), plain(load.base.placements), `seed ${load.seed}`);
  }
  assert.ok(same > 0, 'no load kept the placeCourses answer');
});

test('the same courses in another order give identical placements', () => {
  for (const load of randomLoads().slice(0, 60)) {
    const random = seeded(load.seed * 7919);
    const again = placeCoursesBest([], shuffled(load.perCourse, random), load.index);
    assert.deepStrictEqual(plain(again.placements), plain(load.best.placements), `seed ${load.seed}`);
    assert.deepStrictEqual(plain(again.summary.options), plain(load.best.summary.options));
  }
});

test('placed in two steps, what the first step placed does not move', () => {
  let checked = 0;
  for (const load of randomLoads().slice(0, 80)) {
    const random = seeded(load.seed * 104729);
    const courses = shuffled(load.perCourse, random);
    const split = 1 + Math.floor(random() * (courses.length - 1));
    const first = placeCoursesBest([], courses.slice(0, split), load.index);
    // Some of the first step is pinned, as a student's own choices would be.
    const existing = first.placements.map((p, i) => (i % 3 === 0 ? { ...p, pinned: true } : p));
    const before = plain(existing);
    const second = placeCoursesBest(existing, courses.slice(split), load.index);
    assert.deepStrictEqual(plain(second.placements.slice(0, before.length)), before, `seed ${load.seed}`);
    assert.strictEqual(second.placements.length, existing.length + second.placed.length);
    for (const option of second.summary.options) {
      assert.deepStrictEqual(plain(option.placements.slice(0, before.length)), before);
    }
    const [clashes, runMins, days] = scoreOf(second.placements, load.index);
    assert.strictEqual(second.summary.conflictsAfter, clashes);
    assert.strictEqual(second.summary.quality.runMins, runMins);
    assert.strictEqual(second.summary.quality.days, days);
    checked += 1;
  }
  assert.ok(checked > 0);
});

test('nothing to place returns what placeCourses returns, with the quality of what is there', () => {
  const { perCourse, index } = loadOf(['COMP 1601', 'MATH 1115']);
  const existing = placeCourses([], perCourse, index).placements;
  for (const start of [[], existing]) {
    const base = placeCourses(start, [], index);
    const got = placeCoursesBest(start, [], index);
    assert.deepStrictEqual(plain(got.placements), plain(base.placements));
    assert.deepStrictEqual(plain(got.placed), []);
    const { quality, proven, options, ...rest } = got.summary;
    assert.deepStrictEqual(plain(rest), plain(base.summary));
    const [, runMins, days] = scoreOf(start, index);
    assert.deepStrictEqual(plain(quality), { runMins, days });
    assert.strictEqual(proven, true);
    assert.deepStrictEqual(plain(options), [{ runMins, days, placements: plain(start) }]);
  }
});

test('a group with no sittings is skipped and does not stop the rest', () => {
  const { perCourse, index } = loadOf(['COMP 1601']);
  const empty = {
    courseKey: 'X',
    groups: [{ groupId: 'X|Lecture|all', courseKey: 'X', type: 'Lecture', sessions: [] }],
  };
  const got = placeCoursesBest([], [...perCourse, empty], index);
  assert.strictEqual(got.placements.length, perCourse[0].groups.length);
});

// ---- placeCoursesBest's extra references, and comparing arrangements ----

/** An arrangement of the loose groups, as the plain object a reference is. */
function referenceOf(placements, looseAt) {
  const reference = {};
  for (const p of placements.slice(looseAt)) reference[p.groupId] = p.selectedSessionId;
  return reference;
}

/**
 * A load whose default pick shares its (clashes, run, days) with another
 * arrangement one move away, so a reference can be seen to win the tie.
 */
function tiedLoad() {
  for (const load of randomLoads()) {
    const placements = load.best.placements;
    const target = scoreOf(placements, load.index);
    for (let i = 0; i < placements.length; i++) {
      const group = load.index.get(placements[i].groupId);
      for (const session of group.sessions) {
        if (session.sessionId === placements[i].selectedSessionId) continue;
        const tried = placements.map((p, j) =>
          j === i ? { ...p, selectedSessionId: session.sessionId } : p);
        if (compareScores(scoreOf(tried, load.index), target) === 0) {
          return { load, tied: tried };
        }
      }
    }
  }
  return null;
}

test('placeCoursesBest gives the same answer with no extra references as with three arguments', () => {
  for (const load of randomLoads().slice(0, 20)) {
    const three = placeCoursesBest([], load.perCourse, load.index);
    for (const extra of [undefined, null, []]) {
      const four = placeCoursesBest([], load.perCourse, load.index, extra);
      assert.deepStrictEqual(plain(four), plain(three), `seed ${load.seed}`);
    }
  }
});

test('an extra reference that reaches the first entry is the week returned', () => {
  const found = tiedLoad();
  assert.ok(found, 'no load has a tie one move away');
  const { load, tied } = found;
  const got = placeCoursesBest([], load.perCourse, load.index, [referenceOf(tied, 0)]);
  assert.ok(sameArrangement(got.placements, tied));
  assert.ok(!sameArrangement(got.placements, load.best.placements));
});

test('extra references are tried in the order given, before placeCourses', () => {
  const found = tiedLoad();
  assert.ok(found);
  const { load, tied } = found;
  const first = referenceOf(load.best.placements, 0);
  const second = referenceOf(tied, 0);
  const got = placeCoursesBest([], load.perCourse, load.index, [second, first]);
  assert.ok(sameArrangement(got.placements, tied));
  const back = placeCoursesBest([], load.perCourse, load.index, [first, second]);
  assert.ok(sameArrangement(back.placements, load.best.placements));
});

test('an extra reference that names no valid week is ignored', () => {
  const load = randomLoads()[0];
  const got = placeCoursesBest([], load.perCourse, load.index, [{ nope: 'x' }, 'junk', null]);
  assert.deepStrictEqual(plain(got), plain(load.best));
});

function sameArrangement(a, b) {
  return api.get('sameArrangement')(a, b);
}

test('two arrangements are the same when group, session and pin match, in any order', () => {
  const a = [
    { courseKey: 'A', groupId: 'A|Lab|all', selectedSessionId: 1, pinned: false },
    { courseKey: 'A', groupId: 'A|Lecture|all', selectedSessionId: 2, pinned: true },
  ];
  assert.equal(sameArrangement(a, [...a].reverse()), true);
  assert.equal(sameArrangement(a, a.map((p) => ({ ...p }))), true);
  // A missing pin is read as unpinned, as eventForPlacement reads it.
  assert.equal(sameArrangement(a, [{ ...a[0], pinned: undefined }, a[1]]), true);
  assert.equal(sameArrangement(a, [{ ...a[0], selectedSessionId: 3 }, a[1]]), false);
  assert.equal(sameArrangement(a, [{ ...a[0], pinned: true }, a[1]]), false);
  assert.equal(sameArrangement(a, [a[0]]), false);
  assert.equal(sameArrangement(a, [a[0], a[0]]), false);
  assert.equal(sameArrangement([], []), true);
});

// ---- placeCoursesBest with preferences ----

const MON_FRI_TWO_HOURS = { freeDays: ['Monday', 'Friday'], breakMins: 120 };

/** [clashes, blocked, runMins, days] of the new placements, with the preferences. */
function scoreWith(placements, looseAt, index, prefs) {
  const events = eventsFor(placements, index);
  const q = weekQuality(events, prefs.breakMins);
  const blocked = blockedOf(eventsFor(placements.slice(looseAt), index), prefs.freeDays);
  return [findConflicts(events).length, blocked, q.runMins, q.days];
}

test('placeCoursesBest with preferences omitted is the call it always was', () => {
  for (const load of randomLoads().slice(0, 20)) {
    for (const prefs of [undefined, null]) {
      const got = placeCoursesBest([], load.perCourse, load.index, undefined, prefs);
      assert.deepStrictEqual(plain(got), plain(load.best), `seed ${load.seed}`);
      assert.ok(!('blocked' in got.summary));
    }
  }
});

test('placeCoursesBest with preferences reports blocked, and every option rescores to its figures', () => {
  let blockedSome = 0;
  for (const load of randomLoads().slice(0, 60)) {
    const got = placeCoursesBest([], load.perCourse, load.index, undefined, MON_FRI_TWO_HOURS);
    const { summary } = got;
    const [clashes, blocked, runMins, days] = scoreWith(got.placements, 0, load.index, MON_FRI_TWO_HOURS);
    assert.strictEqual(summary.conflictsAfter, clashes, `seed ${load.seed}`);
    assert.strictEqual(summary.blocked, blocked, `seed ${load.seed}`);
    assert.deepStrictEqual(plain(summary.quality), { runMins, days }, `seed ${load.seed}`);
    if (blocked > 0) blockedSome += 1;
    assert.deepStrictEqual(plain(summary.options[0].placements), plain(got.placements));
    summary.options.forEach((option, i) => {
      const score = scoreWith(option.placements, 0, load.index, MON_FRI_TWO_HOURS);
      assert.deepStrictEqual(score, [clashes, option.blocked, option.runMins, option.days], `seed ${load.seed} option ${i}`);
      assert.strictEqual(option.blocked, summary.blocked);
    });
    // Never worse than placeCourses, now judged clashes, then free days, then
    // run, then days: the first option has the shortest run of the best.
    const was = scoreWith(load.base.placements, 0, load.index, MON_FRI_TWO_HOURS);
    const now = [clashes, blocked, runMins, days];
    const first = now.findIndex((x, i) => x !== was[i]);
    assert.ok(first < 0 || now[first] < was[first], `seed ${load.seed}: ${was} became ${now}`);
  }
  assert.ok(blockedSome > 0, 'no load kept a class on Monday or Friday, so blocked was never tested above 0');
});

test('placeCoursesBest with preferences leaves what is already placed alone, and counts only the new classes', () => {
  const { perCourse, index } = loadOf(['COMP 2601', 'COMP 2611', 'COMP 3607', 'COMP 3613']);
  const first = placeCoursesBest([], perCourse.slice(0, 2), index);
  const existing = first.placements.map((p) => ({ ...p, pinned: true }));
  const got = placeCoursesBest(existing, perCourse.slice(2), index, undefined, MON_FRI_TWO_HOURS);
  assert.deepStrictEqual(plain(got.placements.slice(0, existing.length)), plain(existing));
  const [, blocked] = scoreWith(got.placements, existing.length, index, MON_FRI_TWO_HOURS);
  assert.strictEqual(got.summary.blocked, blocked);
  // COMP 3607's lab only runs on Friday, so at least that one is on a free day.
  assert.ok(blocked >= 1);
});
