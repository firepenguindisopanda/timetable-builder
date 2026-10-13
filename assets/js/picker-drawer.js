'use strict';

/**
 * The course picker as a drawer over the page (REDESIGN-SPEC.md 5.6).
 *
 * The picker was a panel above the grid, so opening it pushed the grid down
 * and a student adding three courses never saw them land. It now opens over
 * the page, which stays in view behind it on a desktop but cannot be reached
 * while it is open.
 *
 * Not a native <dialog> with showModal(), which the spec first proposed: the
 * top layer would sit over the toast stack, and "Added COMP 2601" would be
 * hidden behind the drawer that caused it. The page's own dialog pattern is
 * used instead (`hold` makes everything but the drawer and the toasts
 * inert), as the detail and resolve dialogs already do.
 *
 * The open/close controller lived in the untested inline script, which is
 * where both failures recorded in STATUS.md lived. It is here, and
 * `tests/js/picker-drawer.test.js` pins it, before the markup moves.
 */

//: Where focus goes on close when the button that opened the drawer can no
//: longer take it: opened from the first-visit block, whose button is gone
//: once a course has been added, focus goes to the toolbar's Add courses.
const PICKER_FOCUS_FALLBACKS = ['addCoursesBtn', 'choosePicker'];

/**
 * Bind the drawer. `options`:
 *   doc        the document (a fake in tests)
 *   hold       make the page behind inert; given the drawer
 *   release    undo `hold`
 *   canFocus   whether an element can take focus now (shown, enabled)
 *   onOpen     called after opening, to focus the search box and load
 *   onClose    called after closing, to put the page right behind it
 */
function bindPickerDrawer(drawer, options) {
  const { doc, hold, release, canFocus, onOpen, onClose } = options;
  let opener = null;

  const isOpen = () => !drawer.hidden;

  function open(from) {
    if (!isOpen()) {
      opener = from || null;
      drawer.hidden = false;
      hold(drawer);
    }
    if (onOpen) onOpen();
  }

  function close() {
    if (!isOpen()) return;
    drawer.hidden = true;
    release();
    if (onClose) onClose();
    const back = [opener, ...PICKER_FOCUS_FALLBACKS.map((id) => doc.getElementById(id))]
      .find((el) => el && canFocus(el));
    opener = null;
    if (back) back.focus();
  }

  doc.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && isOpen()) close();
  });

  // The backdrop, not the panel: a click inside the drawer is a click on
  // the picker.
  drawer.addEventListener('click', (event) => {
    if (event.target && event.target.hasAttribute && event.target.hasAttribute('data-drawer-close')) {
      close();
    }
  });

  return { open, close, isOpen };
}
