# FullCalendar grid, phase 1: task list

**Not started.** Proposed 22 September 2026. Reasoning is in
[plan.md](plan.md); requirements are in
[FULLCALENDAR-SPEC.md](../FULLCALENDAR-SPEC.md).

Verification commands, used throughout:

```bash
node --test 'tests/js/**/*.test.js'
uv run --group test pytest
uv run uvicorn main:app --reload --port 8000
```

The manual checks refer to spec §6 by number. Run them in the in-app
browser against the local dev server.

## Phase A: groundwork

- [x] **1** Docs. *Done 22 Sep 2026; the docs are not tracked in git, so nothing to commit but this tick.*
      ~~Add `FULLCALENDAR-SPEC.md` and this plan to CLAUDE.md's doc table~~
      (done 22 Sep 2026, when this replaced the picker's plan). Rewrite ICS-EXPORT-SPEC §3.3 from "unresolved"
      to decided: reading 1, week 1 begins Mon 31 Aug 2026 for Semester 1 and
      Mon 18 Jan 2027 for Semester 2, confirmed by the owner 22 Sep 2026. Update
      its open question 1 to match.
      *Accept:* both files say the same dates as spec §2; nothing says
      "blocking" about the week 1 date any more.
      *Verify:* grep both files for `31 Aug` and `18 Jan`.
      XS. No dependencies.
      Files: `CLAUDE.md`, `ICS-EXPORT-SPEC.md`

- [x] **2** Spike: theme and v7 API check. *Done 22 Sep 2026; Forma recommended, findings go into the spec at checkpoint A.*
      Scratch page in the scratchpad, not the repo, loading
      `fullcalendar@7.1.0/all/global.js`, with a dozen fake events copied from
      the fixture's shape. For each of the four themes: light and dark, and
      whether its colours can come from `explore.css` variables. In the same
      page, confirm the exact v7 name and behaviour of: the per-event class
      property, `eventContent` returning DOM nodes, `slotEventOverlap: false`
      (side by side), `eventDragStart`/`eventDrop`/`eventDragStop` and
      `info.revert()`, adding and removing `display: 'background'` events
      mid-drag, `dayHeaderFormat` hiding the date, and whether an event can
      take keyboard focus.
      *Accept:* a short written report with the theme recommendation and its
      override list, and every name above either confirmed or corrected.
      *Verify:* screenshots of the chosen theme in light and dark.
      S. No dependencies.
      Files: none committed.

### Checkpoint A
- [x] You pick the theme. *Forma, 22 Sep 2026.*
- [x] Spec §4.3–§4.5 are corrected to the names the spike proved.
- [x] Create a branch for phase B (`git checkout -b fullcalendar-grid`).

## Phase B: parity

- [x] **3** Render placed classes with FullCalendar, read-only. *Done 22 Sep 2026. All the interact.js drag code went here too, not just its handlers: the ghost-zone helpers called the deleted `timeToSlot`, so task 5 only adds FullCalendar's drag.*
      New `assets/js/calendar-events.js` with `toCalendarEvents` and
      `visibleRange`, plus tests (spec §4.2 and §6). Add the pinned script tag
      and the chosen theme. Build the calendar with spec §4.3's options and an
      `eventContent` that renders code, pin, stale icon, type, time, room and
      badge, escaping every string. `renderEvents` replaces the calendar's
      events instead of building divs. Delete `buildGrid`, `timeToSlot`,
      `slotToTop`, the block-building loop, the clipped state, and
      `grid-layout.js` with its test. If `FullCalendar` is undefined, say so in
      the card. Drag is off (`editable: false`) until task 5, and the
      interact.js drag handlers go in this task, because they target
      `.calendar-event`.
      *Accept:* the same classes appear as on the live site for the same
      courses; two classes at one hour sit side by side; a 07:00 or 22:30
      class shows in full.
      *Verify:* both suites; manual checks 1, 2, 10, 12; grep that
      `time-slots`, `layoutDayEvents` and `timeToSlot` are gone.
      M. Needs 2.
      Files: `assets/js/calendar-events.js`,
      `tests/js/calendar-events.test.js`, `templates/calendar.html`,
      `assets/js/grid-layout.js` (deleted), `tests/js/grid-layout.test.js`
      (deleted)

- [ ] **4** Tap, keyboard and clash badge.
      `eventClick` opens the detail dialog, except on `.clash-badge`. The
      delegated badge handler reads `groupId`/`sessionId` from the event rather
      than `dataset`. Enter or Space on a focused class opens the dialog. The
      tap handler from interact.js is removed.
      *Accept:* all three paths open the right class's dialog; Escape still
      closes the resolve dialog first, then the details.
      *Verify:* manual checks 5 and 6; both suites.
      S. Needs 3.
      Files: `templates/calendar.html`

- [ ] **5** Drag to an alternative.
      Add `dropTargets` and `resolveDrop` to `calendar-events.js`, with tests
      (spec §4.2 and §6). Set `editable: true` and
      `eventDurationEditable: false`. `eventDragStart` adds the targets as
      background events with class `drop-zone`; `eventDrop` resolves, then
      either calls `state.moveEvent` or `info.revert()`; `eventDragStop` clears
      the targets. Delete `setupDragDrop`, `showGhostZones`, `clearGhostZones`,
      `getGhostZoneAt`, `resetDragPosition` and the interact.js script tag.
      Measure touch drag on a phone-sized viewport.
      *Accept:* a drop on an alternative moves and pins the class and Undo
      reverts it; any other drop leaves state untouched; a sitting another
      placement already shows is never a target.
      *Verify:* both suites; manual checks 3, 4, 11; grep that `interact` is
      gone from `calendar.html`.
      M. Needs 3 (and 4, since they edit the same file).
      Files: `assets/js/calendar-events.js`,
      `tests/js/calendar-events.test.js`, `templates/calendar.html`

### Checkpoint B
- [ ] Both suites pass.
- [ ] Manual checks 1–6 and 10–12 pass.
- [ ] Touch drag delay reported; your call if it needs changing.
- [ ] Review with you before styling.

## Phase C: finish

- [ ] **6** Styling.
      Re-point `.calendar-event*`, `.clash`, `.drop-zone` and the type colours
      onto FullCalendar's event elements; apply the theme overrides from task
      2; delete the CSS for `.day-column`, `.time-slot`, `.clipped` and
      `.dragging` that nothing uses any more. Only design-system variables, no
      literal colours. Check that print.css's
      `body > *:not(#printView)` still hides the calendar.
      *Accept:* type colours, clash ring, pin and focus ring all match today in
      light and dark; no horizontal overflow beyond today's 700px wrapper.
      *Verify:* manual checks 7, 8, 9, 13; grep the new CSS for `#` hex and
      `rgb(` literals.
      M. Needs 5.
      Files: `templates/calendar.html` (styles), possibly
      `assets/css/explore.css`

- [ ] **7** Record it.
      STATUS.md: what shipped, JS test count before and after and why it
      moved. CLAUDE.md: the test counts, the frontend paragraph (interact.js
      gone, FullCalendar in), the inline-script line count. Spec status line:
      phase 1 shipped. Tick spec §8.
      *Accept:* no doc says interact.js, `grid-layout.js` or the old counts.
      *Verify:* grep for `interact`, `grid-layout`, `308 JS`.
      XS. Needs 6.
      Files: `STATUS.md`, `CLAUDE.md`, `FULLCALENDAR-SPEC.md`

### Checkpoint C
- [ ] All 13 manual checks pass.
- [ ] Both suites pass; counts recorded.
- [ ] Spec §8 all ticked.
- [ ] You approve the merge and the deploy.
