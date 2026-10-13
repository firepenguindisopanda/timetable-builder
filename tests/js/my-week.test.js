'use strict';

/**
 * What a student's week adds up to: the summary above the grid.
 */

const test = require('node:test');
const assert = require('node:assert');
const { load } = require('./harness.js');

const api = load('calendar-utils.js', 'my-week.js');
const { weekSummary, weekSummaryLine, weekSummaryDetails, buildingOf } =
  api.take('weekSummary', 'weekSummaryLine', 'weekSummaryDetails', 'buildingOf');

function cls(day, startTime, endTime, room, label = 'COMP 2601') {
  return { day, startTime, endTime, room, label };
}

test('contact hours add up the week', () => {
  const s = weekSummary([cls('Monday', '09:00', '11:00', 'TLC LT E'), cls('Wednesday', '14:00', '15:00', 'FST C1')]);
  assert.equal(s.contactMins, 180);
});

test('two clashing classes are not counted twice', () => {
  // COMP 2602 2-4pm and HIST 1306 3-5pm on Monday is three hours, not four.
  const s = weekSummary([cls('Monday', '14:00', '16:00', 'TLC LT E'), cls('Monday', '15:00', '17:00', 'FHE RM 229')]);
  assert.equal(s.contactMins, 180);
});

test('a gap of two hours or more is time to use', () => {
  const s = weekSummary([cls('Monday', '09:00', '10:00', 'TLC'), cls('Monday', '12:00', '13:00', 'TLC'),
    cls('Monday', '13:30', '14:30', 'TLC')]);
  assert.deepEqual(s.days[0].gaps, [{ from: 600, to: 720 }]);
});

test('a day of eight hours or more, first class to last, is long', () => {
  const s = weekSummary([cls('Tuesday', '08:00', '09:00', 'FST'), cls('Tuesday', '15:00', '16:00', 'FST'),
    cls('Thursday', '09:00', '10:00', 'FST')]);
  assert.deepEqual(s.longDays.map((d) => d.day), ['Tuesday']);
});

test('earliest start, latest finish and free weekdays', () => {
  const s = weekSummary([cls('Tuesday', '08:00', '09:00', 'FST'), cls('Monday', '19:00', '20:00', 'FST')]);
  assert.deepEqual(s.earliest, { day: 'Tuesday', mins: 480 });
  assert.deepEqual(s.latest, { day: 'Monday', mins: 1200 });
  assert.deepEqual(s.freeWeekdays, ['Wednesday', 'Thursday', 'Friday']);
});

test('back to back in different buildings is a dash across campus', () => {
  const s = weekSummary([cls('Monday', '12:00', '14:00', 'FST CSL1', 'COMP 2611'),
    cls('Monday', '14:00', '16:00', 'TLC LT E', 'COMP 2602')]);
  assert.deepEqual(s.backToBack, [{ day: 'Monday', at: 840, fromLabel: 'COMP 2611', toLabel: 'COMP 2602',
    fromBuilding: 'FST', toBuilding: 'TLC' }]);
});

test('back to back in the same building, or remote, raises nothing', () => {
  const same = weekSummary([cls('Monday', '12:00', '14:00', 'FST CSL1'), cls('Monday', '14:00', '15:00', 'FST C2')]);
  const remote = weekSummary([cls('Monday', '12:00', '14:00', 'FST CSL1'), cls('Monday', '14:00', '15:00', 'Remote Teaching')]);
  assert.deepEqual(same.backToBack, []);
  assert.deepEqual(remote.backToBack, []);
});

test('buildings come from the room code, and an unknown one has none', () => {
  assert.equal(buildingOf('FHE SOE N 12'), 'FHE');
  assert.equal(buildingOf('Eng MD3'), 'ENG');
  assert.equal(buildingOf('Daaga Auditorium'), 'DAAGA');
  assert.equal(buildingOf('ENG MD3; JFK LT'), 'ENG', 'a split class is in its first room');
  assert.equal(buildingOf('Venue to be advised'), null);
  assert.equal(buildingOf(null), null);
});

test('the one-line summary answers how heavy the week is', () => {
  const s = weekSummary([cls('Monday', '08:00', '10:00', 'FST'), cls('Monday', '15:00', '17:00', 'FST'),
    cls('Tuesday', '09:00', '10:00', 'FST'), cls('Thursday', '13:00', '14:30', 'FST')]);
  assert.equal(weekSummaryLine(s), '6.5 contact hours · 1 long day · earliest 8am Mon · free Wed, Fri');
});

test('the details walk the week a day at a time', () => {
  const s = weekSummary([cls('Monday', '08:00', '10:00', 'FST CSL1', 'COMP 2611'),
    cls('Monday', '13:00', '14:00', 'FST C1', 'COMP 2601'), cls('Monday', '14:00', '15:00', 'TLC LT E', 'COMP 2602')]);
  assert.deepEqual(weekSummaryDetails(s), [
    'Monday: 8am–3pm, 4h of class; free 10am–1pm.',
    'Monday 2pm: COMP 2601 in Science & Technology runs straight into COMP 2602 in Teaching & Learning Complex.',
    'Latest finish: 3pm on Monday.',
  ]);
});

test('an empty week says nothing', () => {
  assert.equal(weekSummaryLine(weekSummary([])), '');
  assert.deepEqual(weekSummaryDetails(weekSummary([])), []);
});

// What another time would do

const { optionEffect, optionEffectText } = api.take('optionEffect', 'optionEffectText');

test('another time that runs into a class says which', () => {
  const others = [{ ...cls('Monday', '14:00', '16:00', 'TLC LT E', 'COMP 2602 Lecture'), weeks: [1, 2, 3] }];
  const effect = optionEffect({ ...cls('Monday', '15:00', '17:00', 'FST'), weeks: [2] }, others);
  assert.deepEqual(effect.clashes, ['COMP 2602 Lecture']);
  assert.match(optionEffectText(effect), /^Clashes with COMP 2602 Lecture/);
});

test('times that never share a week are no clash, as the clash panel counts', () => {
  const others = [{ ...cls('Monday', '14:00', '16:00', 'TLC', 'COMP 2602 Lecture'), weeks: [1, 3, 5] }];
  const effect = optionEffect({ ...cls('Monday', '15:00', '17:00', 'FST'), weeks: [2, 4] }, others);
  assert.deepEqual(effect.clashes, []);
});

test('it says how long that day would run', () => {
  const others = [cls('Tuesday', '09:00', '10:00', 'TLC', 'COMP 2611 Lecture')];
  assert.equal(optionEffectText(optionEffect(cls('Tuesday', '17:00', '19:00', 'FST'), others)),
    'No clash \u00b7 Tuesday would run 9am\u20137pm');
});

test('a day with nothing else on says so', () => {
  assert.equal(optionEffectText(optionEffect(cls('Wednesday', '09:00', '11:00', 'FST'), [])),
    'No clash \u00b7 the only class on Wednesday');
});
