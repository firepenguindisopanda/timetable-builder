'use strict';

/**
 * Reading a timetable saved by an older version of the page.
 *
 * The rule this suite exists to protect: a student with no network and a saved
 * timetable keeps working. Every reader below is one they might still be on.
 */

const test = require('node:test');
const assert = require('node:assert');
const { load, course } = require('./harness.js');

const api = load(
  'calendar-utils.js',
  'option-groups.js',
  'placement.js',
  'timetable-state.js'
);
const {
  TimetableState,
  migrateV1toV2,
  migrateV2toV3,
  readSavedState,
  writeSavedState,
} = api.take(
  'TimetableState',
  'migrateV1toV2',
  'migrateV2toV3',
  'readSavedState',
  'writeSavedState'
);

/** localStorage, near enough, and able to refuse. */
function fakeStorage(initial) {
  const data = { ...(initial || {}) };
  return {
    full: false,
    getItem(key) {
      return key in data ? data[key] : null;
    },
    setItem(key, value) {
      if (this.full) {
        const error = new Error('quota');
        error.name = 'QuotaExceededError';
        throw error;
      }
      data[key] = value;
    },
    _raw: data,
  };
}

/**
 * A v2 payload of the shape the page used to write, built from real COMP 1601
 * sessions so the streams are ones the grouping rules actually meet.
 */
function v2Payload() {
  const real = course('COMP 1601');
  const streams = real.sessions.map((s) => ({
    streamId: api.get('computeStreamId')(
      s.type,
      s.day,
      s.startTime,
      s.endTime,
      s.streamLabel
    ),
    type: s.type,
    typeKey: s.type,
    day: s.day,
    startTime: s.startTime,
    endTime: s.endTime,
    room: s.room,
    staff: null,
    groupLabel: s.streamLabel,
    weeks: s.weeksRaw,
    weekCount: null,
  }));

  return {
    version: 2,
    sourceData: {
      courses: [
        {
          courseId: 'COMP-1601-COMPUTER-PROGRAMMING-I',
          title: 'COMP 1601, Computer Programming I',
          sourceFile: 'm104178.pdf',
          streams,
        },
      ],
    },
    scheduleState: {
      placements: [
        {
          courseId: 'COMP-1601-COMPUTER-PROGRAMMING-I',
          streamType: 'Lecture',
          selectedStreamId: streams.find((s) => s.type === 'Lecture').streamId,
        },
        {
          courseId: 'COMP-1601-COMPUTER-PROGRAMMING-I',
          streamType: 'Lab',
          selectedStreamId: streams.find((s) => s.type === 'Lab').streamId,
        },
      ],
      history: [],
      future: [],
    },
    savedAt: '2026-08-01T10:00:00.000Z',
  };
}

// v2 to v3


test('a v2 timetable migrates without losing a placement', () => {
  const v2 = v2Payload();

  const v3 = migrateV2toV3(v2);

  assert.equal(v3.version, 3);
  assert.equal(v3.placements.length, 2);
  assert.equal(v3.courses.length, 1);
});

test('migration keeps the exact classes that were placed', () => {
  const v2 = v2Payload();
  const wanted = v2.scheduleState.placements.map((p) => p.selectedStreamId);

  const v3 = migrateV2toV3(v2);
  const state = new TimetableState({ courses: v3.courses }, v3);
  const placed = state
    .getPlacedEvents()
    .map((e) => state.getPlacedEventDetails(e.groupId).streamId);

  assert.deepEqual(placed.sort(), wanted.sort());
});

test('a migrated course is keyed on its code, not its title', () => {
  const v3 = migrateV2toV3(v2Payload());

  assert.equal(v3.courses[0].courseKey, 'COMP 1601');
  assert.equal(v3.courseKeys[0], 'COMP 1601');
});

test('a migrated course is still marked as uploaded', () => {
  const v3 = migrateV2toV3(v2Payload());

  assert.equal(v3.courses[0].origin, 'upload');
  assert.equal(v3.courses[0].sourceFile, 'm104178.pdf');
});

test('migrated placements are left unpinned so re-optimise can still work', () => {
  const v3 = migrateV2toV3(v2Payload());

  assert.ok(v3.placements.every((p) => p.pinned === false));
});

test('every migrated placement points at a group that exists', () => {
  const v3 = migrateV2toV3(v2Payload());
  const state = new TimetableState({ courses: v3.courses }, v3);
  const ids = new Set(state.optionGroups.map((g) => g.groupId));

  assert.ok(v3.placements.every((p) => ids.has(p.groupId)));
});

test('two v2 placements of one type collapse into the group that holds them', () => {
  /**
   * v2 allowed one placement per (course, type). COMP 1601's ten labs are one
   * menu in v3, so the lab placement has to land on that single group rather
   * than inventing one per stream.
   */
  const v3 = migrateV2toV3(v2Payload());
  const labs = v3.placements.filter((p) => p.groupId.includes('|Lab|'));

  assert.equal(labs.length, 1);
  assert.equal(labs[0].groupId, 'COMP 1601|Lab|all');
});

test('a v2 payload with nothing in it migrates to nothing, not a crash', () => {
  assert.equal(migrateV2toV3(null), null);
  assert.equal(migrateV2toV3({ version: 2, sourceData: { courses: [] } }), null);
});

// v1, still read


test('a v1 payload still loads, through v2', () => {
  const v1 = {
    results: [
      {
        course_title: 'COMP 1601, Computer Programming I',
        source_file: 'm104178.pdf',
        entries: [
          { type: 'Lecture', day: 'Monday', start_time: '12:00', end_time: '13:00', room: 'TLC LT A1', weeks: 'W1-W12' },
          { type: 'Lab', day: 'Wednesday', start_time: '13:00', end_time: '15:00', room: 'FST CSL1', weeks: 'W1-W12' },
        ],
      },
    ],
    calendar_events: [
      { course: 'COMP 1601, Computer Programming I', type: 'Lecture', day: 'Monday', start_time: '12:00', end_time: '13:00' },
    ],
  };

  const v3 = migrateV2toV3(migrateV1toV2(v1));

  assert.equal(v3.version, 3);
  assert.equal(v3.courses[0].courseKey, 'COMP 1601');
  assert.equal(v3.placements.length, 1);
});

// Choosing which reader to use


test('a v3 payload is read as it stands', () => {
  const v3 = migrateV2toV3(v2Payload());
  const storage = fakeStorage({ celcat_timetable_v3: JSON.stringify(v3) });

  const loaded = readSavedState(storage);

  assert.equal(loaded.version, 3);
  assert.equal(loaded.placements.length, 2);
});

test('a v2 payload is upgraded on the way in', () => {
  const storage = fakeStorage({
    celcat_timetable_v2: JSON.stringify(v2Payload()),
  });

  const loaded = readSavedState(storage);

  assert.equal(loaded.version, 3);
  assert.equal(loaded.courses[0].courseKey, 'COMP 1601');
});

test('v3 wins when both are present', () => {
  const v3 = migrateV2toV3(v2Payload());
  v3.placements = [];
  const storage = fakeStorage({
    celcat_timetable_v3: JSON.stringify(v3),
    celcat_timetable_v2: JSON.stringify(v2Payload()),
  });

  assert.equal(readSavedState(storage).placements.length, 0);
});

test('nothing saved reads as nothing', () => {
  assert.equal(readSavedState(fakeStorage()), null);
});

test('a corrupted payload is ignored rather than thrown', () => {
  const storage = fakeStorage({ celcat_timetable_v3: '{not json' });

  assert.equal(readSavedState(storage), null);
});

// Saving


test('saving round trips', () => {
  const state = new TimetableState(
    TimetableState.fromWarehouseResponse({
      publicationId: 1,
      courses: [course('COMP 1602')],
    })
  );
  state.placeMissing();
  const storage = fakeStorage();

  assert.deepEqual(writeSavedState(state.toSaved(), storage), { ok: true });
  const loaded = readSavedState(storage);

  assert.equal(loaded.publicationId, 1);
  assert.deepEqual(loaded.placements, state.placements);
});

test('a full browser is reported rather than logged and forgotten', () => {
  const storage = fakeStorage();
  storage.full = true;

  const result = writeSavedState({ version: 3 }, storage);

  assert.equal(result.ok, false);
  assert.match(result.error, /no room left/);
});

test('a browser that stores nothing at all is reported too', () => {
  const result = writeSavedState({ version: 3 }, null);

  assert.equal(result.ok, false);
  assert.ok(result.error);
});

test('the publication is saved, so a reload can spot a republish', () => {
  const state = new TimetableState(
    TimetableState.fromWarehouseResponse({
      publicationId: 7,
      courses: [course('COMP 1602')],
    })
  );

  assert.equal(state.toSaved().publicationId, 7);
});

// An upload whose title carries no code the reader recognises

/**
 * What /extract saves for LAW 0101 (downloaded_pdfs/m103865.pdf), trimmed.
 * The "Course timetable - " prefix is how CELCAT titles the PDF, and it is
 * why no code is found: the key has to come from the title instead.
 */
function lawUploadV1() {
  return {
    extractedAt: '2026-09-23T04:00:00.000Z',
    results: [
      {
        course_title: 'Course timetable - LAW 0101, Introduction to Commonwealth Caribbean Legal Systems (Wks W3-W12)',
        source_file: 'm103865.pdf',
        entries: [
          { type: 'Lecture', day: 'Tuesday', start_time: '10:00', end_time: '12:00', room: 'FFA B', weeks: 'W3-W12' },
          { type: 'Tutorial', day: 'Tuesday', start_time: '15:00', end_time: '16:00', room: 'FFA B', weeks: 'W3-W12' },
          { type: 'Tutorial', day: 'Friday', start_time: '13:00', end_time: '14:00', room: 'TCB 31', weeks: 'W3-W12' },
        ],
      },
    ],
    total_files: 1,
    total_entries: 3,
  };
}

const LAW_KEY = 'COURSE-TIMETABLE---LAW-0101-INTRODUCTION-TO-COMMONWEALTH-CARIBBEAN-LEGAL-SYSTEMS-WKS-W3-W12';

test('an upload with no recognisable code keeps the key the extract reader gave it', () => {
  const v3 = migrateV2toV3(migrateV1toV2(lawUploadV1()));

  assert.equal(v3.courses[0].courseKey, LAW_KEY);
  assert.deepEqual(v3.courseKeys, [LAW_KEY]);
});

test('an uploaded course is still on the timetable after a save and a reload', () => {
  const first = readSavedState(fakeStorage({ celcat_timetable_data: JSON.stringify(lawUploadV1()) }));
  const state = new TimetableState({ courses: first.courses }, first);
  state.placeMissing();
  const placedBefore = state.getPlacedEvents().length;

  // What the page does: save through JSON, then read it back on the next load.
  const storage = fakeStorage({ celcat_timetable_v3: JSON.stringify(state.toSaved()) });
  const saved = readSavedState(storage);
  const reloaded = new TimetableState({ courses: saved.courses }, saved);
  reloaded.pruneDanglingPlacements();
  reloaded.placeMissing();

  assert.equal(placedBefore, 2);
  assert.equal(reloaded.getPlacedEvents().length, 2);
  assert.ok(reloaded.getPlacedEvents().every(e => e.groupId.startsWith(LAW_KEY + '|')));
});

/**
 * A v3 timetable saved while the bug was live: the course lost its key to
 * JSON, courseKeys holds the null that undefined became, and the placements
 * name groups under "undefined". The student had dragged the tutorial.
 */
function savedWithLostKey() {
  const v3 = migrateV2toV3(migrateV1toV2(lawUploadV1()));
  const course = { ...v3.courses[0] };
  delete course.courseKey;
  const tutorials = course.sessions.filter(s => s.type === 'Tutorial');
  return JSON.parse(JSON.stringify({
    ...v3,
    courses: [course],
    courseKeys: [null],
    placements: [
      { groupId: 'undefined|Lecture|all', selectedSessionId: course.sessions[0].sessionId, pinned: false },
      { groupId: 'undefined|Tutorial|all', selectedSessionId: tutorials[1].sessionId, pinned: true },
    ],
  }));
}

test('a timetable saved with the lost key loads with its uploaded course back on it', () => {
  const saved = readSavedState(fakeStorage({ celcat_timetable_v3: JSON.stringify(savedWithLostKey()) }));
  const state = new TimetableState({ courses: saved.courses }, saved);
  state.pruneDanglingPlacements();
  state.placeMissing();

  assert.equal(saved.courses[0].courseKey, LAW_KEY);
  assert.deepEqual(saved.courseKeys, [LAW_KEY]);
  assert.equal(state.getPlacedEvents().length, 2);
});

test('repairing the lost key keeps the class the student placed by hand', () => {
  const saved = readSavedState(fakeStorage({ celcat_timetable_v3: JSON.stringify(savedWithLostKey()) }));
  const state = new TimetableState({ courses: saved.courses }, saved);
  state.pruneDanglingPlacements();

  const tutorial = state.getPlacedEvents().find(e => e.type === 'Tutorial');
  assert.equal(tutorial.day, 'Friday');
  assert.equal(tutorial.pinned, true);
});

test('a v3 timetable with every key intact is returned untouched', () => {
  const intact = migrateV2toV3(migrateV1toV2(lawUploadV1()));
  const raw = JSON.stringify(intact);

  assert.equal(JSON.stringify(readSavedState(fakeStorage({ celcat_timetable_v3: raw }))), raw);
});

test('a course the student removed while its key was lost stays removed once repaired', () => {
  // Removing it filtered undefined out of courseKeys, so no null is left behind.
  const removed = { ...savedWithLostKey(), courseKeys: [], placements: [] };
  const saved = readSavedState(fakeStorage({ celcat_timetable_v3: JSON.stringify(removed) }));
  const state = new TimetableState({ courses: saved.courses }, saved);
  state.placeMissing();

  assert.equal(saved.courses[0].courseKey, LAW_KEY);
  assert.deepEqual(saved.courseKeys, []);
  assert.equal(state.getPlacedEvents().length, 0);
});
