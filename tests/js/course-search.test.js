'use strict';

/**
 * Finding a course by typing at it.
 *
 * The index rows here are the ones `/explore/courses.json` serves, so the
 * fields are the real ones and the codes are the awkward real spellings.
 */

const test = require('node:test');
const assert = require('node:assert');
const { load } = require('./harness.js');

const api = load('course-search.js');
const { searchCourses, courseMatchesQuery, weeksFromMask, weekMaskLabel } =
  api.take('searchCourses', 'courseMatchesQuery', 'weeksFromMask', 'weekMaskLabel');

/** A handful of real index rows, trimmed to the fields search reads. */
const INDEX = [
  {
    code: 'COMP 1601', title: 'Computer Programming I',
    faculty: 'Science & Technology', department: 'DCIT',
    rooms: ['FST CSL1', 'TLC LT A1'], staff: ['GOODRIDGE,Wayne'],
    days: ['Monday', 'Tuesday'], sessions: 15, weeks: 0xfff,
  },
  {
    code: 'COMP 1602', title: 'Computer Programming II',
    faculty: 'Science & Technology', department: 'DCIT',
    rooms: ['FST CSL2'], staff: [], days: ['Wednesday'], sessions: 4, weeks: 0xfff,
  },
  {
    code: 'BIOL 1262', title: 'Living Organisms I',
    faculty: 'Science & Technology', department: 'Life Sciences',
    rooms: ['FST LS1'], staff: [], days: ['Monday'], sessions: 24,
    weeks: 0b101010101010,
  },
  {
    code: 'WW101', title: 'Workshop Week', faculty: null, department: null,
    rooms: [], staff: [], days: ['Friday'], sessions: 2, weeks: 0b11,
  },
  {
    code: 'FOUN 1001 (FULL & PART-TIME)', title: 'Caribbean Civilisation',
    faculty: 'Humanities & Education', department: 'History',
    rooms: [], staff: [], days: ['Monday'], sessions: 52, weeks: 0xfff,
  },
];

// Matching


test('a course is found by its code', () => {
  assert.deepEqual(
    searchCourses(INDEX, 'COMP 1601').map(c => c.code),
    ['COMP 1601']
  );
});

test('the space in a code is optional, because nobody types it', () => {
  assert.deepEqual(searchCourses(INDEX, 'comp1601').map(c => c.code), ['COMP 1601']);
});

test('a course is found by its title', () => {
  assert.deepEqual(
    searchCourses(INDEX, 'living organisms').map(c => c.code),
    ['BIOL 1262']
  );
});

test('a course is found by its lecturer', () => {
  assert.deepEqual(searchCourses(INDEX, 'goodridge').map(c => c.code), ['COMP 1601']);
});

test('a course is found by a room it uses', () => {
  assert.deepEqual(searchCourses(INDEX, 'FST LS1').map(c => c.code), ['BIOL 1262']);
});

test('words narrow the search rather than widening it', () => {
  // "comp programming" must not also return everything matching either word.
  const codes = searchCourses(INDEX, 'comp programming').map(c => c.code);
  assert.deepEqual(codes, ['COMP 1601', 'COMP 1602']);
});

test('a code with punctuation in it is still findable', () => {
  assert.deepEqual(
    searchCourses(INDEX, 'foun 1001').map(c => c.code),
    ['FOUN 1001 (FULL & PART-TIME)']
  );
});

test('a code with no space at all is findable', () => {
  assert.deepEqual(searchCourses(INDEX, 'ww101').map(c => c.code), ['WW101']);
});

test('an empty query returns everything, in index order', () => {
  assert.equal(searchCourses(INDEX, '').length, INDEX.length);
  assert.equal(searchCourses(INDEX, '   ').length, INDEX.length);
});

test('nothing matching returns nothing', () => {
  assert.deepEqual(searchCourses(INDEX, 'astrophysics'), []);
});

test('a course with no faculty or department does not break matching', () => {
  assert.equal(courseMatchesQuery(INDEX[3], 'workshop'), true);
});

// Ranking


test('an exact code beats a course that merely mentions it', () => {
  const withMention = [
    { code: 'ZZZZ 9999', title: 'Reading COMP 1601 for beginners', rooms: [], staff: [] },
    ...INDEX,
  ];

  assert.equal(searchCourses(withMention, 'COMP 1601')[0].code, 'COMP 1601');
});

test('a code prefix beats a title match', () => {
  const ranked = searchCourses(INDEX, 'comp').map(c => c.code);

  assert.deepEqual(ranked.slice(0, 2), ['COMP 1601', 'COMP 1602']);
});

test('the limit caps how many come back but not how many matched', () => {
  assert.equal(searchCourses(INDEX, '', 2).length, 2);
  assert.equal(searchCourses(INDEX, '').length, INDEX.length);
});

// Reading a pasted list


const parseCourseCodeList = api.get('parseCourseCodeList');

function parse(text) {
  return parseCourseCodeList(text, INDEX);
}

test('a comma separated list is read', () => {
  assert.deepEqual(parse('COMP 1601, COMP 1602, BIOL 1262').codes, [
    'COMP 1601',
    'COMP 1602',
    'BIOL 1262',
  ]);
});

test('a list off a screenshot, one code a line, is read', () => {
  const pasted = 'COMP 1601\nCOMP 1602\nBIOL 1262\n';

  assert.deepEqual(parse(pasted).codes, ['COMP 1601', 'COMP 1602', 'BIOL 1262']);
});

test('codes run together with spaces are separated', () => {
  assert.deepEqual(parse('COMP1601 COMP1602 WW101').codes, [
    'COMP 1601',
    'COMP 1602',
    'WW101',
  ]);
});

test('a code that contains a space is not torn in half', () => {
  /**
   * The reason whitespace cannot simply be a separator. Splitting on it would
   * turn one published course into two unrecognised fragments.
   */
  assert.deepEqual(parse('FOUN 1001 (FULL & PART-TIME)').codes, [
    'FOUN 1001 (FULL & PART-TIME)',
  ]);
});

test('a code with a space survives alongside others on one line', () => {
  const result = parse('COMP1601 FOUN 1001 (FULL & PART-TIME) BIOL1262');

  assert.deepEqual(result.codes, [
    'COMP 1601',
    'FOUN 1001 (FULL & PART-TIME)',
    'BIOL 1262',
  ]);
  assert.deepEqual(result.unknown, []);
});

test('capitalisation and stray spacing do not matter', () => {
  assert.deepEqual(parse('  comp   1601 ,  Biol1262 ').codes, [
    'COMP 1601',
    'BIOL 1262',
  ]);
});

test('the same course listed twice is added once', () => {
  assert.deepEqual(parse('COMP 1601, comp1601, COMP1601').codes, ['COMP 1601']);
});

test('junk is reported rather than silently swallowed', () => {
  const result = parse('COMP 1601\nmy timetable\nBIOL 1262\nCOMP 9999');

  assert.deepEqual(result.codes, ['COMP 1601', 'BIOL 1262']);
  assert.deepEqual(result.unknown, ['my timetable', 'COMP 9999']);
});

test('a stray sentence is one complaint, not one per word', () => {
  // The line a student leaves at the top of a pasted list.
  const result = parse('my sem 1 courses:\nCOMP1601\nBIOL1262');

  assert.deepEqual(result.codes, ['COMP 1601', 'BIOL 1262']);
  assert.deepEqual(result.unknown, ['my sem 1 courses:']);
});

test('junk between two codes on one line does not swallow either', () => {
  const result = parse('COMP1601 and also BIOL1262');

  assert.deepEqual(result.codes, ['COMP 1601', 'BIOL 1262']);
  assert.deepEqual(result.unknown, ['and also']);
});

test('a course the warehouse does not publish is called out', () => {
  const result = parse('COMP 1601, PSYC 9999');

  assert.deepEqual(result.codes, ['COMP 1601']);
  assert.ok(result.unknown.length);
});

test('semicolons work too, because a spreadsheet paste uses them', () => {
  assert.deepEqual(parse('COMP 1601; BIOL 1262').codes, ['COMP 1601', 'BIOL 1262']);
});

test('an empty paste yields nothing at all, and no complaint', () => {
  assert.deepEqual(parse(''), { codes: [], unknown: [] });
  assert.deepEqual(parse('  \n , ; \n '), { codes: [], unknown: [] });
});

test('blank lines between codes are ignored', () => {
  assert.deepEqual(parse('COMP 1601\n\n\nBIOL 1262').codes, [
    'COMP 1601',
    'BIOL 1262',
  ]);
});

// The week meter


test('a bitmask unpacks to the weeks it stands for', () => {
  // The fortnightly pattern the corpus is full of.
  assert.deepEqual(weeksFromMask(0b101010101010), [2, 4, 6, 8, 10, 12]);
  assert.deepEqual(weeksFromMask(0xfff), [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]);
});

test('a course with no weeks recorded says so rather than showing nothing', () => {
  assert.equal(weekMaskLabel(0), 'No teaching weeks recorded');
});

test('the meter announces which weeks it lights', () => {
  assert.equal(weekMaskLabel(0b101), 'Runs in weeks 1, 3');
  assert.equal(weekMaskLabel(0b1), 'Runs in week 1');
});
