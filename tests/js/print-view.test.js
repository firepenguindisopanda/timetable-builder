'use strict';

/**
 * The markup of the printed page.
 *
 * The renderer makes no decisions, so these check the two things it can get
 * wrong: losing something the model carried, and letting a course title reach
 * the page unescaped.
 */

const test = require('node:test');
const assert = require('node:assert');
const { load, course, warehouse } = require('./harness.js');

const api = load('calendar-utils.js', 'print-model.js', 'print-view.js');
const {
  renderPrintView,
  escapePrint,
  fillClass,
  hueFor,
  buildPrintModel,
  PRINT_PALETTE,
} = api.take(
  'renderPrintView',
  'escapePrint',
  'fillClass',
  'hueFor',
  'buildPrintModel',
  'PRINT_PALETTE'
);

function event(fields) {
  return {
    courseKey: 'COMP 1601',
    courseTitle: 'Computer Programming I',
    type: 'Lecture',
    day: 'Monday',
    startTime: '09:00',
    endTime: '11:00',
    room: 'SB1',
    staff: [],
    streamLabel: null,
    weeks: null,
    ...fields,
  };
}

function render(input) {
  return renderPrintView(buildPrintModel(input || {}));
}

// Escaping

test('a course title with markup in it cannot reach the page as markup', () => {
  assert.equal(
    escapePrint('<script>alert(1)</script>'),
    '&lt;script&gt;alert(1)&lt;/script&gt;'
  );
});

test('quotes are escaped, because titles are written into attributes too', () => {
  assert.equal(escapePrint(`"O'Brien" & co`), '&quot;O&#39;Brien&quot; &amp; co');
});

test('null and undefined escape to nothing rather than to the word null', () => {
  assert.equal(escapePrint(null), '');
  assert.equal(escapePrint(undefined), '');
});

test('an uploaded course title is escaped in the rendered page', () => {
  /**
   * Titles come out of a PDF an unknown person uploaded, so they are the one
   * thing on the page that is not ours.
   */
  const html = render({
    events: [event({ courseKey: '<b>BAD</b>', courseTitle: '<img src=x>' })],
  });
  assert.ok(!html.includes('<b>BAD</b>'), 'raw markup must not survive');
  assert.ok(!html.includes('<img src=x>'), 'raw markup must not survive');
  assert.ok(html.includes('&lt;b&gt;BAD&lt;/b&gt;'));
});

// Swatches

test('each activity type gets its own fill', () => {
  const fills = ['lecture', 'lab', 'tutorial', 'other'].map(fillClass);
  assert.deepEqual(fills, [
    'pv-fill-solid',
    'pv-fill-hatch',
    'pv-fill-outline',
    'pv-fill-dots',
  ]);
  assert.equal(new Set(fills).size, 4, 'no two types may share a fill');
});

test('an unknown type still gets a fill rather than none', () => {
  assert.equal(fillClass('nonsense'), 'pv-fill-dots');
  assert.equal(fillClass(undefined), 'pv-fill-dots');
});

test('a colour index past the palette wraps instead of producing undefined', () => {
  assert.equal(hueFor(0), PRINT_PALETTE[0].hex);
  assert.equal(hueFor(8), PRINT_PALETTE[0].hex);
  assert.equal(hueFor(-1), PRINT_PALETTE[PRINT_PALETTE.length - 1].hex);
});

// Content

test('an empty timetable renders a page rather than a blank string', () => {
  const html = render({});
  assert.ok(html.includes('pv-sheet'));
  assert.ok(html.includes('Nothing placed yet'));
});

test('a model with no meta renders nothing at all', () => {
  assert.equal(renderPrintView(null), '');
  assert.equal(renderPrintView({}), '');
});

test('every placed class reaches the page', () => {
  const events = [
    event({ day: 'Monday' }),
    event({ day: 'Tuesday', courseKey: 'MATH 1115' }),
    event({ day: 'Friday', courseKey: 'CHEM 1073' }),
  ];
  const html = render({ events });
  const entries = html.match(/class="pv-entry"/g) || [];
  assert.equal(entries.length, 3);
  assert.ok(html.includes('MATH 1115'));
  assert.ok(html.includes('CHEM 1073'));
});

test('the day headings are printed in week order', () => {
  const html = render({
    events: [event({ day: 'Friday' }), event({ day: 'Monday' })],
  });
  assert.ok(html.indexOf('Monday') < html.indexOf('Friday'));
});

test('a missing room leaves no empty separator behind', () => {
  const html = render({ events: [event({ room: null, staff: [], weeks: null })] });
  assert.ok(!html.includes('pv-line-detail'), 'the detail line is dropped whole');
  assert.ok(!html.includes('&middot; &middot;'), 'no orphaned separators');
});

test('a missing room drops only itself, keeping lecturer and weeks', () => {
  // 19 of the fixture's 224 sessions have no room, and the rest of the line
  // is still worth printing.
  const html = render({
    events: [event({ room: null, staff: ['AUSTIN,Nigel'], weeks: [1, 2, 3] })],
  });
  const detail = html.match(/<p class="pv-line-detail">([\s\S]*?)<\/p>/)[1].trim();
  assert.equal(detail, 'Nigel Austin &middot; Wks 1–3');
});

test('a class outside the calendar grid hours still prints', () => {
  /**
   * The grid clamps anything before 08:00 or after 22:00 to its edge and
   * marks it "Runs outside these hours" (E7). A list has no bounds, so the
   * whole failure mode is absent here, which is half the reason the printout
   * is a list.
   */
  const html = render({
    events: [
      event({ startTime: '07:00', endTime: '08:00' }),
      event({ day: 'Tuesday', startTime: '21:00', endTime: '23:00' }),
    ],
  });
  assert.ok(html.includes('07:00–08:00'));
  assert.ok(html.includes('21:00–23:00'));
  assert.ok(!html.includes('outside'), 'nothing is clipped, so nothing is flagged');
});

test('a weekend-only timetable prints the weekend and no empty weekdays', () => {
  const html = render({
    events: [
      event({ day: 'Saturday', type: 'Lab', room: null }),
      event({ day: 'Sunday' }),
    ],
  });
  const days = [...html.matchAll(/class="pv-day-name">([^<]+)</g)].map(m => m[1]);
  assert.deepEqual(days, ['Saturday', 'Sunday']);
});

test('room, lecturer and weeks are joined on one line when all present', () => {
  const html = render({
    events: [event({ room: 'SB1', staff: ['AUSTIN,Nigel'], weeks: [1, 2, 3] })],
  });
  assert.ok(html.includes('SB1 &middot; Nigel Austin &middot; Wks 1–3'));
});

test('a class that sits out part of the semester is emphasised', () => {
  const html = render({
    events: [
      event({ weeks: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12] }),
      event({ day: 'Tuesday', weeks: [7, 8] }),
    ],
  });
  assert.ok(html.includes('<strong class="pv-weeks-odd">Wks 7–8</strong>'));
  assert.ok(
    !html.includes('<strong class="pv-weeks-odd">Wks 1–12</strong>'),
    'a class running the whole semester is not emphasised'
  );
});

test('the lab group label is printed, because it decides which room you go to', () => {
  const html = render({
    events: [event({ type: 'Lab', streamLabel: 'L1' })],
  });
  assert.ok(html.includes('pv-stream'));
  assert.ok(html.includes('L1'));
});

test('the courses block lists every course once and carries the legend', () => {
  const html = render({
    events: [
      event({ courseKey: 'COMP 1601', type: 'Lecture' }),
      event({ courseKey: 'COMP 1601', type: 'Lab', day: 'Tuesday' }),
      event({ courseKey: 'MATH 1115', day: 'Friday' }),
    ],
  });
  const rows = html.match(/class="pv-course"/g) || [];
  assert.equal(rows.length, 2, 'one row per course, not per class');
  assert.ok(html.includes('pv-key'), 'the fill key is on the page');
});

test('a stale course says so on the page', () => {
  const html = render({
    events: [event()],
    courses: [
      { courseKey: 'COMP 1601', title: 'Computer Programming I', stale: true },
    ],
  });
  assert.ok(html.includes('no longer published'));
});

test('an uploaded course says where it came from', () => {
  const html = render({
    events: [event()],
    courses: [{ courseKey: 'COMP 1601', title: null, origin: 'upload' }],
  });
  assert.ok(html.includes('from upload'));
});

test('the header counts what is on the page', () => {
  const html = render({
    events: [event(), event({ day: 'Tuesday', courseKey: 'MATH 1115' })],
    meta: { printedAt: '12 August 2026', publication: 'Semester 1' },
  });
  assert.ok(html.includes('2 courses &middot; 2 classes'));
  assert.ok(html.includes('Printed 12 August 2026'));
  assert.ok(html.includes('Semester 1'));
});

test('one course and one class are counted in the singular', () => {
  const html = render({ events: [event()] });
  assert.ok(html.includes('1 course &middot; 1 class'));
});

test('the typical-week note is always on the page', () => {
  // Without it the reader cannot tell that this is one representative week
  // rather than a specific one.
  assert.ok(render({ events: [event()] }).includes('A typical teaching week'));
});

// Clashes and unplaced

test('no clashes means no clashes section', () => {
  assert.ok(!render({ events: [event()] }).includes('pv-clashes'));
});

test('an unresolved clash is printed with both sides and the weeks', () => {
  const a = event({ day: 'Thursday', startTime: '14:00', endTime: '16:00' });
  const b = event({
    courseKey: 'CHEM 1073', day: 'Thursday', startTime: '15:00', endTime: '17:00',
  });
  const html = render({
    events: [a, b],
    conflicts: [
      { a, b, courseA: 'COMP 1601', courseB: 'CHEM 1073', day: 'Thursday', weeks: [3, 4] },
    ],
  });
  assert.ok(html.includes('Clashes (1)'));
  assert.ok(html.includes('14:00–16:00'));
  assert.ok(html.includes('15:00–17:00'));
  assert.ok(html.includes('Wks 3–4'));
});

test('a class the builder could not place is named on the page', () => {
  const html = render({
    events: [event()],
    unplaced: [{ courseKey: 'MATH 1115', type: 'Tutorial' }],
  });
  assert.ok(html.includes('Not placed (1)'));
  assert.ok(html.includes('MATH 1115'));
});

test('nothing unplaced means no unplaced section', () => {
  assert.ok(!render({ events: [event()] }).includes('pv-unplaced'));
});

// Against real data

test('a real timetable renders every class it was given', () => {
  const events = warehouse.courses.flatMap(c =>
    c.sessions.map(s =>
      event({
        courseKey: c.code,
        courseTitle: c.title,
        type: s.type,
        day: s.day,
        startTime: s.startTime,
        endTime: s.endTime,
        room: s.room || null,
        staff: s.staff,
        streamLabel: s.streamLabel,
        weeks: s.weeks,
      })
    )
  );
  const html = renderPrintView(buildPrintModel({ events }));
  const rendered = (html.match(/class="pv-entry"/g) || []).length;

  assert.equal(rendered, events.length, 'nothing may be lost on the way to paper');
  for (const c of warehouse.courses) {
    assert.ok(html.includes(escapePrint(c.code)), `${c.code} is missing`);
  }
});

test('the rendered page has balanced tags', () => {
  /**
   * A stray unclosed element would take the rest of the sheet inside it and
   * the fault would only show up on paper.
   */
  const events = course('COMP 1601').sessions.map(s =>
    event({
      type: s.type, day: s.day, startTime: s.startTime, endTime: s.endTime,
      room: s.room || null, staff: s.staff, streamLabel: s.streamLabel,
      weeks: s.weeks,
    })
  );
  const html = renderPrintView(buildPrintModel({ events }));

  for (const tag of ['div', 'section', 'ul', 'ol', 'li', 'p', 'span', 'header', 'footer']) {
    const open = (html.match(new RegExp(`<${tag}[\\s>]`, 'g')) || []).length;
    const close = (html.match(new RegExp(`</${tag}>`, 'g')) || []).length;
    assert.equal(open, close, `unbalanced <${tag}>: ${open} open, ${close} closed`);
  }
});
