# Implementation plan: FullCalendar as the `/calendar` grid, phase 1

Status: **proposed, awaiting review**. Written 22 September 2026.

Spec: [FULLCALENDAR-SPEC.md](../FULLCALENDAR-SPEC.md). Task list:
[todo.md](todo.md).

## Overview

Replace the hand-built week grid in `templates/calendar.html` with
FullCalendar 7.1.0's `timeGridWeek`, loaded as a pinned script tag. The student
should notice no difference except that nothing is ever cut off or hidden. The
logic that is left moves into a new tested module,
`assets/js/calendar-events.js`. Phase 2 (dated weeks) is planned separately
once this ships.

## Architecture decisions

All settled in spec §2 and §4. Repeated here only where they shape the order.

- **`TimetableState` stays the only source of truth.** FullCalendar is a view.
  Every change goes through `state` → `onStateChanged()` → replace the
  calendar's events. So the calendar can be swapped without touching
  placement, conflicts, undo/redo, persistence or print.
- **Pure logic in `calendar-events.js`, thin glue in the inline script.** The
  node suite can't load FullCalendar, so anything that needs a test must not
  need FullCalendar.
- **The spike comes first.** The spec's FullCalendar option and hook names come
  from the v7 docs and the upgrade guide, not from running code. v7 renamed a
  lot (`eventClassNames` → `eventClass`, `backgroundColor` → `color`, and so
  on) and dropped its bundled CSS. Task 2 proves every name the build tasks use
  before anything depends on it.
- **Work on a branch; deploy once, at the end.** Tasks 3–5 each leave the page
  working, but between task 3 and task 5 you can't drag. That's fine on a
  branch and not fine on the live site.

## Dependency graph

```
Task 1 docs ─────────────────────────────────────────────────┐
                                                             │
Task 2 spike (theme + v7 API names)                          │
   │                                                         │
   ▼                                                         │
Task 3 render read-only ──► Task 4 tap / keyboard / badge    │
   │   (toCalendarEvents,       (eventClick, Enter/Space,    │
   │    visibleRange, tests)     clash badge)                │
   │                                                         │
   └──────────────────────► Task 5 drag to an alternative    │
                               (dropTargets, resolveDrop,    │
                                tests, interact.js removed)  │
                                         │                   │
                                         ▼                   │
                            Task 6 styling, light/dark,      │
                                   mobile, print             │
                                         │                   │
                                         ▼                   ▼
                                  Task 7 STATUS, counts, spec status
```

Task 1 depends on nothing and could run beside task 2. Tasks 4 and 5 both
depend only on task 3, but they edit the same inline script, so they run one
after the other.

## Slicing

Each build task is something a student can do end to end, not a layer:

| Task | After it, a student can… |
|---|---|
| 3 | See their timetable drawn by FullCalendar, with classes side by side and nothing cut off |
| 4 | Tap or press Enter on a class to see details; tap a clash badge to fix it |
| 5 | Drag a class to one of its alternatives, or have it snap back |
| 6 | Use it in light and dark mode, on a phone, and print it |

Each task's module functions and tests land in the same task as the UI that
uses them, not in a separate "write the module" task up front.

## Task list

Details, acceptance criteria and files are in
[todo.md](todo.md).

### Phase A: groundwork
- [ ] 1. Docs: CLAUDE.md doc table; ICS-EXPORT-SPEC §3.3 week 1 dates (XS)
- [ ] 2. Spike: theme choice plus a check of every v7 option and hook name (S, scratch only)

### Checkpoint A: human review
- [ ] Theme chosen; spec §4.3–§4.5 corrected to the names the spike proved

### Phase B: parity
- [ ] 3. Render placed classes with FullCalendar, read-only (M)
- [ ] 4. Tap, keyboard and clash badge (S)
- [ ] 5. Drag to an alternative (M)

### Checkpoint B: behaviour parity
- [ ] Both suites pass
- [ ] Spec §6 manual checks 1–6 and 10–12 pass in the browser
- [ ] Review with human before styling

### Phase C: finish
- [ ] 6. Styling: light/dark, phone width, print (M)
- [ ] 7. STATUS.md, CLAUDE.md test counts, spec status (XS)

### Checkpoint C: ready to ship
- [ ] All 13 manual checks in spec §6 pass
- [ ] Both suites pass; counts recorded
- [ ] Spec §8 success criteria all ticked
- [ ] Human approves merge and deploy (not done without asking)

## Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| v7 option or hook names differ from what the spec says | Med | Task 2 checks each one in a running page before task 3 uses it. The spec is corrected at checkpoint A, not mid-build. |
| No v7 theme can be pointed at `explore.css` tokens without fighting its own colours | High | Task 2 tries every theme and writes down which overrides each needs. If none works, stop at checkpoint A and ask; don't write a theme from scratch. |
| **Touch drag feels different.** FullCalendar starts a touch drag after a long press (`eventLongPressDelay`, 1000 ms by default); interact.js starts at once. | Med | This is arguably better: on phones the grid scrolls sideways, and an instant drag fights the scroll. Task 5 measures it on a touch device. If 1 s is too slow, pick a shorter delay and ask before shipping it. |
| CDN fails to load, so the calendar area is blank | Med | Today's interact.js poller retries forever without a word. Task 3 adds a check: if `FullCalendar` is undefined, the card says the calendar could not load. (This goes beyond the spec, but it is one line and it is the failure STATUS.md already recorded once, as a blank calendar.) |
| Saved timetables break | High | State and storage format are untouched. Manual check 10 reloads a timetable saved before the change. |
| Hidden DOM dependencies on the old grid (`.time-slots`, `data-day`, `.calendar-event` selectors) | Low | A grep during planning found them only in the grid code being replaced and in the clash-badge handler, which task 4 rewrites. Task 3 greps again after deleting. |
| Test count changes read as a regression | Low | Deleting `grid-layout.test.js` lowers the JS count. Task 7 records the old count, the new count and why. |

## Out of scope

Phase 2 (dated weeks, the week switcher, week-aware conflicts), month and list
views, a phone-specific day view, SRI hashes (declined), and any change to
`schema.sql` or Python dependencies.

## Open questions

- Which theme? Task 2 answers it, and you decide at checkpoint A.
