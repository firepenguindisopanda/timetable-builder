'use strict';

/**
 * The course picker as a drawer (REDESIGN-SPEC.md 5.6).
 */

const test = require('node:test');
const assert = require('node:assert');
const { load } = require('./harness.js');

const api = load('picker-drawer.js');
const bindPickerDrawer = api.get('bindPickerDrawer');

function fake(doc, id, attrs = {}) {
  return {
    id,
    hidden: false,
    shown: true,
    listeners: {},
    attrs,
    hasAttribute(name) { return name in this.attrs; },
    addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); },
    focus() { doc.activeElement = this; },
  };
}

function setup() {
  const doc = {
    activeElement: null,
    listeners: {},
    elements: {},
    getElementById(id) { return this.elements[id] || null; },
    addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); },
    key(key) { for (const fn of this.listeners.keydown || []) fn({ key }); },
  };
  for (const id of ['addCoursesBtn', 'choosePicker', 'pickerQuery']) {
    doc.elements[id] = fake(doc, id);
  }
  const drawer = fake(doc, 'pickerDrawer');
  drawer.hidden = true;
  const backdrop = fake(doc, 'backdrop', { 'data-drawer-close': '' });
  const panel = fake(doc, 'panel');
  const calls = [];
  const control = bindPickerDrawer(drawer, {
    doc,
    hold: (el) => calls.push('hold:' + el.id),
    release: () => calls.push('release'),
    canFocus: (el) => el.shown,
    onOpen: () => { calls.push('onOpen'); doc.elements.pickerQuery.focus(); },
    onClose: () => calls.push('onClose'),
  });
  const clickOn = (target) => { for (const fn of drawer.listeners.click || []) fn({ target }); };
  return { doc, drawer, backdrop, panel, calls, control, clickOn };
}

test('opening shows the drawer, holds the page and focuses the search', () => {
  const { doc, drawer, calls, control } = setup();
  control.open(doc.elements.addCoursesBtn);
  assert.strictEqual(drawer.hidden, false);
  assert.strictEqual(control.isOpen(), true);
  assert.deepStrictEqual(calls, ['hold:pickerDrawer', 'onOpen']);
  assert.strictEqual(doc.activeElement.id, 'pickerQuery');
});

test('opening twice holds the page once and keeps the first opener', () => {
  const { doc, calls, control } = setup();
  control.open(doc.elements.addCoursesBtn);
  control.open(doc.elements.choosePicker);
  assert.deepStrictEqual(calls, ['hold:pickerDrawer', 'onOpen', 'onOpen']);
  control.close();
  assert.strictEqual(doc.activeElement.id, 'addCoursesBtn');
});

test('closing releases the page and returns focus to the opener', () => {
  const { doc, drawer, calls, control } = setup();
  control.open(doc.elements.addCoursesBtn);
  control.close();
  assert.strictEqual(drawer.hidden, true);
  assert.deepStrictEqual(calls.slice(2), ['release', 'onClose']);
  assert.strictEqual(doc.activeElement.id, 'addCoursesBtn');
});

test('opened from the first visit, focus falls back once that button is gone', () => {
  const { doc, control } = setup();
  control.open(doc.elements.choosePicker);
  // A course was added: the first-visit block hides and the toolbar shows.
  doc.elements.choosePicker.shown = false;
  control.close();
  assert.strictEqual(doc.activeElement.id, 'addCoursesBtn');
});

test('Esc closes it; Esc with it closed does nothing', () => {
  const { doc, calls, control } = setup();
  doc.key('Escape');
  assert.deepStrictEqual(calls, []);
  control.open(doc.elements.addCoursesBtn);
  doc.key('Enter');
  assert.strictEqual(control.isOpen(), true);
  doc.key('Escape');
  assert.strictEqual(control.isOpen(), false);
});

test('a click on the backdrop closes it, a click in the panel does not', () => {
  const { doc, backdrop, panel, control, clickOn } = setup();
  control.open(doc.elements.addCoursesBtn);
  clickOn(panel);
  assert.strictEqual(control.isOpen(), true);
  clickOn(backdrop);
  assert.strictEqual(control.isOpen(), false);
});

test('closing a closed drawer is a no-op', () => {
  const { calls, control } = setup();
  control.close();
  assert.deepStrictEqual(calls, []);
});
