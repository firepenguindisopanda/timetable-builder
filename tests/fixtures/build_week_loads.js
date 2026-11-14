'use strict';

/**
 * Writes `week_loads.json`, the answers the week optimiser is checked against.
 *
 * Two solvers are meant to agree with this file: branch and bound in the
 * browser and an integer program in Julia (WEEK-OPTIMISER-SPEC.md, sections
 * 3.6 and 6). Neither can be trusted to check the other, so the answers here
 * come from a third route that is too plain to be wrong: every arrangement is
 * tried, with no pruning and no shared code. It is slow on purpose.
 *
 * Each case is written out in full, fixed events and loose groups with their
 * days, times and weeks, so a reader in another language needs nothing but
 * this file. The warehouse cases are grouped by the app's own
 * `weeklyOptionGroups`, loaded through the test harness, so the instances are
 * the ones a student's timetable would actually produce. A JS test rebuilds
 * them with `buildInstances` and fails if they no longer match, which is why
 * that step is exported apart from the brute force.
 *
 * Run by hand after changing the list of loads:
 *
 *   node tests/fixtures/build_week_loads.js
 */

const fs = require('node:fs');
const path = require('node:path');
const { load, course } = require('../js/harness.js');

/**
 * How long a break has to be before a run of class is over. Spec 3.2.
 *
 * Restated here rather than read from the app, because the point of this file
 * is to share nothing with the solver it checks.
 */
const RUN_BREAK_MINS = 60;

/**
 * The most arrangements one case may have.
 *
 * Every arrangement is scored, so a case past this would take minutes to
 * build, and spec 3.6 promises the Julia and browser checks a size they can
 * also afford.
 */
const MAX_ARRANGEMENTS = 5000000;

/** Where the answers are written. */
const OUTPUT = path.join(__dirname, 'week_loads.json');

const _app = load('calendar-utils.js', 'option-groups.js');
const _weeklyOptionGroups = _app.get('weeklyOptionGroups');
const _sessionsInTimetableOrder = _app.get('sessionsInTimetableOrder');
const _eventsCollide = _app.get('eventsCollide');

const ALL_WEEKS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12];

/**
 * Course loads taken from `warehouse_sessions.json`.
 *
 * `pins` mirror what `reoptimise()` in timetable-state.js does with a pinned
 * placement. A pinned `main` sitting is the group's only placement, so the
 * sitting becomes a fixed event and the group drops out. A pinned `extra` is a
 * second sitting the student added on top: it becomes a fixed event, and the
 * group stays loose without that sitting, so the first placement cannot land
 * on a session the student already attends.
 */
const WAREHOUSE_LOADS = [
  {
    name: 'one-arrangement',
    about: 'COMP 3607 with its lectures split: every group has a single sitting, so there is nothing to choose.',
    courses: ['COMP 3607'],
    overrides: { 'COMP 3607|Lecture': 'split' },
  },
  {
    name: 'comp-year-two-three',
    about: 'The four-course computing load from the spec, about 240 arrangements.',
    courses: ['COMP 2601', 'COMP 2611', 'COMP 3607', 'COMP 3613'],
  },
  {
    name: 'comp-year-two-three-pinned-lecture',
    about: 'comp-year-two-three with the COMP 2611 Wednesday 13:00 lecture pinned: the best week without the pin uses the Tuesday lecture, so the answer is worse.',
    courses: ['COMP 2601', 'COMP 2611', 'COMP 3607', 'COMP 3613'],
    pins: [{ sessionId: 19220, kind: 'main' }],
  },
  {
    name: 'comp-year-two-three-with-foun',
    about: 'The same four courses plus FOUN 1101, whose lectures run in week 1 only.',
    courses: ['COMP 2601', 'COMP 2611', 'COMP 3607', 'COMP 3613', 'FOUN 1101'],
  },
  {
    name: 'first-year-large',
    about: 'The largest load the brute force is asked to try, a little over three million arrangements.',
    courses: ['COMP 1601', 'COMP 1602', 'MATH 1115', 'FOUN 1101'],
  },
  {
    name: 'agbu-weeks-differ',
    about: 'AGBU 1005 lectures and tutorials share hours but not weeks, so they never clash.',
    courses: ['AGBU 1005'],
  },
  {
    name: 'agbu-with-biol',
    about: 'AGBU 1005 beside BIOL 2061, whose classes run every week.',
    courses: ['AGBU 1005', 'BIOL 2061'],
  },
  {
    name: 'split-lecture',
    about: 'COMP 1601 with its lectures split into one group per time, two of which are one choice because they overlap.',
    courses: ['COMP 1601', 'COMP 1602', 'COMP 2611'],
    overrides: { 'COMP 1601|Lecture': 'split' },
  },
  {
    name: 'unavoidable-clash',
    about: 'With COMP 1601 lectures split, its only Wednesday 12:00 lecture overlaps the only COMP 3613 lecture, Wednesday 11:00 to 13:00.',
    courses: ['COMP 1601', 'COMP 2601', 'COMP 3613'],
    overrides: { 'COMP 1601|Lecture': 'split' },
  },
  {
    name: 'pinned-extra-sitting',
    about: 'A second COMP 2601 tutorial the student pinned: it is fixed, and the tutorial group stays loose without it.',
    courses: ['COMP 2601', 'COMP 2611', 'COMP 3613'],
    pins: [{ sessionId: 19193, kind: 'extra' }],
  },
  {
    name: 'biol-alternate-weeks',
    about: 'BIOL 1262 runs in even weeks only, beside CHEM 2470 and COMP 3613 which run every week.',
    courses: ['BIOL 1262', 'CHEM 2470', 'COMP 3613'],
  },
  {
    name: 'psychology-and-foundation',
    about: 'Large tutorial menus: PSYC 1001, FOUN 1101 and WW101.',
    courses: ['PSYC 1001', 'FOUN 1101', 'WW101'],
  },
  {
    name: 'sciences-mixed',
    about: 'An ordinary three-course load across biology, chemistry and psychology.',
    courses: ['BIOL 2061', 'CHEM 2470', 'PSYC 1001'],
  },
];

/**
 * Cases written out by hand, where the warehouse has no example.
 *
 * Every warehouse class starts and ends on the hour, so a 30-minute gap has
 * to be made up, and no warehouse class lacks weeks the way an uploaded PDF
 * does. The first two are small enough to work on paper; the working is here
 * so that whoever reads a disagreement can check this file before the solver.
 *
 * paper-two-by-two. No fixed events. Lecture: L1 Mon 09:00-10:00, L2 Tue
 * 09:00-10:00. Tutorial: T1 Mon 10:00-11:00, T2 Mon 09:30-10:30. All week 1.
 *   L1+T1: no overlap (10:00 is not before 10:00). Mon 09:00-11:00 is one run
 *          of 120. One day. (120, 1), C = 0.
 *   L1+T2: 09:30 is before 10:00 and 09:00 before 10:30, so they clash. C = 1.
 *   L2+T1: Tue 60, Mon 60. (60, 2), C = 0.
 *   L2+T2: Tue 60, Mon 60. (60, 2), C = 0.
 * C* = 0. Neither (60, 2) nor (120, 1) beats the other, so the front is
 * [(60, 2), (120, 1)].
 *
 * paper-forced-clash. Fixed F Mon 10:00-12:00 in weeks 1 and 2. One group:
 * A Mon 11:00-12:00 in week 2, B Mon 09:00-10:30 in weeks 1 and 3. Weeks
 * considered are 1, 2 and 3.
 *   F+A: overlap, and both run in week 2, so C = 1. Week 1 is F alone, 120.
 *        Week 2 is F and A, which overlap and so are one run, 10:00-12:00,
 *        120. Week 3 is empty. (120, 1).
 *   F+B: overlap 10:00-10:30, both run in week 1, so C = 1. Week 1 is B then
 *        F, one run 09:00-12:00, 180. Week 2 is F, 120. Week 3 is B, 90.
 *        (180, 1).
 * C* = 1, and (120, 1) beats (180, 1), so the front is [(120, 1)].
 */
const HAND_BUILT = [
  {
    name: 'paper-two-by-two',
    about: 'Small enough to work on paper: two groups of two, one pair clashes, and the front has two entries.',
    fixed: [],
    groups: [
      {
        groupId: 'HAND 0001|Lecture|all',
        sittings: [
          _sitting(1, 'Monday', '09:00', '10:00', [1]),
          _sitting(2, 'Tuesday', '09:00', '10:00', [1]),
        ],
      },
      {
        groupId: 'HAND 0001|Tutorial|all',
        sittings: [
          _sitting(3, 'Monday', '09:30', '10:30', [1]),
          _sitting(4, 'Monday', '10:00', '11:00', [1]),
        ],
      },
    ],
  },
  {
    name: 'paper-forced-clash',
    about: 'Small enough to work on paper: every sitting clashes with the fixed class in some week, so the best week still has one clash.',
    fixed: [_fixed('HAND 0002 Lecture (pinned)', 'Monday', '10:00', '12:00', [1, 2])],
    groups: [
      {
        groupId: 'HAND 0002|Tutorial|all',
        sittings: [
          _sitting(11, 'Monday', '09:00', '10:30', [1, 3]),
          _sitting(12, 'Monday', '11:00', '12:00', [2]),
        ],
      },
    ],
  },
  {
    name: 'gap-thirty-minutes',
    about: 'A 30-minute gap does not end a run, so the Tuesday sitting makes one run of 150 minutes.',
    fixed: [_fixed('HAND 0003 Lecture (pinned)', 'Tuesday', '09:00', '10:00', ALL_WEEKS)],
    groups: [
      {
        groupId: 'HAND 0003|Tutorial|all',
        sittings: [
          _sitting(21, 'Tuesday', '10:30', '11:30', ALL_WEEKS),
          _sitting(22, 'Thursday', '10:30', '11:30', ALL_WEEKS),
        ],
      },
    ],
  },
  {
    name: 'gap-sixty-minutes',
    about: 'A 60-minute gap ends a run, so the Tuesday sitting makes two runs of 60 minutes on one day.',
    fixed: [_fixed('HAND 0004 Lecture (pinned)', 'Tuesday', '09:00', '10:00', ALL_WEEKS)],
    groups: [
      {
        groupId: 'HAND 0004|Tutorial|all',
        sittings: [
          _sitting(31, 'Tuesday', '11:00', '12:00', ALL_WEEKS),
          _sitting(32, 'Thursday', '11:00', '12:00', ALL_WEEKS),
        ],
      },
    ],
  },
  {
    name: 'uploaded-no-weeks',
    about: 'An uploaded PDF gives no weeks: every event is in one undated week, and every overlap is a clash.',
    fixed: [_fixed('UPLD 1000 Lecture (pinned)', 'Monday', '08:00', '10:00', null)],
    groups: [
      {
        groupId: 'UPLD 1000|Lab|all',
        sittings: [
          _sitting(41, 'Monday', '09:00', '10:00', null),
          _sitting(42, 'Wednesday', '13:00', '14:00', null),
        ],
      },
      {
        groupId: 'UPLD 1000|Tutorial|all',
        sittings: [
          _sitting(43, 'Monday', '11:00', '12:00', null),
          _sitting(44, 'Friday', '08:00', '09:00', null),
        ],
      },
    ],
  },
  {
    name: 'uploaded-beside-dated',
    about: 'An event with no weeks is present in every week another event names, so it meets a week-5 class.',
    fixed: [_fixed('UPLD 2000 Lecture (pinned)', 'Thursday', '10:00', '12:00', null)],
    groups: [
      {
        groupId: 'HAND 0005|Tutorial|all',
        sittings: [
          _sitting(51, 'Thursday', '12:30', '13:30', [5]),
          _sitting(52, 'Friday', '10:00', '11:00', [1, 2]),
        ],
      },
    ],
  },
];

function _sitting(sessionId, day, startTime, endTime, weeks) {
  return { sessionId, day, startTime, endTime, weeks };
}

function _fixed(label, day, startTime, endTime, weeks) {
  return { label, day, startTime, endTime, weeks };
}

/** Only the fields the model reads, in a fixed key order. */
function _asSitting(session) {
  return _sitting(
    session.sessionId,
    session.day,
    session.startTime,
    session.endTime,
    session.weeks == null ? null : [...session.weeks]
  );
}

/**
 * One warehouse load as an instance, grouped the way the app groups it.
 *
 * Pins are applied the way `reoptimise()` applies them, so a pinned case is
 * the instance Re-arrange would hand the solver.
 */
function _warehouseInstance(spec) {
  const fixed = [];
  const groups = [];
  const pins = new Map((spec.pins || []).map((p) => [p.sessionId, p.kind]));
  const used = new Set();

  for (const code of spec.courses) {
    const found = course(code);
    const loaded = { courseKey: code, title: found.title, sessions: found.sessions };
    for (const group of _weeklyOptionGroups(loaded, spec.overrides || {})) {
      const sessions = _sessionsInTimetableOrder(group.sessions);
      const pinned = sessions.filter((s) => pins.has(s.sessionId));
      for (const session of pinned) {
        const kind = pins.get(session.sessionId);
        used.add(session.sessionId);
        fixed.push(_fixed(
          `${code} ${group.type} ${session.sessionId} (${kind === 'extra' ? 'pinned extra' : 'pinned'})`,
          session.day,
          session.startTime,
          session.endTime,
          session.weeks == null ? null : [...session.weeks]
        ));
      }
      if (pinned.some((s) => pins.get(s.sessionId) === 'main')) continue;
      const loose = sessions.filter((s) => !pins.has(s.sessionId));
      // reoptimise() drops a group left with nothing to choose from.
      if (loose.length === 0) continue;
      groups.push({ groupId: group.groupId, sittings: loose.map(_asSitting) });
    }
  }

  for (const sessionId of pins.keys()) {
    if (!used.has(sessionId)) {
      throw new Error(`${spec.name}: pinned session ${sessionId} is not in the load`);
    }
  }
  return {
    name: spec.name,
    about: spec.about,
    source: 'warehouse',
    courses: [...spec.courses],
    fixed,
    groups,
  };
}

/**
 * Every instance, without answers. Spec 3.6 has a test rebuild these and
 * compare them with the committed file, so this must not depend on anything
 * the brute force computes. Each is already in the written shape, keys in
 * the written order, so a case minus `arrangements` and `expected` should
 * deep-equal its instance.
 */
function buildInstances() {
  const warehouse = WAREHOUSE_LOADS.map(_warehouseInstance);
  const hand = HAND_BUILT.map((spec) => ({
    name: spec.name,
    about: spec.about,
    source: 'hand-built',
    fixed: spec.fixed.map((e) => ({ ...e })),
    groups: spec.groups.map((g) => ({
      groupId: g.groupId,
      sittings: g.sittings.map((s) => ({ ...s })),
    })),
  }));
  const instances = [...warehouse, ...hand];

  const names = new Set();
  for (const instance of instances) {
    if (names.has(instance.name)) throw new Error(`duplicate case ${instance.name}`);
    names.add(instance.name);
    // The file promises sittings in timetable order; hand-typed groups could
    // break that without anyone noticing.
    for (const group of instance.groups) {
      const ordered = _sessionsInTimetableOrder(group.sittings);
      if (ordered.some((s, i) => s !== group.sittings[i])) {
        throw new Error(`${instance.name}: ${group.groupId} is not in timetable order`);
      }
    }
  }
  return instances;
}

/** Number of arrangements: the product of the group sizes. */
function countArrangements(instance) {
  return instance.groups.reduce((n, g) => n * g.sittings.length, 1);
}

// The scorer. Written from spec 3.2 directly and kept deliberately plain.

function _mins(time) {
  const match = /^(\d{2}):(\d{2})$/.exec(time);
  if (!match) throw new Error(`unexpected time ${time}`);
  return Number(match[1]) * 60 + Number(match[2]);
}

/**
 * Weeks as a set, or null when unknown.
 *
 * The app treats an empty list as unknown too (`sharedWeeks` in
 * calendar-utils.js), so this does the same rather than reading it as "never".
 */
function _weekSet(weeks) {
  if (weeks == null || weeks.length === 0) return null;
  return new Set(weeks);
}

function _plain(event) {
  return {
    day: event.day,
    start: _mins(event.startTime),
    end: _mins(event.endTime),
    weeks: _weekSet(event.weeks),
  };
}

/** Spec 3.2: same day, overlapping times, and a shared week or unknown weeks. */
function _collide(a, b) {
  if (a.day !== b.day) return false;
  if (!(a.start < b.end && b.start < a.end)) return false;
  if (a.weeks === null || b.weeks === null) return true;
  for (const w of a.weeks) {
    if (b.weeks.has(w)) return true;
  }
  return false;
}

/**
 * The weeks to score in: every week any event names. One undated week, shown
 * as null, when none does.
 */
function _weeksConsidered(events) {
  const named = new Set();
  for (const event of events) {
    if (event.weeks !== null) for (const w of event.weeks) named.add(w);
  }
  if (named.size === 0) return [null];
  return [...named].sort((a, b) => a - b);
}

function _inWeek(event, week) {
  return week === null || event.weeks === null || event.weeks.has(week);
}

/** Longest run and days with class in the worst week. Spec 3.2. */
function _runAndDays(events, weeks) {
  let runMins = 0;
  let days = 0;
  for (const week of weeks) {
    const byDay = new Map();
    for (const event of events) {
      if (!_inWeek(event, week)) continue;
      if (!byDay.has(event.day)) byDay.set(event.day, []);
      byDay.get(event.day).push(event);
    }
    days = Math.max(days, byDay.size);
    for (const dayEvents of byDay.values()) {
      dayEvents.sort((a, b) => a.start - b.start);
      let first = dayEvents[0].start;
      let reach = dayEvents[0].end;
      for (const event of dayEvents.slice(1)) {
        if (event.start - reach < RUN_BREAK_MINS) {
          reach = Math.max(reach, event.end);
        } else {
          runMins = Math.max(runMins, reach - first);
          first = event.start;
          reach = event.end;
        }
      }
      runMins = Math.max(runMins, reach - first);
    }
  }
  return { runMins, days };
}

/**
 * The (R, D) pairs no other pair matches or beats on both, sorted by R.
 *
 * Read over distinct pairs: two arrangements with the same pair do not knock
 * each other out.
 */
function _front(pairs) {
  const front = pairs.filter((p) => !pairs.some(
    (q) => q !== p && q.runMins <= p.runMins && q.days <= p.days
  ));
  return front.sort((a, b) => a.runMins - b.runMins);
}

/**
 * C* and the front, found by scoring every arrangement.
 *
 * Every pair this scores is also put to the app's `eventsCollide`, once per
 * distinct pair, and a disagreement stops the build: a fixture whose clash
 * rule differs from the site's would make both solvers wrong in the same way.
 */
function solveByBruteForce(instance) {
  const arrangements = countArrangements(instance);
  if (arrangements > MAX_ARRANGEMENTS) {
    throw new Error(
      `${instance.name}: ${arrangements} arrangements, more than ${MAX_ARRANGEMENTS}`
    );
  }

  // Every event the instance can produce, numbered so each pair is checked
  // against the app once however many arrangements contain it.
  const raw = [...instance.fixed];
  const index = instance.groups.map((g) => g.sittings.map((s) => raw.push(s) - 1));
  const plain = raw.map(_plain);
  const weeks = _weeksConsidered(plain);
  const checked = new Uint8Array(raw.length * raw.length);

  const choice = instance.groups.map(() => 0);
  const fixedIds = instance.fixed.map((_, i) => i);
  let best = Infinity;
  let pairs = new Map();

  for (let n = 0; n < arrangements; n++) {
    const ids = [...fixedIds, ...choice.map((c, g) => index[g][c])];

    let clashes = 0;
    for (let i = 0; i < ids.length; i++) {
      for (let j = i + 1; j < ids.length; j++) {
        const a = ids[i];
        const b = ids[j];
        const mine = _collide(plain[a], plain[b]);
        if (!checked[a * raw.length + b]) {
          if (mine !== _eventsCollide(raw[a], raw[b])) {
            throw new Error(
              `${instance.name}: clash rule disagrees with eventsCollide on ` +
              `${JSON.stringify(raw[a])} and ${JSON.stringify(raw[b])}`
            );
          }
          checked[a * raw.length + b] = 1;
        }
        if (mine) clashes++;
      }
    }

    if (clashes <= best) {
      if (clashes < best) {
        best = clashes;
        pairs = new Map();
      }
      const { runMins, days } = _runAndDays(ids.map((id) => plain[id]), weeks);
      pairs.set(`${runMins}|${days}`, { runMins, days });
    }

    // Odometer: the last group turns fastest.
    for (let g = choice.length - 1; g >= 0; g--) {
      choice[g]++;
      if (choice[g] < instance.groups[g].sittings.length) break;
      choice[g] = 0;
    }
  }

  return { arrangements, clashes: best, front: _front([...pairs.values()]) };
}

// Output. A hand-rolled writer, because JSON.stringify with an indent puts
// every week number on its own line and the file becomes unreadable.

function _inline(value) {
  if (Array.isArray(value)) return `[${value.map(_inline).join(', ')}]`;
  if (value !== null && typeof value === 'object') {
    const parts = Object.keys(value).map((k) => `${JSON.stringify(k)}: ${_inline(value[k])}`);
    return `{ ${parts.join(', ')} }`;
  }
  return JSON.stringify(value);
}

function _isLeaf(value) {
  if (value === null || typeof value !== 'object') return true;
  if (Array.isArray(value)) return value.every((v) => v === null || typeof v !== 'object');
  return Object.values(value).every(_isLeaf);
}

function _format(value, indent) {
  if (_isLeaf(value)) return _inline(value);
  const inner = indent + '  ';
  if (Array.isArray(value)) {
    return `[\n${value.map((v) => inner + _format(v, inner)).join(',\n')}\n${indent}]`;
  }
  const parts = Object.keys(value).map(
    (k) => `${inner}${JSON.stringify(k)}: ${_format(value[k], inner)}`
  );
  return `{\n${parts.join(',\n')}\n${indent}}`;
}

function _frontText(front) {
  return front.map((p) => `(${p.runMins}, ${p.days})`).join(' ');
}

function main() {
  const cases = [];
  for (const instance of buildInstances()) {
    const answer = solveByBruteForce(instance);
    cases.push({
      ...instance,
      arrangements: answer.arrangements,
      expected: { clashes: answer.clashes, front: answer.front },
    });
    console.log(
      `${instance.name}: ${answer.arrangements} arrangements, ` +
      `C* ${answer.clashes}, front ${_frontText(answer.front)}`
    );
  }
  fs.writeFileSync(OUTPUT, _format({ runBreakMins: RUN_BREAK_MINS, cases }, '') + '\n');
  console.log(`wrote ${cases.length} cases to ${path.relative(process.cwd(), OUTPUT)}`);
}

module.exports = { buildInstances, solveByBruteForce, countArrangements };

if (require.main === module) main();
