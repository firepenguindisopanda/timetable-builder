# Course picker: task list

**Complete and deployed, 10 August 2026.** All seven phases done; see
[STATUS.md](../STATUS.md) for where things stand. Full reasoning is in
[plan.md](plan.md), with its section 4 marked superseded.

Two corrections landed after the phases, both from the deployed app:

- **The grouping rule.** Section 4's whole premise was that the data could say
  whether a course's sittings are alternatives or obligations. It cannot. A
  student attends one lecture, one lab and one tutorial per course per week,
  which is institutional and is now stated in `option-groups.js` rather than
  inferred.
- **Asset caching.** A deploy changed a script without changing the `?v=` that
  asked for it, and returning students got new HTML against a stale cached
  script, which rendered a blank calendar. Asset URLs are now content-hashed.

## Phase 1: the sessions API

- [x] **1.1** Course code resolution that survives the real spellings.
      Exact match before normalising, so `WW101` and
      `FOUN 1001 (FULL & PART-TIME)` stop landing in `notFound`.
      S. No dependencies.
      Files: `explore_queries.py`, `tests/test_explore_queries.py`
- [x] **1.2** `sessions_for_courses(conn, codes)`, one query not N, emitting the
      field names `computeStreamId` expects and real `weeks`.
      S. Needs 1.1.
      Files: `explore_queries.py`
- [x] **1.3** `GET /api/timetable/sessions`, second `APIRouter` in
      `explore_router.py`, public and read-only, pool and cache reused, 40-code
      cap, `notFound` not 404.
      S. Needs 1.2.
      Files: `explore_router.py`, `main.py`
- [x] **1.4** Endpoint tests with fixtures captured from the warehouse
      (`COMP 1601`, `BIOL 1262`, `FOUN 1101`), `query` faked so no database is
      needed.
      S. Needs 1.3.
      Files: `tests/test_timetable_api.py`,
      `tests/fixtures/warehouse_sessions.json`

### Checkpoint: phase 1 (done)

- [x] `uv run pytest` green, 238 to 312, nothing removed
- [x] `/calendar`, `/extract` and `/explore` unchanged, all 200
- [x] STATUS.md updated
- [x] Bonus: the same resolution bug fixed in `/explore/course/{code}` and
      `cli course`, which open question 4 had left open

## Phase 2: pure logic, tested, not yet wired in

- [x] **2.0** JS test harness: `node --test tests/js/`, CommonJS export only
      when `module` exists, and a pytest shim that runs it and skips without
      node. S. No dependencies, can run alongside phase 1.
      Files: `tests/js/`, `tests/test_js_suite.py`, `calendar-utils.js`
- [x] **2.1** Option grouping: ceiling rule, merged partial labels, then overlap
      clustering. `MENU_CEILING_HOURS` defined once with its derivation beside
      it. Stable group ids. M. Needs 2.0.
      Files: `assets/js/option-groups.js`, `tests/js/`
      - [x] Run over all 1,082 live courses: 2,323 groups from 3,603
            sessions, 1,280 blocks kept off the grid, five-course load down
            from 82 placements / 99h to 21 / 31h
- [x] **2.2** Week-aware `findConflicts`: weeks must intersect, empty weeks
      means every week, same-course clashes now reported, shared weeks in the
      result. S. Needs 2.0.
      Files: `calendar-utils.js`, `tests/js/conflicts.test.js`
      - [x] E6 fixture is the real `BIOL 1262` pair, Lecture Thu 16:00
            W2/4/6/8/12 against Lecture Relocated Thu 16:00 W10
- [x] **2.3** Incremental placement (8.1): never moves an existing placement,
      deterministic tie-breaks, returns a summary. M. Needs 2.1, 2.2.
      Files: `assets/js/placement.js`, `tests/js/placement.test.js`
- [x] **2.4** Bulk placement (8.2): most-constrained-first, bounded repair over
      this batch only, honest reporting. M. Needs 2.3.
      Files: `assets/js/placement.js`, `tests/js/placement.test.js`

### Checkpoint: phase 2 (done)

- [x] `node --test` green at 64, `uv run pytest` green at 313
- [x] No template touched. Browser check: a seeded v2 timetable still places
      3 blocks, the conflict panel still reports its clash, console clean,
      dark at 390px unchanged
- [x] `deriveOptionGroups` and `placeGroups` are absent from the page, so
      nothing new is reachable yet
- [x] STATUS.md updated
- [x] Carried into phase 4 and settled there: `/calendar` is dark only, and
      the picker is styled in its variables rather than importing
      `explore.css`. Giving the calendar a light theme is still open

## Phase 3: state and persistence

- [x] **3.1** `TimetableState` on option groups and `courseKey`, both sources
      producing one shape, pinning honoured everywhere, `autoPlaceAll` becomes
      an explicit re-optimise. M. Needs 2.3.
      Files: `timetable-state.js`, `tests/js/timetable-state.test.js`
- [x] **3.2** v3 persistence and `migrateV2toV3`, v1 and v2 readers kept,
      `publicationId` stored, storage failure surfaced (E14). M. Needs 3.1.
      Files: `timetable-state.js`, `tests/js/migration.test.js`
- [x] **3.3** Rewire `calendar.html` to the new state. No new UI. Drag now pins.
      M. Needs 3.2.
      Files: `templates/calendar.html`
      - [x] Browser: v2 and v1 payloads upgrade and render, a real drag
            moves and pins across four alternatives, re-optimise spares
            the pinned one, undo and redo walk back, console clean,
            dark at 390px. No light theme exists to check

### Checkpoint: phase 3 (done)

- [x] Upload mode fully working: loading a saved timetable makes no request to
      the warehouse, verified from the network log
- [x] A saved v2 timetable survives the upgrade, and so does a v1 one
- [x] `uv run pytest` green at 313, `node --test` green at 107
- [x] STATUS.md updated

## Phase 4: picker UI, one course at a time

- [x] **4.1** Mode chooser and empty state (9.1), picker first, only when empty.
      S. Needs 3.3. Files: `templates/calendar.html`
- [x] **4.2** Course search over `/explore/courses.json`, reusing `explore.js`
      matching, explorer-style rows with the week meter, honest offline message
      (E17). M. Needs 4.1. Files: `templates/calendar.html`, `explore.js`
- [x] **4.3** Add and remove one course through 8.1, immediate, with a toast.
      Duplicate add is a no-op with a message (E2). Removing leaves the rest put
      (UC6). M. Needs 4.2. Files: `templates/calendar.html`

### Checkpoint: phase 4 (done)

- [x] A timetable can be built without touching a PDF
- [x] Upload mode still offered everywhere the picker is, and still the only
      route with no network
- [x] Offline: saved timetable renders in full, picker says what is broken,
      PDF route stays, undo still works
- [x] `uv run pytest` green at 313, `node --test` green at 124
- [x] The explorer's own search verified unchanged after sharing its matcher
- [x] STATUS.md updated

## Phase 5: bulk

- [x] **5.1** Checkboxes in results with a running "Add N courses", one batch is
      one undo step (E19). S. Needs 4.3. Files: `templates/calendar.html`
- [x] **5.2** Paste box with a parse preview, batching past 40 (E12), junk lines
      listed not swallowed (E13), normalisation on entry (E18), punctuated codes
      parsed correctly. M. Needs 5.1. Files: `templates/calendar.html`

### Checkpoint: phase 5 (done)

- [x] UC2 (paste a whole semester) and UC3 (multi-select) work end to end
- [x] One Ctrl+Z takes a whole batch back, verified at 4 courses and at 45
- [x] 45 codes split into 2 requests of 40 and 5, still one undo step
- [x] All 1,082 published codes round-trip through the paste parser
- [x] No horizontal overflow at 390px with the paste box and selection bar open
- [x] `uv run pytest` green at 313, `node --test` green at 138
- [x] STATUS.md updated

## Phase 6: conflict UX

- [x] **6.1** Resolvable versus unavoidable, weeks shown, "Fix" only where an
      alternative exists and never moving a pinned placement. M. Needs 5.2.
      Files: `templates/calendar.html`
- [x] **6.2** The option group override the spec requires: merge or split a
      group, stored per course, surviving reload. A ceiling-created menu says so
      and can be expanded. M. Needs 6.1.
      Files: `templates/calendar.html`, `timetable-state.js`

### Checkpoint: phase 6 (done)

- [x] UC8 (see which classes clash, and in which weeks) and UC9 (be told when
      a clash cannot be avoided) both work
- [x] A fix is offered only when it lowers the total, and never by moving a
      pinned placement
- [x] The section 4 default is correctable, and the correction survives a
      reload and can be undone
- [x] `uv run pytest` green at 313, `node --test` green at 150
- [x] STATUS.md updated

## Phase 7: polish

- [x] **7.1** Shareable `/calendar?codes=...` placed through 8.2 (UC11), codes
      with spaces and punctuation surviving the round trip. S. Needs 6.2.
- [x] **7.2** Stale data prompt on `publicationId` mismatch (E16), unpublished
      course kept and marked stale (E15). S. Needs 7.1.
- [x] **7.3** Clamp and flag a session outside the grid (E7), confirm Saturday
      and Sunday are not hidden (E8), "Not published" for a missing room or
      staff (E9). S. Needs 7.2.

### Checkpoint: complete (done)

- [x] All 12 use cases and all 20 edge cases accounted for
- [x] `uv run pytest` green at 314, `node --test` green at 156
- [x] Browser verified at 390px and desktop. No light theme exists to check,
      which is recorded in STATUS.md rather than silently skipped
- [x] Upload path verified: offline, migrated from v1 and v2, and folded into
      an existing timetable (which was broken and is now fixed)
- [x] STATUS.md and README.md updated

## Standing bar

Held for every task above, and for anything added later. Not a checklist to
complete; a bar to clear each time.

- House style: no em dashes, en dashes, emoji or rule lines, including in
  comments. Comments say why, not what
- Tests read as statements about behaviour, fixtures pulled from the warehouse
  rather than invented
- The upload path still works with no network
- No automatic placement moves anything the student set by hand
- New API routes stay public and read-only, sharing the explorer's pool and
  cache
