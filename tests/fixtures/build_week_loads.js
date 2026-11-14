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
 * this file. A case may also carry the student's `preferences`, the days to
 * keep free and the break that ends a run (spec 14), and every answer gives
 * `blocked`, the fewest chosen sittings on a free day. The warehouse cases are grouped by the app's own
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
 * The breaks a student may choose between, and the day names a free day may
 * take. Spec 14.1. A typing slip in a case should stop the build, not quietly
 * become a preference no student can set.
 */
const BREAK_CHOICES = [60, 120];
const DAY_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

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
  // Preferences (spec 14). Each of these is a load above with a student's
  // choices added, taken from the warehouse wherever it has an example of the
  // case: only the clash-free-only-on-a-free-day case and the half-hour gaps
  // are made up, below in HAND_BUILT.
  {
    name: 'sciences-mixed-monday-friday-free',
    about: 'sciences-mixed with Monday and Friday kept free: every group has a sitting from Tuesday to Thursday that keeps the same run and days, so the free days cost nothing.',
    courses: ['BIOL 2061', 'CHEM 2470', 'PSYC 1001'],
    preferences: { freeDays: ['Monday', 'Friday'], breakMins: 60 },
  },
  {
    name: 'comp-year-two-three-tuesday-free',
    about: 'comp-year-two-three with Tuesday kept free: it can be done, but only with a longer run on more days, (240, 4) where the best week without it is (120, 3).',
    courses: ['COMP 2601', 'COMP 2611', 'COMP 3607', 'COMP 3613'],
    preferences: { freeDays: ['Tuesday'], breakMins: 60 },
  },
  {
    name: 'comp-year-two-three-monday-friday-free',
    about: 'comp-year-two-three with Monday and Friday kept free: the COMP 2601 tutorial and the COMP 3607 lab only run on Friday, so two classes stay on a free day whatever is chosen.',
    courses: ['COMP 2601', 'COMP 2611', 'COMP 3607', 'COMP 3613'],
    preferences: { freeDays: ['Monday', 'Friday'], breakMins: 60 },
  },
  {
    name: 'comp-year-two-three-pinned-lecture-wednesday-free',
    about: 'comp-year-two-three-pinned-lecture with Wednesday kept free: the pinned COMP 2611 lecture is on Wednesday and does not count, so B* is 1, for the COMP 3613 lecture that only runs on Wednesday, and not 2.',
    courses: ['COMP 2601', 'COMP 2611', 'COMP 3607', 'COMP 3613'],
    pins: [{ sessionId: 19220, kind: 'main' }],
    preferences: { freeDays: ['Wednesday'], breakMins: 60 },
  },
  {
    name: 'comp-year-two-three-two-hour-break',
    about: 'comp-year-two-three with a 2-hour break: classes an hour apart now join, so the front of (120, 3) becomes three entries trading run against days.',
    courses: ['COMP 2601', 'COMP 2611', 'COMP 3607', 'COMP 3613'],
    preferences: { freeDays: [], breakMins: 120 },
  },
  {
    name: 'agbu-with-biol-both-choices',
    about: 'agbu-with-biol with Monday and Friday free and a 2-hour break: the front differs both from the one with free days alone, (120, 1), and from the one with the break alone.',
    courses: ['AGBU 1005', 'BIOL 2061'],
    preferences: { freeDays: ['Monday', 'Friday'], breakMins: 120 },
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
 *
 * The last two carry preferences (spec 14) and are worked the same way.
 *
 * paper-clash-free-on-free-day. Monday free, 1-hour break. Fixed F Tue
 * 09:00-11:00. Lab: S1 Mon 10:00-11:00, S2 Tue 10:00-11:00. Tutorial: T1 Mon
 * 14:00-15:00, T2 Wed 14:00-15:00. All weeks 1 to 12, so every week is alike.
 *   S1+T1: no clash. B = 2. Mon has 10-11 and 14-15, three hours apart, so two
 *          runs of 60; Tue 120. (120, 2).
 *   S1+T2: no clash. B = 1. Mon 60, Tue 120, Wed 60. (120, 3).
 *   S2+T1: S2 overlaps F on Tuesday, C = 1, B = 1.
 *   S2+T2: C = 1, B = 0.
 * C* = 0, so S2 is out however much the free Monday wanted it: B* = 1, not 0.
 * Of the two clash-free weeks only S1+T2 has B = 1, so the front is
 * [(120, 3)], though S1+T1 has fewer days. Without the free day it would be
 * [(120, 2)].
 *
 * gap-ninety-two-hour-break. 2-hour break, no free days. Fixed F1 Thu
 * 09:00-10:30 and F2 Thu 14:30-15:30. One group: X Thu 12:00-13:00, W Thu
 * 12:30-13:30, Y Fri 08:00-09:00. All weeks 1 to 12. No sitting clashes.
 *   X: 12:00 is 90 after 10:30, under 120, so it joins F1; 14:30 is 90 after
 *      13:00 and joins too. One run 09:00-15:30 of 390. (390, 1).
 *   W: 12:30 is 120 after 10:30, not under 120, so a new run starts; 14:30 is
 *      60 after 13:30 and joins it. Runs of 90 and 180. (180, 1).
 *   Y: Thursday's two classes are 240 apart, runs of 90 and 60; Friday 60.
 *      (90, 2).
 * C* = 0, B* = 0, and (180, 1) beats (390, 1): the front is [(90, 2),
 * (180, 1)]. Joining at 90 is what keeps X off the front; were W joined at
 * exactly 120 it would score (390, 1) and drop off as well. With the 1-hour
 * break all three make runs of 90 at most and the front is [(90, 1)].
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
  {
    name: 'paper-clash-free-on-free-day',
    about: 'Small enough to work on paper: the only lab that misses the fixed class is on the free Monday, so it is chosen, C* is 0 and B* is 1.',
    preferences: { freeDays: ['Monday'], breakMins: 60 },
    fixed: [_fixed('HAND 0006 Lecture (pinned)', 'Tuesday', '09:00', '11:00', ALL_WEEKS)],
    groups: [
      {
        groupId: 'HAND 0006|Lab|all',
        sittings: [
          _sitting(61, 'Monday', '10:00', '11:00', ALL_WEEKS),
          _sitting(62, 'Tuesday', '10:00', '11:00', ALL_WEEKS),
        ],
      },
      {
        groupId: 'HAND 0006|Tutorial|all',
        sittings: [
          _sitting(63, 'Monday', '14:00', '15:00', ALL_WEEKS),
          _sitting(64, 'Wednesday', '14:00', '15:00', ALL_WEEKS),
        ],
      },
    ],
  },
  {
    name: 'gap-ninety-two-hour-break',
    about: 'Small enough to work on paper: with a 2-hour break a 90-minute gap joins two classes and a 120-minute gap does not, which the warehouse cannot show because its classes all start on the hour.',
    preferences: { freeDays: [], breakMins: 120 },
    fixed: [
      _fixed('HAND 0007 Lecture (pinned)', 'Thursday', '09:00', '10:30', ALL_WEEKS),
      _fixed('HAND 0007 Lab (pinned)', 'Thursday', '14:30', '15:30', ALL_WEEKS),
    ],
    groups: [
      {
        groupId: 'HAND 0007|Tutorial|all',
        sittings: [
          _sitting(71, 'Thursday', '12:00', '13:00', ALL_WEEKS),
          _sitting(72, 'Thursday', '12:30', '13:30', ALL_WEEKS),
          _sitting(73, 'Friday', '08:00', '09:00', ALL_WEEKS),
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
    ..._preferencesOf(spec),
    fixed,
    groups,
  };
}

/**
 * A case's preferences in the written shape, or nothing when it has none, so
 * a case without them is written exactly as it was before preferences
 * existed. Spec 14.6.
 */
function _preferencesOf(spec) {
  if (!spec.preferences) return {};
  const { freeDays, breakMins } = spec.preferences;
  if (!Array.isArray(freeDays) || freeDays.some((d) => !DAY_NAMES.includes(d))) {
    throw new Error(`${spec.name}: free days must be day names, got ${JSON.stringify(freeDays)}`);
  }
  if (!BREAK_CHOICES.includes(breakMins)) {
    throw new Error(`${spec.name}: a break is 60 or 120 minutes, got ${breakMins}`);
  }
  return { preferences: { freeDays: [...freeDays], breakMins } };
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
    ..._preferencesOf(spec),
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

/**
 * Longest run and days with class in the worst week. Spec 3.2, with the
 * break the student chose in place of the fixed hour (spec 14.2).
 */
function _runAndDays(events, weeks, breakMins) {
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
        if (event.start - reach < breakMins) {
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
 * C*, B* and the front, found by scoring every arrangement.
 *
 * Spec 14.2: the fewest clashes first, then among those the fewest chosen
 * sittings on a free day, then the front over what is left. Fixed events are
 * never counted toward B, since the student cannot move them. A case with no
 * preferences has no free days and the one-hour break, which is the model of
 * spec 3 exactly, so its B* is 0 and its answer is the one it always had.
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

  const preferences = instance.preferences || { freeDays: [], breakMins: RUN_BREAK_MINS };
  const freeDays = new Set(preferences.freeDays);

  const choice = instance.groups.map(() => 0);
  const fixedIds = instance.fixed.map((_, i) => i);
  let best = Infinity;
  let bestBlocked = Infinity;
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

    // Only the chosen sittings, one per group, are looked at here.
    let blocked = 0;
    choice.forEach((c, g) => {
      if (freeDays.has(instance.groups[g].sittings[c].day)) blocked++;
    });

    if (clashes < best || (clashes === best && blocked <= bestBlocked)) {
      if (clashes < best || blocked < bestBlocked) {
        best = clashes;
        bestBlocked = blocked;
        pairs = new Map();
      }
      const { runMins, days } = _runAndDays(
        ids.map((id) => plain[id]),
        weeks,
        preferences.breakMins
      );
      pairs.set(`${runMins}|${days}`, { runMins, days });
    }

    // Odometer: the last group turns fastest.
    for (let g = choice.length - 1; g >= 0; g--) {
      choice[g]++;
      if (choice[g] < instance.groups[g].sittings.length) break;
      choice[g] = 0;
    }
  }

  return {
    arrangements,
    clashes: best,
    blocked: bestBlocked,
    front: _front([...pairs.values()]),
  };
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
      expected: { clashes: answer.clashes, blocked: answer.blocked, front: answer.front },
    });
    console.log(
      `${instance.name}: ${answer.arrangements} arrangements, ` +
      `C* ${answer.clashes}, B* ${answer.blocked}, front ${_frontText(answer.front)}`
    );
  }
  fs.writeFileSync(OUTPUT, _format({ runBreakMins: RUN_BREAK_MINS, cases }, '') + '\n');
  console.log(`wrote ${cases.length} cases to ${path.relative(process.cwd(), OUTPUT)}`);
}

module.exports = { buildInstances, solveByBruteForce, countArrangements };

if (require.main === module) main();
