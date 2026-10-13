'use strict';

/**
 * The calendar toolbar: which button sits where, and the More menu.
 *
 * Nine buttons of equal weight wrapped to three rows on a phone, with Clear
 * all one row-wrap away from Print (REDESIGN-SPEC.md 5.2). They are grouped
 * by purpose now, and the rare ones live behind More. A phone keeps only
 * what it needs on the bar; Undo moves into More there, because the toast
 * that follows every undoable change already offers it at the moment it is
 * useful.
 *
 * Buttons are moved between groups, never copied, so each keeps its id and
 * its listeners. The calendar binds them once, before any move.
 */

//: Where each button goes. Containers are filled in this order; a button
//: listed under `hidden` is not offered at that width at all.
const TOOLBAR_LAYOUTS = {
  desktop: {
    tbPrimary: ['addCoursesBtn'],
    tbHistory: ['undoBtn', 'redoBtn'],
    tbOutput: ['icsBtn', 'printBtn', 'shareBtn'],
    moreItems: ['clearBtn', 'fullscreenBtn'],
    hidden: [],
  },
  // Full screen is a desktop affordance: a phone's day view already fills
  // the screen.
  phone: {
    tbPrimary: ['addCoursesBtn'],
    tbHistory: [],
    tbOutput: ['icsBtn'],
    moreItems: ['undoBtn', 'redoBtn', 'printBtn', 'shareBtn', 'clearBtn'],
    hidden: ['fullscreenBtn'],
  },
};

//: The containers a layout fills, in document order.
const TOOLBAR_GROUPS = ['tbPrimary', 'tbHistory', 'tbOutput', 'moreItems'];

function toolbarLayout(isPhone) {
  return TOOLBAR_LAYOUTS[isPhone ? 'phone' : 'desktop'];
}

/**
 * Move the buttons into the layout's containers. A group left empty is
 * hidden, so it leaves no gap in the bar.
 */
function applyToolbarLayout(layout, doc) {
  for (const group of TOOLBAR_GROUPS) {
    const container = doc.getElementById(group);
    if (!container) continue;
    for (const id of layout[group]) {
      const button = doc.getElementById(id);
      if (!button) continue;
      button.hidden = false;
      container.appendChild(button);
    }
    if (group !== 'moreItems') container.hidden = layout[group].length === 0;
  }
  for (const id of layout.hidden) {
    const button = doc.getElementById(id);
    if (button) button.hidden = true;
  }
}

/**
 * A disclosure button opening a panel of ordinary buttons.
 *
 * Deliberately not an ARIA menu: role="menu" promises arrow-key roving and
 * typeahead, and a half-built menu is worse for a screen reader than a plain
 * expanded list of buttons. Esc and a click outside close it. Choosing an
 * action closes it too, and focus goes back to More unless the action moved
 * focus somewhere itself (Full screen sends it to its exit button).
 */
function bindMoreMenu(button, panel, doc) {
  const isOpen = () => button.getAttribute('aria-expanded') === 'true';

  function setOpen(open) {
    button.setAttribute('aria-expanded', String(open));
    panel.hidden = !open;
  }

  function close({ returnFocus }) {
    if (!isOpen()) return;
    const focusWasInside = panel.contains(doc.activeElement);
    setOpen(false);
    if (returnFocus || focusWasInside) button.focus();
  }

  button.addEventListener('click', () => setOpen(!isOpen()));

  // Bubbles up after the action's own listener has run, so by now the action
  // has had its chance to move focus.
  panel.addEventListener('click', (event) => {
    if (event.target && event.target.closest && event.target.closest('button')) {
      close({ returnFocus: false });
    }
  });

  doc.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && isOpen()) close({ returnFocus: true });
  });

  doc.addEventListener('click', (event) => {
    if (!isOpen()) return;
    if (button.contains(event.target) || panel.contains(event.target)) return;
    close({ returnFocus: false });
  });

  setOpen(false);
  return { isOpen, close: () => close({ returnFocus: false }) };
}
