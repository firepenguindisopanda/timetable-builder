'use strict';

/**
 * Loads the calendar's scripts the way a browser does.
 *
 * `assets/js` is served as plain <script src> tags that share one global
 * scope, in the order calendar.html lists them. Rewriting them as modules so
 * node could require() them would mean the tests exercised a different
 * arrangement from the one students load, so instead they are evaluated in a
 * single vm context here, in the same order, unchanged.
 *
 * Values are read back by name rather than off the context object because a
 * script's top-level `const` binding lives in the global lexical scope and
 * never becomes a property of the global object. `function` declarations do,
 * but reading everything the same way saves remembering which is which.
 */

const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const ASSETS = path.join(__dirname, '..', '..', 'assets', 'js');
const FIXTURE = path.join(__dirname, '..', 'fixtures', 'warehouse_sessions.json');

function load(...scripts) {
  const context = vm.createContext({ console });
  for (const name of scripts) {
    const code = fs.readFileSync(path.join(ASSETS, name), 'utf8');
    vm.runInContext(code, context, { filename: name });
  }
  return {
    get(name) {
      return vm.runInContext(name, context);
    },
    /** Pull several names at once, for destructuring in a test file. */
    take(...names) {
      return Object.fromEntries(names.map((n) => [n, this.get(n)]));
    },
  };
}

/**
 * The captured warehouse response, as `/api/timetable/sessions` returns it.
 *
 * Shared with the Python suite on purpose: one capture, so the two cannot
 * drift into testing different data.
 */
const warehouse = JSON.parse(fs.readFileSync(FIXTURE, 'utf8'));

function course(code) {
  const found = warehouse.courses.find((c) => c.code === code);
  if (!found) {
    throw new Error(
      `no fixture for ${code}; capture it into ${path.basename(FIXTURE)}`
    );
  }
  return found;
}

/** Sessions of one activity type within a fixture course. */
function sessionsOfType(code, type) {
  return course(code).sessions.filter((s) => s.type === type);
}

module.exports = { load, warehouse, course, sessionsOfType };
