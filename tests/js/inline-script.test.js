'use strict';

/**
 * The calendar's inline script must at least parse.
 *
 * It is the one block of the page with no tests, and a syntax error in it
 * stops the whole script: no saved timetable loads, no course can be added,
 * and the page looks merely empty. That happened while building the UX plan's
 * phase F (12 Oct 2026): one apostrophe lost its escape, and both suites still
 * passed. Parsing it here makes that a failing test instead of a blank page.
 */

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const TEMPLATE = path.join(__dirname, '..', '..', 'templates', 'calendar.html');

/** The page's inline scripts, with Jinja replaced by what it renders to. */
function inlineScripts() {
  const html = fs.readFileSync(TEMPLATE, 'utf8');
  return [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(([, code]) =>
    code
      .replace(/\{\{[\s\S]*?\}\}/g, 'null')
      .replace(/\{%[\s\S]*?%\}/g, ''));
}

test('the calendar page has its inline script', () => {
  assert.ok(inlineScripts().length >= 1);
});

test('every inline script on the calendar page parses', () => {
  for (const [index, code] of inlineScripts().entries()) {
    assert.doesNotThrow(
      () => new vm.Script(code, { filename: `calendar.html inline script ${index + 1}` }),
      `inline script ${index + 1} does not parse`
    );
  }
});
