'use strict';

/**
 * The toolbar's groups and its More menu (REDESIGN-SPEC.md 5.2).
 */

const test = require('node:test');
const assert = require('node:assert');
const { load } = require('./harness.js');

const api = load('more-menu.js');
const toolbarLayout = api.get('toolbarLayout');
const applyToolbarLayout = api.get('applyToolbarLayout');
const bindMoreMenu = api.get('bindMoreMenu');

/** Just enough of an element: children, hidden, attributes, listeners. */
function fakeElement(id, doc) {
  const el = {
    id,
    hidden: false,
    parent: null,
    children: [],
    attrs: {},
    listeners: {},
    getAttribute(name) { return name in this.attrs ? this.attrs[name] : null; },
    setAttribute(name, value) { this.attrs[name] = String(value); },
    addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); },
    appendChild(child) {
      if (child.parent) child.parent.children = child.parent.children.filter((c) => c !== child);
      child.parent = this;
      this.children.push(child);
    },
    contains(other) {
      for (let node = other; node; node = node.parent) if (node === this) return true;
      return false;
    },
    closest(selector) {
      return selector === 'button' && this.isButton ? this : null;
    },
    focus() { doc.activeElement = this; },
    click() {
      // Target first, then bubble, as a browser does.
      for (let node = this; node; node = node.parent) {
        for (const fn of node.listeners.click || []) fn({ target: this });
      }
      for (const fn of doc.listeners.click || []) fn({ target: this });
    },
  };
  return el;
}

function fakeDocument(ids) {
  const doc = {
    activeElement: null,
    listeners: {},
    elements: {},
    getElementById(id) { return this.elements[id] || null; },
    addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); },
    key(key) { for (const fn of this.listeners.keydown || []) fn({ key }); },
  };
  for (const id of ids) {
    const el = fakeElement(id, doc);
    el.isButton = id.endsWith('Btn') || id === 'more';
    doc.elements[id] = el;
  }
  return doc;
}

const BUTTONS = ['addCoursesBtn', 'undoBtn', 'redoBtn', 'icsBtn', 'printBtn',
  'shareBtn', 'clearBtn', 'fullscreenBtn', 'clearAllBtn'];
const GROUPS = ['tbPrimary', 'tbHistory', 'tbOutput', 'moreItems'];

const childIds = (doc, group) => doc.getElementById(group).children.map((c) => c.id);

test('desktop: add, history, output, then the rare ones behind More', () => {
  const doc = fakeDocument([...BUTTONS, ...GROUPS]);
  applyToolbarLayout(toolbarLayout(false), doc);
  assert.deepStrictEqual(childIds(doc, 'tbPrimary'), ['addCoursesBtn']);
  assert.deepStrictEqual(childIds(doc, 'tbHistory'), ['undoBtn', 'redoBtn']);
  assert.deepStrictEqual(childIds(doc, 'tbOutput'), ['icsBtn', 'printBtn', 'shareBtn']);
  assert.deepStrictEqual(childIds(doc, 'moreItems'), ['clearBtn', 'fullscreenBtn']);
});

test('phone: two buttons and More, so the bar is one row', () => {
  const doc = fakeDocument([...BUTTONS, ...GROUPS]);
  applyToolbarLayout(toolbarLayout(true), doc);
  assert.deepStrictEqual(childIds(doc, 'tbPrimary'), ['addCoursesBtn']);
  assert.deepStrictEqual(childIds(doc, 'tbOutput'), ['icsBtn']);
  assert.strictEqual(doc.getElementById('tbHistory').hidden, true);
  assert.deepStrictEqual(childIds(doc, 'moreItems'),
    ['undoBtn', 'redoBtn', 'printBtn', 'shareBtn', 'clearBtn']);
  assert.strictEqual(doc.getElementById('fullscreenBtn').hidden, true);
});

test('back to desktop restores every button, Full screen included', () => {
  const doc = fakeDocument([...BUTTONS, ...GROUPS]);
  applyToolbarLayout(toolbarLayout(true), doc);
  applyToolbarLayout(toolbarLayout(false), doc);
  assert.deepStrictEqual(childIds(doc, 'tbHistory'), ['undoBtn', 'redoBtn']);
  assert.strictEqual(doc.getElementById('tbHistory').hidden, false);
  assert.strictEqual(doc.getElementById('fullscreenBtn').hidden, false);
  assert.deepStrictEqual(childIds(doc, 'moreItems'), ['clearBtn', 'fullscreenBtn']);
});

test('every button is placed or hidden at both widths; none is lost', () => {
  for (const phone of [false, true]) {
    const layout = toolbarLayout(phone);
    const placed = [...GROUPS.flatMap((g) => layout[g]), ...layout.hidden];
    // Clear all is not moved: it sits on its own below a divider in More.
    assert.deepStrictEqual(placed.sort(),
      BUTTONS.filter((b) => b !== 'clearAllBtn').sort(), phone ? 'phone' : 'desktop');
  }
});

function menu() {
  const doc = fakeDocument(['more', 'panel', 'printBtn', 'fullscreenBtn', 'elsewhere', 'exitBtn']);
  const more = doc.getElementById('more');
  const panel = doc.getElementById('panel');
  panel.appendChild(doc.getElementById('printBtn'));
  panel.appendChild(doc.getElementById('fullscreenBtn'));
  const control = bindMoreMenu(more, panel, doc);
  return { doc, more, panel, control };
}

test('starts closed and toggles open and shut', () => {
  const { more, panel, control } = menu();
  assert.strictEqual(more.getAttribute('aria-expanded'), 'false');
  assert.strictEqual(panel.hidden, true);
  more.click();
  assert.strictEqual(control.isOpen(), true);
  assert.strictEqual(panel.hidden, false);
  more.click();
  assert.strictEqual(control.isOpen(), false);
});

test('Esc closes it and puts focus back on More', () => {
  const { doc, more, control } = menu();
  more.click();
  doc.getElementById('printBtn').focus();
  doc.key('Escape');
  assert.strictEqual(control.isOpen(), false);
  assert.strictEqual(doc.activeElement, more);
});

test('choosing an action closes it, and focus is not left on a hidden button', () => {
  const { doc, more, control } = menu();
  more.click();
  const print = doc.getElementById('printBtn');
  print.focus();
  print.click();
  assert.strictEqual(control.isOpen(), false);
  assert.strictEqual(doc.activeElement, more);
});

test('an action that moves focus itself keeps it there', () => {
  const { doc, more, control } = menu();
  const exit = doc.getElementById('exitBtn');
  const fullscreen = doc.getElementById('fullscreenBtn');
  fullscreen.addEventListener('click', () => exit.focus());
  more.click();
  fullscreen.focus();
  fullscreen.click();
  assert.strictEqual(control.isOpen(), false);
  assert.strictEqual(doc.activeElement, exit);
});

test('a click outside closes it without stealing focus', () => {
  const { doc, more, control } = menu();
  more.click();
  const elsewhere = doc.getElementById('elsewhere');
  elsewhere.focus();
  elsewhere.click();
  assert.strictEqual(control.isOpen(), false);
  assert.strictEqual(doc.activeElement, elsewhere);
});
