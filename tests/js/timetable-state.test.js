'use strict';

/**
 * The timetable a student is building, and the two sources it comes from.
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
  'timetable-state.js'
);
const TimetableState = api.get('TimetableState');
const courseCodeFromTitle = api.get('courseCodeFromTitle');

/** A warehouse response holding just these courses. */
function response(...codes) {
  return {
    publicationId: warehouse.publicationId,
    courses: codes.map(course),
    notFound: [],
  };
}

function stateOf(...codes) {
  const sourceData = TimetableState.fromWarehouseResponse(response(...codes));
  const state = new TimetableState(sourceData);
  state.placeMissing();
  return state;
}

/** An extract response of the shape POST /extract returns. */
function extractResponse(courseTitle, entries) {
  return {
    results: [
      {
        course_title: courseTitle,
        source_file: 'm104178.pdf',
        entries: entries.map((e) => ({
          type: e.type,
          day: e.day,
          start_time: e.start,
          end_time: e.end,
          room: e.room || null,
          staff: e.staff || null,
          group_label: e.label || null,
          weeks: e.weeks || 'W1-W12',
        })),
      },
    ],
  };
}

// Identity across the two sources


test('a course code is read out of an uploaded title', () => {
  assert.equal(
    courseCodeFromTitle('COMP 2601, Computer Architecture'),
    'COMP 2601'
  );
});

test('a parenthetical qualifier is part of the code, not noise', () => {
  // UWI publishes these as two different courses.
  assert.equal(
    courseCodeFromTitle('FOUN 1001 (FULL & PART-TIME), Caribbean Civilisation'),
    'FOUN 1001 (FULL & PART-TIME)'
  );
});

test('a title with a lecturer glued on is not mistaken for a code', () => {
  // "IENG 3017 LALLA,TERRENCE" splits on the comma into something that starts
  // like a code. Keying a course on it would invent a course nobody published.
  assert.equal(courseCodeFromTitle('IENG 3017 LALLA,TERRENCE'), null);
});

test('the code is read past the "Course timetable - " prefix every CELCAT course PDF carries', () => {
  // The title /extract returns for downloaded_pdfs/m103865.pdf.
  assert.equal(
    courseCodeFromTitle('Course timetable - LAW 0101, Introduction to Commonwealth Caribbean Legal Systems (Wks W3-W12)'),
    'LAW 0101'
  );
  assert.equal(
    courseCodeFromTitle('Course timetable - FOUN 1001 (FULL & PART-TIME), Caribbean Civilisation (Wks W1-W12)'),
    'FOUN 1001 (FULL & PART-TIME)'
  );
});

test('only the course timetable prefix is skipped, so a staff timetable is still no course', () => {
  assert.equal(courseCodeFromTitle('Staff timetable - IENG 3017, Lalla Terrence'), null);
});

test('a title with no code at all falls back rather than guessing', () => {
  assert.equal(courseCodeFromTitle('Timetable for the week'), null);
});

test('the same class from both sources computes the same stream id', () => {
  const fromWarehouse = TimetableState.fromWarehouseResponse(
    response('COMP 1601')
  ).courses[0];
  const lecture = fromWarehouse.sessions.find(
    (s) => s.type === 'Lecture' && s.day === 'Monday' && s.startTime === '12:00'
  );

  const fromUpload = TimetableState.fromExtractResponse(
    extractResponse('COMP 1601, Computer Programming I', [
      { type: 'Lecture', day: 'Monday', start: '12:00', end: '13:00', room: 'TLC LT A1' },
    ])
  ).courses[0];

  assert.equal(fromUpload.courseKey, fromWarehouse.courseKey);
  assert.equal(fromUpload.sessions[0].streamId, lecture.streamId);
});

test('an uploaded course is marked as such, and so is a warehouse one', () => {
  const uploaded = TimetableState.fromExtractResponse(
    extractResponse('COMP 1601, Computer Programming I', [
      { type: 'Lecture', day: 'Monday', start: '12:00', end: '13:00' },
    ])
  );
  const fetched = TimetableState.fromWarehouseResponse(response('COMP 1601'));

  assert.equal(uploaded.courses[0].origin, 'upload');
  assert.equal(fetched.courses[0].origin, 'warehouse');
});

test('uploaded weeks stay printed text, so uploads clash as they always did', () => {
  const uploaded = TimetableState.fromExtractResponse(
    extractResponse('COMP 1601, Computer Programming I', [
      { type: 'Lecture', day: 'Monday', start: '12:00', end: '13:00', weeks: 'W1-W12' },
    ])
  );
  const session = uploaded.courses[0].sessions[0];

  assert.equal(session.weeks, null, 'null reads as every week');
  assert.equal(session.weeksRaw, 'W1-W12');
});

// Placing


test('adding a course places one class per option group', () => {
  const state = stateOf('COMP 1601');

  assert.equal(state.placements.length, state.optionGroups.length);
  assert.equal(state.getPlacedEvents().length, state.optionGroups.length);
});

test('a five course load is placed without a clash', () => {
  const state = stateOf(
    'COMP 1601',
    'COMP 1602',
    'MATH 1115',
    'FOUN 1101',
    'PSYC 1001'
  );

  assert.deepEqual(state.getConflicts(), []);
  assert.ok(state.placements.length <= 25);
});

test('adding a course leaves the others where they were', () => {
  const state = stateOf('COMP 1601');
  const before = JSON.parse(JSON.stringify(state.placements));

  const psyc = TimetableState.fromWarehouseResponse(response('PSYC 1001'))
    .courses[0];
  state.addCourse(psyc);

  for (const original of before) {
    assert.deepEqual(
      state.placements.find((p) => p.groupId === original.groupId),
      original
    );
  }
});

test('adding a course already on the timetable changes nothing', () => {
  const state = stateOf('COMP 1601');
  const before = JSON.parse(JSON.stringify(state.placements));

  const again = TimetableState.fromWarehouseResponse(response('COMP 1601'))
    .courses[0];
  const result = state.addCourse(again);

  assert.deepEqual(result.added, []);
  assert.deepEqual(result.alreadyPresent, ['COMP 1601']);
  assert.deepEqual(state.placements, before);
});

// Adding takes the best week. WEEK-OPTIMISER-SPEC 5.1

/** The first-year load of spec 9.3. */
const FIRST_YEAR = [
  'COMP 1601',
  'COMP 1602',
  'MATH 1115',
  'FOUN 1101',
  'FOUN 1001 (FULL & PART-TIME)',
];

function coursesOf(...codes) {
  return TimetableState.fromWarehouseResponse(response(...codes)).courses;
}

/** The longest run and days of the week on a state's grid. */
function qualityOf(state) {
  const weekQuality = api.get('weekQuality');
  const eventsFor = api.get('eventsFor');
  return weekQuality(eventsFor(state.placements, state.groupIndex));
}

test('adding courses takes the week with the shortest stretch of class, not the earliest', () => {
  const courses = coursesOf(...FIRST_YEAR);
  const state = new TimetableState({ courses: [] });
  const result = state.addCourses(courses);

  // What the old placer gives for the same courses, for comparison.
  const groups = courses.map((c) => ({
    courseKey: c.courseKey,
    groups: api.get('weeklyOptionGroups')(c, {}),
  }));
  const index = api.get('indexGroups')(groups.flatMap((c) => c.groups));
  const old = api.get('placeCourses')([], groups, index);
  const before = api.get('weekQuality')(api.get('eventsFor')(old.placements, index));

  const after = qualityOf(state);
  assert.deepEqual(state.getConflicts(), []);
  assert.ok(
    after.runMins < before.runMins,
    `longest run ${after.runMins} should be under the old placer's ${before.runMins}`
  );
  assert.deepEqual({ ...result.summary.quality }, { ...after });
  assert.equal(result.summary.proven, true);
});

test('adding courses moves nothing already on the timetable, pinned or not', () => {
  const state = stateOf('COMP 1601', 'PSYC 1001');
  const menu = state.optionGroups.find((g) => g.sessions.length > 1);
  state.moveEvent(menu.groupId, menu.sessions[4].sessionId);
  const before = JSON.parse(JSON.stringify(state.placements));
  assert.ok(before.some((p) => p.pinned) && before.some((p) => !p.pinned));

  state.addCourses(coursesOf('COMP 1602', 'MATH 1115', 'FOUN 1101'));

  assert.ok(state.placements.length > before.length);
  assert.deepEqual(
    JSON.parse(JSON.stringify(state.placements.slice(0, before.length))),
    before
  );
});

test('classes that are added arrive unpinned', () => {
  const state = stateOf('COMP 1601');
  const had = state.placements.length;

  state.addCourses(coursesOf('COMP 1602', 'MATH 1115'));

  const added = state.placements.slice(had);
  assert.ok(added.length > 0);
  assert.ok(added.every((p) => !p.pinned));
});

test('what adding reports keeps every field the page reads', () => {
  const state = new TimetableState({ courses: [] });
  const result = state.addCourses(coursesOf(...FIRST_YEAR));

  assert.deepEqual([...result.added], FIRST_YEAR);
  assert.deepEqual([...result.alreadyPresent], []);
  assert.equal(result.placed.length, state.placements.length);
  for (const entry of result.placed) {
    const placement = state.placements.find((p) => p.groupId === entry.groupId);
    assert.equal(entry.selectedSessionId, placement.selectedSessionId);
    assert.equal(entry.clashing, false);
  }
  for (const key of [
    'courses',
    'groups',
    'conflictsBefore',
    'conflictsAfter',
    'repairAttempts',
    'repairCapped',
    'unavoidable',
  ]) {
    assert.ok(key in result.summary, `summary.${key} is missing`);
  }
  assert.equal(result.summary.conflictsAfter, 0);
});

test('the same courses added in another order give the same week', () => {
  // A share link carries course codes only, so the recipient's browser has
  // to land on the week the sender saw.
  const chosen = (state) =>
    state.placements
      .map((p) => `${p.groupId} ${p.selectedSessionId}`)
      .sort();

  const one = new TimetableState({ courses: [] });
  one.addCourses(coursesOf(...FIRST_YEAR));
  const other = new TimetableState({ courses: [] });
  other.addCourses(coursesOf(...[...FIRST_YEAR].reverse()));

  assert.deepEqual(chosen(other), chosen(one));
});

test('undo after adding puts the timetable back exactly', () => {
  const state = stateOf('COMP 1601');
  const before = JSON.parse(JSON.stringify(state.placements));

  state.addCourses(coursesOf('COMP 1602', 'MATH 1115'));
  state.undo();

  assert.deepEqual(JSON.parse(JSON.stringify(state.placements)), before);
  assert.deepEqual([...state.courseKeys], ['COMP 1601']);
});

test('removing a course leaves every other placement put', () => {
  const state = stateOf('COMP 1601', 'PSYC 1001');
  const keep = state.placements.filter((p) => p.courseKey === 'COMP 1601');

  state.removeCourse('PSYC 1001');

  assert.deepEqual(state.placements, keep);
  assert.ok(!state.getPlacedEvents().some((e) => e.courseKey === 'PSYC 1001'));
});

// Starting over

test('clearing empties every course and every placement', () => {
  const state = stateOf('COMP 1601', 'PSYC 1001', 'MATH 1115');

  assert.equal(state.clearAll(), true);

  assert.deepEqual(state.courseKeys, []);
  assert.deepEqual(state.placements, []);
  assert.deepEqual(state.getPlacedEvents(), []);
  assert.deepEqual(state.optionGroups, []);
});

test('clearing costs one undo, not one per course', () => {
  /**
   * Three separate snapshots would make starting over feel like a trap: the
   * student presses Ctrl+Z, gets one course back, and has to guess how many
   * more presses there are.
   */
  const state = stateOf('COMP 1601', 'PSYC 1001', 'MATH 1115');
  const before = JSON.parse(JSON.stringify(state.placements));

  state.clearAll();
  state.undo();

  assert.deepEqual(state.courseKeys.sort(), ['COMP 1601', 'MATH 1115', 'PSYC 1001']);
  assert.deepEqual(state.placements, before);
});

test('clearing keeps the courses in the pool, so undo needs no network', () => {
  const state = stateOf('COMP 1601', 'PSYC 1001');

  state.clearAll();

  assert.ok(state.getCourse('COMP 1601'), 'still pooled');
  assert.ok(state.getCourse('PSYC 1001'), 'still pooled');
});

test('clearing an already empty timetable reports that it did nothing', () => {
  // So the button can stay quiet rather than announce an empty clear.
  const state = new TimetableState({ courses: [] }, null);

  assert.equal(state.clearAll(), false);
  assert.equal(state.history.length, 0, 'and does not spend an undo slot');
});

test('a cleared timetable saves as empty rather than keeping the old one', () => {
  /**
   * Saving happens on change, so a clear that did not reach storage would
   * come back on the next reload.
   */
  const state = stateOf('COMP 1601');
  state.clearAll();

  const saved = state.toSaved();
  assert.deepEqual(saved.courseKeys, []);
  assert.deepEqual(saved.placements, []);
});

test('courses can be added again after clearing', () => {
  const state = stateOf('COMP 1601', 'PSYC 1001');
  state.clearAll();

  state.addCourse(state.getCourse('PSYC 1001'));

  assert.deepEqual(state.courseKeys, ['PSYC 1001']);
  assert.ok(state.getPlacedEvents().some((e) => e.courseKey === 'PSYC 1001'));
  assert.ok(!state.getPlacedEvents().some((e) => e.courseKey === 'COMP 1601'));
});

test('a removed course can be added back without fetching it again', () => {
  const state = stateOf('COMP 1601', 'PSYC 1001');
  state.removeCourse('PSYC 1001');

  const pooled = state.getCourse('PSYC 1001');
  assert.ok(pooled, 'the course data is kept so undo and re-add are free');
  state.addCourse(pooled);

  assert.ok(state.getPlacedEvents().some((e) => e.courseKey === 'PSYC 1001'));
});

// Pinning


test('choosing an option by hand pins it', () => {
  const state = stateOf('COMP 1601');
  const menu = state.optionGroups.find((g) => g.sessions.length > 1);
  const target = menu.sessions[4].sessionId;

  state.moveEvent(menu.groupId, target);

  const placement = state.placements.find((p) => p.groupId === menu.groupId);
  assert.equal(placement.selectedSessionId, target);
  assert.equal(placement.pinned, true);
});

test('re-optimising does not move what the student pinned', () => {
  const state = stateOf('COMP 1601', 'PSYC 1001');
  const menu = state.optionGroups.find((g) => g.sessions.length > 1);
  const target = menu.sessions[4].sessionId;
  state.moveEvent(menu.groupId, target);

  state.reoptimise();

  const placement = state.placements.find((p) => p.groupId === menu.groupId);
  assert.equal(placement.selectedSessionId, target);
  assert.equal(placement.pinned, true);
});

test('re-optimising still places everything', () => {
  const state = stateOf('COMP 1601', 'MATH 1115');
  const groups = state.optionGroups.length;

  state.reoptimise();

  assert.equal(state.placements.length, groups);
});

// Re-arrange: the best weeks on offer, and taking one

// Read lazily, so these fail one by one before the helper exists.
function sameArrangement(a, b) {
  return api.get('sameArrangement')(a, b);
}

const plain = (value) => JSON.parse(JSON.stringify(value));

/** [clashes, runMins, days] of a set of placements, scored independently. */
function scoreOfPlacements(state, placements) {
  const events = api.get('eventsFor')(placements, state.groupIndex);
  const q = api.get('weekQuality')(events);
  return [api.get('findConflicts')(events).length, q.runMins, q.days];
}

/** Negative when a is the better week: clashes, then run, then days. */
function compareScores(a, b) {
  for (let i = 0; i < 3; i++) {
    if (a[i] !== b[i]) return a[i] - b[i];
  }
  return 0;
}

/** Everything a student could lose: the grid, the history, the saved copy. */
function stateSnapshot(state) {
  const { savedAt, ...saved } = state.toSaved();
  return plain({
    placements: state.placements,
    history: state.history.length,
    future: state.future.length,
    saved,
  });
}

/** A first-year week added from empty, then one class pinned somewhere else. */
function firstYearWithPin() {
  const state = new TimetableState({ courses: [] });
  state.addCourses(coursesOf(...FIRST_YEAR));
  const menu = state.optionGroups.find((g) => g.sessions.length > 2);
  const placed = state.placements.find((p) => p.groupId === menu.groupId);
  const target = menu.sessions.find((s) => s.sessionId !== placed.selectedSessionId);
  state.moveEvent(menu.groupId, target.sessionId);
  return { state, pinned: { groupId: menu.groupId, sessionId: target.sessionId } };
}

test('asking for re-arrange options changes nothing', () => {
  const { state } = firstYearWithPin();
  const before = stateSnapshot(state);
  let notified = 0;
  state.onChange(() => { notified += 1; });

  const result = state.rearrangeOptions();

  assert.deepEqual(stateSnapshot(state), before);
  assert.equal(notified, 0);
  assert.ok(result.current);
  assert.ok(Array.isArray(result.options));
  assert.ok(result.options.length >= 1 && result.options.length <= 3);
  assert.equal(typeof result.proven, 'boolean');
  for (const option of [result.current, ...result.options]) {
    for (const key of ['runMins', 'days', 'clashes', 'placements']) {
      assert.ok(key in option, `${key} is missing`);
    }
  }
});

test('the current week is a copy, so changing it cannot touch the grid', () => {
  const { state } = firstYearWithPin();
  const before = plain(state.placements);
  const { current } = state.rearrangeOptions();

  assert.deepEqual(plain(current.placements), before);
  assert.notStrictEqual(current.placements, state.placements);
  current.placements.length = 0;
  assert.deepEqual(plain(state.placements), before);
});

test('the current week reports the figures of the grid', () => {
  const { state } = firstYearWithPin();
  const { current } = state.rearrangeOptions();
  const [clashes, runMins, days] = scoreOfPlacements(state, state.placements);
  assert.deepEqual(
    [current.clashes, current.runMins, current.days],
    [clashes, runMins, days]
  );
});

test('each option reports its own figures and is a full week', () => {
  const { state } = firstYearWithPin();
  const groups = new Set(state.placements.map((p) => p.groupId));
  for (const option of state.rearrangeOptions().options) {
    const [clashes, runMins, days] = scoreOfPlacements(state, option.placements);
    assert.deepEqual([option.clashes, option.runMins, option.days], [clashes, runMins, days]);
    assert.deepEqual(new Set(option.placements.map((p) => p.groupId)), groups);
  }
});

test('options run from the shortest stretch to the fewest days', () => {
  const { state } = firstYearWithPin();
  const { options } = state.rearrangeOptions();
  for (let i = 1; i < options.length; i++) {
    assert.ok(options[i - 1].runMins < options[i].runMins);
    assert.ok(options[i - 1].days > options[i].days);
  }
});

test('a longer front is cut to its first, middle and last entries', () => {
  const pick = api.get('_rearrangePicks');
  const front = (n) => Array.from({ length: n }, (_, i) => ({ at: i }));
  const ats = (n) => pick(front(n)).map((e) => e.at);
  assert.deepEqual(ats(1), [0]);
  assert.deepEqual(ats(2), [0, 1]);
  assert.deepEqual(ats(3), [0, 1, 2]);
  assert.deepEqual(ats(4), [0, 2, 3]);
  assert.deepEqual(ats(5), [0, 2, 4]);
  assert.deepEqual(ats(7), [0, 3, 6]);
});

test('a front of three gives three options, in order', () => {
  // These three courses reach 2, 3 and 4 hours in a row on 4, 3 and 2 days.
  const state = new TimetableState({ courses: [] });
  state.addCourses(coursesOf('COMP 1602', 'MATH 1115', 'PSYC 1001'));
  const { options } = state.rearrangeOptions();
  assert.deepEqual(
    options.map((o) => [o.runMins, o.days]),
    [[120, 4], [180, 3], [240, 2]]
  );
});

test('a pinned class is in every option, where the student put it', () => {
  const { state, pinned } = firstYearWithPin();
  for (const option of state.rearrangeOptions().options) {
    const held = option.placements.filter((p) => p.groupId === pinned.groupId);
    assert.equal(held.length, 1);
    assert.equal(held[0].selectedSessionId, pinned.sessionId);
    assert.equal(held[0].pinned, true);
  }
});

test('every option has the fewest clashes, and no more than the grid has now', () => {
  const { state } = firstYearWithPin();
  const { current, options } = state.rearrangeOptions();
  const counts = new Set(options.map((o) => o.clashes));
  assert.equal(counts.size, 1);
  assert.ok(options[0].clashes <= current.clashes);
});

test('straight after adding from empty, the grid is one of the options', () => {
  const state = new TimetableState({ courses: [] });
  state.addCourses(coursesOf(...FIRST_YEAR));

  const { current, options } = state.rearrangeOptions();

  assert.ok(options.some((o) => sameArrangement(o.placements, current.placements)));
});

test('a week made worse by hand is never what re-arrange offers first', () => {
  const state = new TimetableState({ courses: [] });
  state.addCourses(coursesOf(...FIRST_YEAR));
  const best = scoreOfPlacements(state, state.placements);

  // Move one unpinned class somewhere that makes the week worse, then unpin
  // it, so the grid holds a worse week that re-arrange is free to change.
  let worse = null;
  for (const group of state.optionGroups) {
    const placed = state.placements.find((p) => p.groupId === group.groupId);
    for (const session of group.sessions) {
      const tried = state.placements.map((p) =>
        p === placed ? { ...p, selectedSessionId: session.sessionId } : p);
      if (compareScores(scoreOfPlacements(state, tried), best) > 0) {
        worse = { groupId: group.groupId, sessionId: session.sessionId };
        break;
      }
    }
    if (worse) break;
  }
  assert.ok(worse, 'no single move makes this week worse');
  state.moveEvent(worse.groupId, worse.sessionId);
  state.setPinned(worse.groupId, false);
  assert.ok(state.placements.every((p) => !p.pinned));

  const { current, options } = state.rearrangeOptions();
  const now = [current.clashes, current.runMins, current.days];
  const first = [options[0].clashes, options[0].runMins, options[0].days];
  assert.ok(compareScores(first, now) < 0, `${first} should beat ${now}`);
});

test('taking an option puts that week on the grid, and one undo takes it back', () => {
  const state = new TimetableState({ courses: [] });
  state.addCourses(coursesOf(...FIRST_YEAR));
  const menu = state.optionGroups.find((g) => g.sessions.length > 2);
  const placed = state.placements.find((p) => p.groupId === menu.groupId);
  const other = menu.sessions.find((s) => s.sessionId !== placed.selectedSessionId);
  state.moveEvent(menu.groupId, other.sessionId);
  state.setPinned(menu.groupId, false);
  const before = plain(state.placements);
  const depth = state.history.length;
  let notified = 0;
  state.onChange(() => { notified += 1; });

  const { options } = state.rearrangeOptions();
  const option = options[options.length - 1];
  assert.equal(state.applyArrangement(option), true);

  assert.ok(sameArrangement(state.placements, option.placements));
  assert.notStrictEqual(state.placements, option.placements);
  assert.equal(state.history.length, depth + 1);
  assert.equal(notified, 1);

  state.undo();
  assert.deepEqual(plain(state.placements), before);

  state.redo();
  assert.ok(sameArrangement(state.placements, option.placements));
});

test('applying no option, or one without placements, does nothing', () => {
  const state = stateOf('COMP 1601');
  const before = stateSnapshot(state);
  assert.equal(state.applyArrangement(), false);
  assert.equal(state.applyArrangement(null), false);
  assert.equal(state.applyArrangement({ runMins: 0, days: 0 }), false);
  assert.deepEqual(stateSnapshot(state), before);
});

test('re-optimising applies the first option', () => {
  const { state } = firstYearWithPin();
  const { options } = state.rearrangeOptions();

  state.reoptimise();

  assert.deepEqual(plain(state.placements), plain(options[0].placements));
});

test('re-optimising is still one undo step', () => {
  const { state } = firstYearWithPin();
  const before = plain(state.placements);
  const depth = state.history.length;

  state.reoptimise();
  assert.equal(state.history.length, depth + 1);

  state.undo();
  assert.deepEqual(plain(state.placements), before);
});

test('a split lecture group stays split in every option', () => {
  const state = stateOf('COMP 1601');
  state.setOptionGroupOverride('COMP 1601', 'Lecture', 'split');
  const lectureGroups = state.optionGroups
    .filter((g) => g.courseKey === 'COMP 1601' && g.type === 'Lecture')
    .map((g) => g.groupId)
    .sort();
  assert.ok(lectureGroups.length > 1, 'COMP 1601 lectures no longer split');

  for (const option of state.rearrangeOptions().options) {
    const held = option.placements
      .filter((p) => lectureGroups.includes(p.groupId))
      .map((p) => p.groupId)
      .sort();
    assert.deepEqual(held, lectureGroups);
  }
});

// The student's override


test('an override regroups the course and replaces its placements', () => {
  const state = stateOf('AGBU 1005');
  const lectures = () => state.optionGroups.filter((g) => g.type === 'Lecture');
  assert.equal(lectures().length, 1, 'one choice of two sittings by default');

  state.setOptionGroupOverride('AGBU 1005', 'Lecture', 'split');

  assert.equal(lectures().length, 2, 'now two classes to attend');
  const placed = state.placements.filter((p) =>
    p.groupId.startsWith('AGBU 1005|Lecture')
  );
  assert.equal(placed.length, 2);
  assert.ok(placed.every((p) => state.getPlacedEventDetails(p.groupId)));
});

test('an override leaves no placement pointing at a group that is gone', () => {
  const state = stateOf('AGBU 1005');

  state.setOptionGroupOverride('AGBU 1005', 'Lecture', 'split');

  const ids = new Set(state.optionGroups.map((g) => g.groupId));
  assert.ok(state.placements.every((p) => ids.has(p.groupId)));
});

test('a placement whose session is gone is dropped, not left holding the group', () => {
  /**
   * The nastier of the two: the group still exists, so a check for missing
   * groups alone leaves the placement in place. It renders nothing, and
   * because the group looks occupied the gap is never refilled, so the class
   * disappears from the timetable in silence.
   */
  const state = stateOf('COMP 1601');
  const lab = state.placements.find((p) => p.groupId === 'COMP 1601|Lab|all');
  lab.selectedSessionId = 99999999;

  assert.equal(state.pruneDanglingPlacements(), 1);
  assert.ok(!state.placements.some((p) => p.groupId === 'COMP 1601|Lab|all'));

  state.placeMissing();
  const refilled = state.placements.find((p) => p.groupId === 'COMP 1601|Lab|all');
  assert.ok(refilled, 'the gap is refilled once the dead placement is gone');
  assert.ok(state.getPlacedEvents().some((e) => e.type === 'Lab'));
});

test('a placement that still resolves is left alone by pruning', () => {
  const state = stateOf('COMP 1601');
  const before = JSON.parse(JSON.stringify(state.placements));

  assert.equal(state.pruneDanglingPlacements(), 0);
  assert.deepEqual(state.placements, before);
});

test('placements stranded by a rule change are dropped and refilled', () => {
  /**
   * Group ids come from the grouping rules, so changing those rules strands
   * everything saved under the old ones. This is what stops a student's saved
   * timetable keeping a class they can neither see nor move.
   */
  const state = stateOf('COMP 1601');
  state.placements.push({
    courseKey: 'COMP 1601',
    groupId: 'COMP 1601|Lecture|Monday-12:00',
    selectedSessionId: 1,
    pinned: false,
  });

  assert.equal(state.pruneDanglingPlacements(), 1);
  const ids = new Set(state.optionGroups.map((g) => g.groupId));
  assert.ok(state.placements.every((p) => ids.has(p.groupId)));
});

// Dated one-offs

test('exams and relocated classes are never placed on the weekly grid', () => {
  /**
   * The 12 Oct 2026 review: an exam auto-placed as a weekly class clashed
   * with its own course's lecture, and the clash panel said it could not be
   * avoided. PSYC 1001 publishes a relocated lecture and a make-up tutorial.
   */
  const state = stateOf('PSYC 1001');
  const types = new Set(state.getPlacedEvents().map((e) => e.type));

  assert.ok(types.has('Lecture') && types.has('Tutorial'));
  assert.ok(!types.has('Lecture Relocated'));
  assert.ok(!types.has('Tutorial (make-up/relocated)'));
});

test('dated one-offs are listed instead, every sitting, in week order', () => {
  const state = stateOf('PSYC 1001');
  const dated = state.datedSessions;
  const source = course('PSYC 1001').sessions.filter((s) =>
    ['Lecture Relocated', 'Tutorial (make-up/relocated)'].includes(s.type));

  assert.equal(dated.length, source.length);
  assert.ok(dated.every((s) => s.courseKey === 'PSYC 1001' && s.courseTitle));
  const firstWeeks = dated.map((s) => Math.min(...s.weeks));
  assert.deepEqual(firstWeeks, [...firstWeeks].sort((a, b) => a - b));
});

test('a removed course takes its dated one-offs with it', () => {
  const state = stateOf('PSYC 1001', 'COMP 1601');
  state.removeCourse('PSYC 1001');
  assert.deepEqual(state.datedSessions, []);
});

test('an exam placed on the grid before this change is cleared on load', () => {
  // A saved timetable from before carries the placement. Its group is no
  // longer a weekly one, so it stops resolving and pruning drops it.
  const state = stateOf('PSYC 1001');
  const relocated = course('PSYC 1001').sessions.find((s) => s.type === 'Lecture Relocated');
  state.placements.push({
    courseKey: 'PSYC 1001',
    groupId: 'PSYC 1001|Lecture Relocated|all',
    selectedSessionId: relocated.sessionId,
    pinned: false,
  });

  assert.equal(state.pruneDanglingPlacements(), 1);
  assert.equal(state.placeMissing(), false, 'nothing put it back');
  assert.ok(!state.placements.some((p) => p.groupId === 'PSYC 1001|Lecture Relocated|all'));
});

// History


test('undo takes back a whole course, not one class', () => {
  const state = stateOf('COMP 1601');
  const before = JSON.parse(JSON.stringify(state.placements));

  const psyc = TimetableState.fromWarehouseResponse(response('PSYC 1001'))
    .courses[0];
  state.addCourse(psyc);
  assert.ok(state.placements.length > before.length);

  state.undo();

  assert.deepEqual(state.placements, before);
  assert.ok(!state.courseKeys.includes('PSYC 1001'));
});

test('undo takes back a bulk add in one step', () => {
  const state = stateOf('COMP 1601');
  const before = state.placements.length;

  const added = ['PSYC 1001', 'MATH 1115'].map(
    (c) => TimetableState.fromWarehouseResponse(response(c)).courses[0]
  );
  state.addCourses(added);
  assert.ok(state.placements.length > before);

  state.undo();

  assert.equal(state.placements.length, before);
  assert.deepEqual(state.courseKeys, ['COMP 1601']);
});

test('undo puts a removed course back', () => {
  const state = stateOf('COMP 1601', 'PSYC 1001');
  const before = JSON.parse(JSON.stringify(state.placements));

  state.removeCourse('PSYC 1001');
  state.undo();

  assert.deepEqual(state.placements, before);
  assert.ok(state.courseKeys.includes('PSYC 1001'));
});

test('redo puts back what undo took away', () => {
  const state = stateOf('COMP 1601');
  const psyc = TimetableState.fromWarehouseResponse(response('PSYC 1001'))
    .courses[0];
  state.addCourse(psyc);
  const after = JSON.parse(JSON.stringify(state.placements));

  state.undo();
  state.redo();

  assert.deepEqual(state.placements, after);
});

test('nothing to undo is answered honestly', () => {
  const state = stateOf('COMP 1601');
  assert.equal(state.canRedo(), false);
  while (state.canUndo()) state.undo();
  assert.equal(state.undo(), false);
});

// Clashes, and what can be done about them


test('a clash-free timetable classifies to no clashes at all', () => {
  const state = stateOf('COMP 1601', 'COMP 1602');

  assert.deepEqual(state.getClassifiedConflicts(), []);
});

test('applying a fix moves the class and pins it there', () => {
  const state = stateOf('COMP 1601');
  const menu = state.optionGroups.find((g) => g.sessions.length > 1);
  const target = menu.sessions[3].sessionId;

  const applied = state.applyFix({ groupId: menu.groupId, sessionId: target });

  assert.equal(applied, true);
  const placement = state.placements.find((p) => p.groupId === menu.groupId);
  assert.equal(placement.selectedSessionId, target);
  assert.equal(placement.pinned, true, 'a fix is the student choosing');
});

test('applying nothing does nothing', () => {
  const state = stateOf('COMP 1601');
  const before = JSON.parse(JSON.stringify(state.placements));

  assert.equal(state.applyFix(null), false);
  assert.deepEqual(state.placements, before);
});

// The warehouse moving underneath a saved timetable


test('only warehouse courses are offered for refresh', () => {
  const state = stateOf('COMP 1601');
  const uploaded = TimetableState.fromExtractResponse(
    extractResponse('ZZZZ 9999, Something Unpublished', [
      { type: 'Lecture', day: 'Monday', start: '08:00', end: '09:00' },
    ])
  );
  state.addCourse(uploaded.courses[0]);

  assert.deepEqual(state.warehouseCourseKeys, ['COMP 1601']);
});

// Publication provenance, which the printed timetable carries

test('the publication date comes through from the warehouse', () => {
  const source = TimetableState.fromWarehouseResponse({
    publicationId: 1,
    publishedAt: '2026-08-06T14:22:58+00:00',
    courses: [course('COMP 1601')],
  });
  const state = new TimetableState(source, null);

  assert.equal(state.publishedAt, '2026-08-06T14:22:58+00:00');
});

test('a response with no publication date leaves it null, not undefined', () => {
  // The printed header drops the line on null, so the distinction matters.
  const state = new TimetableState(
    TimetableState.fromWarehouseResponse(response('COMP 1601')),
    null
  );

  assert.equal(state.publishedAt, null);
});

test('the publication date survives a save and reload', () => {
  /**
   * A student reloading with no network still gets their timetable out of
   * storage, and a printout that cannot say how old the data is would be
   * worse than one that can.
   */
  const source = TimetableState.fromWarehouseResponse({
    publicationId: 1,
    publishedAt: '2026-08-06T14:22:58+00:00',
    courses: [course('COMP 1601')],
  });
  const saved = new TimetableState(source, null).toSaved();

  assert.equal(saved.publishedAt, '2026-08-06T14:22:58+00:00');

  // Reloaded with no source data at all, which is the offline case.
  const reloaded = new TimetableState({ courses: saved.courses }, saved);
  assert.equal(reloaded.publishedAt, '2026-08-06T14:22:58+00:00');
});

test('refreshing onto a newer publication moves the date with it', () => {
  const state = stateOf('COMP 1601');
  const again = TimetableState.fromWarehouseResponse({
    publicationId: 2,
    publishedAt: '2026-09-01T00:00:00+00:00',
    courses: [course('COMP 1601')],
  });

  state.refreshFromWarehouse(again.courses, [], 2, again.publishedAt);

  assert.equal(state.publishedAt, '2026-09-01T00:00:00+00:00');
});

test('a refresh that reports no date keeps the one already known', () => {
  // Otherwise a refresh would silently strip the provenance line.
  const source = TimetableState.fromWarehouseResponse({
    publicationId: 1,
    publishedAt: '2026-08-06T14:22:58+00:00',
    courses: [course('COMP 1601')],
  });
  const state = new TimetableState(source, null);
  state.placeMissing();

  state.refreshFromWarehouse([course('COMP 1601')], [], 2, null);

  assert.equal(state.publishedAt, '2026-08-06T14:22:58+00:00');
});

test('a refresh keeps a placement that still resolves', () => {
  const state = stateOf('COMP 1601');
  const before = JSON.parse(JSON.stringify(state.placements));

  const again = TimetableState.fromWarehouseResponse(response('COMP 1601'));
  state.refreshFromWarehouse(again.courses, [], 2);

  assert.deepEqual(state.placements, before);
  assert.equal(state.publicationId, 2);
});

test('a placement whose class is gone is refilled, not left dangling', () => {
  const state = stateOf('COMP 3613');
  const lectureGroup = state.optionGroups.find(
    (g) => g.type === 'Lecture' && g.sessions.length === 1
  );

  // The new publication drops that one lecture.
  const trimmed = TimetableState.fromWarehouseResponse(response('COMP 3613'));
  const goneId = lectureGroup.sessions[0].sessionId;
  trimmed.courses[0].sessions = trimmed.courses[0].sessions.filter(
    (s) => s.sessionId !== goneId
  );

  const result = state.refreshFromWarehouse(trimmed.courses, [], 2);

  assert.equal(result.moved, 1);
  const ids = new Set(state.optionGroups.map((g) => g.groupId));
  assert.ok(state.placements.every((p) => ids.has(p.groupId)));
});

test('a class that moves while its group survives is followed, not stranded', () => {
  /**
   * The 28 August 2026 republish. `refreshFromWarehouse` used to drop
   * placements whose *group* had gone, which misses the ordinary case: UWI
   * moves one sitting, the group stays, and the placement is left pointing at
   * a session id the new publication does not have. It rendered nothing, held
   * its group against the refill below, and reported nothing had changed.
   * Ten of a student's twelve blocks disappeared until they reloaded.
   *
   * One sitting gone and one arrived is now read as that class moving, so
   * the placement follows it to Thursday.
   */
  const state = stateOf('COMP 1601');
  const group = state.optionGroups.find((g) => g.sessions.length > 1);
  const placed = state.placements.find((p) => p.groupId === group.groupId);

  // The same class at a new time, which is a new row and so a new id. The
  // group still exists because its other sittings are untouched.
  const moved = TimetableState.fromWarehouseResponse(response('COMP 1601'));
  const target = moved.courses[0].sessions.find(
    (s) => s.sessionId === placed.selectedSessionId
  );
  target.sessionId = 999001;
  target.day = 'Thursday';
  target.streamId = api.get('computeStreamId')(
    target.type, target.day, target.startTime, target.endTime, target.streamLabel
  );

  const result = state.refreshFromWarehouse(moved.courses, [], 2);

  assert.equal(result.moved, 1, 'the moved class is reported, not silently kept');

  const still = state.placements.find((p) => p.groupId === group.groupId);
  assert.ok(still, 'the group is refilled rather than left empty');
  assert.notEqual(still.selectedSessionId, placed.selectedSessionId);

  // Every placement resolves to something the student can actually see.
  const index = state.groupIndex;
  for (const p of state.placements) {
    assert.notEqual(
      api.get('eventForPlacement')(p, index), null,
      p.groupId + ' renders nothing'
    );
  }
});

/** The same courses as a real republish delivers them: every row renumbered. */
function republished(...codes) {
  const again = TimetableState.fromWarehouseResponse(response(...codes));
  for (const c of again.courses) {
    for (const s of c.sessions) s.sessionId += 40000;
  }
  return again;
}

/** What the student sees for a group: day and start of each placement. */
function slotsOf(state, groupId) {
  return state.getPlacedEvents()
    .filter((e) => e.groupId === groupId)
    .map((e) => `${e.day} ${e.startTime}`)
    .sort();
}

test('a republish that renumbers every class keeps every choice and pin', () => {
  /**
   * Every publication stores every session as a new row. Resolving by id
   * dropped the whole timetable on "Update my courses" and placed it again:
   * a pinned Tuesday 8am lab came back unpinned on Monday 10am, and the
   * toast said two classes had moved when none had.
   */
  const state = stateOf('COMP 1601');
  const menu = state.optionGroups.find((g) => g.sessions.length > 1);
  const placed = state.placements.find((p) => p.groupId === menu.groupId);
  const other = menu.sessions.find((s) => s.sessionId !== placed.selectedSessionId);
  state.moveEvent(menu.groupId, other.sessionId, placed.selectedSessionId);
  const before = state.getPlacedEvents().map((e) => `${e.groupId} ${e.day} ${e.startTime}`).sort();

  const result = state.refreshFromWarehouse(republished('COMP 1601').courses, [], 3);

  assert.equal(result.moved, 0, 'nothing moved, so nothing is reported');
  assert.deepEqual(
    state.getPlacedEvents().map((e) => `${e.groupId} ${e.day} ${e.startTime}`).sort(),
    before
  );
  const pinned = state.placements.find((p) => p.groupId === menu.groupId);
  assert.equal(pinned.pinned, true);
  assert.equal(pinned.selectedSessionId, other.sessionId + 40000);
});

test('an extra sitting survives a republish', () => {
  const state = stateOf('COMP 1602');
  const groupId = 'COMP 1602|Lecture|all';
  const placed = new Set(state.placements.filter((p) => p.groupId === groupId)
    .map((p) => p.selectedSessionId));
  const extra = state.getGroup(groupId).sessions.find((s) => !placed.has(s.sessionId));
  state.addSitting(groupId, extra.sessionId);
  const before = slotsOf(state, groupId);

  state.refreshFromWarehouse(republished('COMP 1602').courses, [], 3);

  assert.deepEqual(slotsOf(state, groupId), before);
});

test('a choice that cannot be told apart is placed again and reported', () => {
  // Two sittings of the chosen type moved at once, so which one is the
  // student's cannot be known. Guessing would put them in the wrong room.
  const state = stateOf('COMP 1601');
  const menu = state.optionGroups.find((g) => g.sessions.length > 2);
  const placed = state.placements.find((p) => p.groupId === menu.groupId);
  const chosen = menu.sessions.find((s) => s.sessionId === placed.selectedSessionId);
  const sibling = menu.sessions.find((s) => s.sessionId !== chosen.sessionId);

  const again = republished('COMP 1601');
  for (const s of again.courses[0].sessions) {
    if (s.sessionId - 40000 === chosen.sessionId || s.sessionId - 40000 === sibling.sessionId) {
      s.startTime = '20:00';
      s.endTime = s.sessionId - 40000 === chosen.sessionId ? '21:00' : '22:00';
    }
  }

  const result = state.refreshFromWarehouse(again.courses, [], 3);

  assert.equal(result.moved, 1);
  assert.equal(state.placements.filter((p) => p.groupId === menu.groupId).length, 1,
    'the group is refilled, not left empty');
  const index = state.groupIndex;
  for (const p of state.placements) {
    assert.notEqual(api.get('eventForPlacement')(p, index), null, p.groupId + ' renders nothing');
  }
});

/** Every placement resolves to a class the student can see. */
function assertAllResolve(state) {
  const index = state.groupIndex;
  for (const p of state.placements) {
    assert.notEqual(api.get('eventForPlacement')(p, index), null, p.groupId + ' renders nothing');
  }
}

function eventsOf(state) {
  return state.getPlacedEvents().map((e) => `${e.groupId} ${e.sessionId} ${e.day} ${e.startTime}`).sort();
}

test('undoing "Update my courses" puts the older timetable back, and redo the newer', () => {
  /**
   * Undo snapshots held choices but not course data, and an update swaps
   * the course data for a publication where every session has a new id. Undo
   * restored placements pointing at nothing: the grid went blank, and a
   * reload then placed everything again and lost the pins.
   */
  const source = TimetableState.fromWarehouseResponse({
    publicationId: 10, publishedAt: '2026-09-29T14:16:23+00:00', courses: [course('COMP 2611')],
  });
  const state = new TimetableState(source, null);
  state.placeMissing();
  const before = eventsOf(state);

  const again = republished('COMP 2611');
  state.refreshFromWarehouse(again.courses, [], 11, '2026-10-09T13:22:49+00:00');
  const after = eventsOf(state);
  assert.notDeepEqual(after, before, 'the update renumbered every class');

  assert.equal(state.undo(), true);
  assert.deepEqual(eventsOf(state), before);
  assert.equal(state.publicationId, 10);
  assert.equal(state.publishedAt, '2026-09-29T14:16:23+00:00');
  assertAllResolve(state);

  assert.equal(state.redo(), true);
  assert.deepEqual(eventsOf(state), after);
  assert.equal(state.publicationId, 11);
  assertAllResolve(state);
});

test('an edit from before the update can still be undone after undoing it', () => {
  const state = stateOf('COMP 2611');
  const lab = state.optionGroups.find((g) => g.type === 'Lab');
  const placed = state.placements.find((p) => p.groupId === lab.groupId);
  const other = lab.sessions.find((s) => s.sessionId !== placed.selectedSessionId);
  const original = eventsOf(state);
  state.moveEvent(lab.groupId, other.sessionId, placed.selectedSessionId);

  state.refreshFromWarehouse(republished('COMP 2611').courses, [], 3);
  state.undo(); // the update
  state.undo(); // the move

  assert.deepEqual(eventsOf(state), original);
  assertAllResolve(state);
});

test('an undoable update survives a reload', () => {
  const state = stateOf('COMP 2611');
  const before = eventsOf(state);
  state.refreshFromWarehouse(republished('COMP 2611').courses, [], 3);

  const saved = JSON.parse(JSON.stringify(state.toSaved()));
  const reloaded = new TimetableState({ courses: saved.courses, publicationId: saved.publicationId }, saved);
  reloaded.undo();

  assert.deepEqual(eventsOf(reloaded), before);
  assertAllResolve(reloaded);
});

test('only an update keeps course data in its undo step', () => {
  // Every other step is choices alone; course data in all fifty would fill
  // the browser's storage.
  const state = stateOf('COMP 2611');
  const lab = state.optionGroups.find((g) => g.type === 'Lab');
  const placed = state.placements.find((p) => p.groupId === lab.groupId);
  state.moveEvent(lab.groupId, lab.sessions.find((s) => s.sessionId !== placed.selectedSessionId).sessionId,
    placed.selectedSessionId);
  assert.equal(state.history.at(-1).data, undefined);

  state.refreshFromWarehouse(republished('COMP 2611').courses, [], 3);
  assert.ok(state.history.at(-1).data);
  state.undo();
  assert.ok(state.future.at(-1).data, 'redo carries the newer publication');
  state.undo();
  assert.equal(state.future.at(-1).data, undefined);
});

test('a refresh does not disturb anything the student pinned', () => {
  const state = stateOf('COMP 1601');
  const menu = state.optionGroups.find((g) => g.sessions.length > 1);
  const chosen = menu.sessions[4].sessionId;
  state.moveEvent(menu.groupId, chosen);

  const again = TimetableState.fromWarehouseResponse(response('COMP 1601'));
  state.refreshFromWarehouse(again.courses, [], 2);

  const placement = state.placements.find((p) => p.groupId === menu.groupId);
  assert.equal(placement.selectedSessionId, chosen);
  assert.equal(placement.pinned, true);
});

test('a course the new publication drops is kept and marked stale', () => {
  /**
   * A withdrawn code is far likelier than a student abandoning the course,
   * and emptying part of their timetable would be the worse mistake.
   */
  const state = stateOf('COMP 1601', 'PSYC 1001');
  const still = TimetableState.fromWarehouseResponse(response('COMP 1601'));

  const result = state.refreshFromWarehouse(still.courses, ['PSYC 1001'], 2);

  assert.deepEqual(result.stale, ['PSYC 1001']);
  assert.equal(state.getCourse('PSYC 1001').stale, true);
  assert.ok(state.courseKeys.includes('PSYC 1001'));
  assert.ok(state.getPlacedEvents().some((e) => e.courseKey === 'PSYC 1001'));
});

test('a refresh can be undone like anything else', () => {
  const state = stateOf('COMP 1601');
  const before = JSON.parse(JSON.stringify(state.placements));

  const again = TimetableState.fromWarehouseResponse(response('COMP 1601'));
  again.courses[0].sessions = again.courses[0].sessions.slice(0, 3);
  state.refreshFromWarehouse(again.courses, [], 2);
  state.undo();

  assert.deepEqual(state.placements, before);
});

// Detail panel


test('a placed class reports everything the detail panel shows', () => {
  const state = stateOf('BIOL 1262');
  const groupId = state.placements[0].groupId;

  const details = state.getPlacedEventDetails(groupId);

  assert.equal(details.courseTitle, 'Living Organisms I');
  assert.equal(details.origin, 'warehouse');
  assert.ok(details.day);
  assert.ok(Array.isArray(details.staff));
  assert.ok(details.optionCount >= 1);
  assert.equal(typeof details.pinned, 'boolean');
});

test('asking about a class that is not placed returns nothing, not a crash', () => {
  const state = stateOf('COMP 1601');
  assert.equal(state.getPlacedEventDetails('NOPE|Lecture|all'), null);
});

// What changed for this student

const LINES = [
  { code: 'COMP 1601', type: 'Lab', text: 'Lab moved from Mon 9am to Fri 9am', severity: 'act' },
  { code: 'COMP 1601', type: 'Lecture', text: 'venue confirmed', severity: 'info' },
];

test('the changes a republish made are kept after updating, until seen', () => {
  /**
   * The update notice listed a student's moved classes and threw the list
   * away the moment they pressed "Update my courses".
   */
  const state = stateOf('COMP 1601');
  assert.equal(state.unseenChanges, null);

  state.recordChanges({ fromPublication: 10, toPublication: 11, publishedAt: '2026-10-09T13:22:49Z', lines: LINES });
  assert.equal(state.unseenChanges.lines.length, 2);

  state.markChangesSeen();
  assert.equal(state.unseenChanges, null);
  assert.equal(state.seenPublicationId, 11);
});

test('only the classes to act on are marked changed, by course and type', () => {
  const state = stateOf('COMP 1601');
  state.recordChanges({ toPublication: 11, lines: LINES });
  assert.deepEqual([...state.changedClassKeys], ['COMP 1601|Lab']);
  state.markChangesSeen();
  assert.deepEqual([...state.changedClassKeys], []);
});

test('the change log and what was seen survive a reload', () => {
  const state = stateOf('COMP 1601');
  state.recordChanges({ toPublication: 11, lines: LINES });
  const saved = JSON.parse(JSON.stringify(state.toSaved()));
  const reloaded = new TimetableState({ courses: saved.courses }, saved);
  assert.equal(reloaded.unseenChanges.lines[0].text, LINES[0].text);

  reloaded.markChangesSeen();
  const again = new TimetableState({ courses: saved.courses }, JSON.parse(JSON.stringify(reloaded.toSaved())));
  assert.equal(again.unseenChanges, null);
});

test('a republish that changed nothing for the student records nothing', () => {
  const state = stateOf('COMP 1601');
  state.recordChanges({ toPublication: 11, lines: [] });
  assert.equal(state.changeLog, null);
});

test('undo does not bring back an old change notice', () => {
  const state = stateOf('COMP 1601');
  state.recordChanges({ toPublication: 11, lines: LINES });
  state.markChangesSeen();
  state.removeCourse('COMP 1601');
  state.undo();
  assert.equal(state.unseenChanges, null);
});
