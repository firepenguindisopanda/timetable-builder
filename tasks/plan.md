# Implementation plan: course picker for /calendar

Written 9 August 2026, against `CALENDAR-PICKER-SPEC.md` and the warehouse as
loaded on 9 Aug 2026 (3,603 sessions, 1,082 courses, publication of 6 Aug).

## Overview

Add a course-picker mode to `/calendar` so a student can select course codes and
have the calendar fill itself from the warehouse, keeping PDF upload as an equal
alternative. Built in the spec's seven phases, each leaving the app working.

The one substantive departure from the spec is in section 4, below. Everything
else follows the spec as written.

## Section 4 re-checked against the live database

> **Superseded, 10 August 2026.** Everything in this section is an attempt to
> infer from the data whether a course's sittings are alternatives or
> obligations. That question is not answerable from the publication, and the
> answer turned out to be an institutional rule: a student attends one lecture,
> one lab and one tutorial per course per week. A student using the deployed
> app reported the symptom. The analysis below is kept because the measurements
> are correct and the failure of method is worth remembering, not because the
> conclusion stands.

The handoff asked for this before any code. The spec's counts reproduce exactly:
1,665 `(course_code, activity_type)` groups, 978 single-session, 99 with stream
labels, 588 unlabelled, of which 131 overlap in time and **457 are ambiguous**.

The recommendation built on those counts does not survive simulation.

### What the spec's rules actually produce

Running section 4's three derivation rules over the whole warehouse:

| Course a student adds | Placements | Hours on the grid |
|---|---|---|
| `FOUN 1001 (FULL & PART-TIME)` | 37 | 41.0 |
| `FOUN 1101` | 36 | 39.0 |
| `ECON 1001` | 32 | 37.0 |
| `FOUN 1106` | 31 | 35.0 |

A realistic five-course load (`COMP 1601`, `COMP 1602`, `MATH 1115`,
`FOUN 1101`, `PSYC 1001`) yields **82 placements and 99 hours** on a grid that
holds 40. The knock-on effect is worse than the clutter: section 7's conflict
panel fills with hundreds of phantom clashes, so the resolvable versus
unavoidable split in 7.4 carries no signal on first load.

### Two specific faults

**1. The taxonomy misplaces the risk.** Section 4 treats the 99 labelled groups
as solved by rule 1. Rule 1 only works when labelling is *complete*, and it is
complete in 81 of the 99. The other 18 are handled worse than the ambiguous
ones, because rule 1 splits one menu into "the labelled menu" plus N required
extras:

```
COMP 1601 Lab    10 sessions, 1 carries a label  -> 8 placements, 16h of lab
BIOL 1262 Tutorial 8 sessions, 4 carry labels    -> 5 tutorials a week
CHEM 1370 Tutorial 14 sessions, 9 carry labels   -> 5 placements
```

`COMP 1601` is the spec's own worked example, and its Lab group is the clearest
case in the warehouse of a menu of ten sections being read as eight obligations.

**2. Unbounded "attend all" is not the safe failure the spec claims.** The
argument in section 4 is that an extra class the student can delete is a smaller
failure than a real class silently missing. That holds for one extra block. It
does not hold at 33.

### The signal the spec missed

The 978 single-session groups are the warehouse's own answer to "what does one
activity type cost a student per week":

```
median 2h        p90 3h        p99 5h
```

That is an empirical ceiling rather than an invented one. Against it, the
ambiguous groups read very differently by size:

| Sessions in group | Groups | Median attend-all hours |
|---|---|---|
| 2 | 297 | 3.0 |
| 3 to 4 | 109 | 4.0 |
| 5 to 8 | 42 | 7.0 |
| 9 or more | 9 | 12.0 |

The risk is concentrated. 297 of 457 are two-session groups at a plausible 3
hours, which is the Monday-plus-Wednesday lecture pair, and there the spec is
right: defaulting those to pick-one would hide a real lecture every week. The
damage sits in the 51 groups of five or more.

Two other candidate signals were tested and rejected. The `notes` field carries
a parenthesised stream label (`(G2 T1)`, `(L4)`) on 191 sessions, but resolves
only **2 of the 457** ambiguous groups, so it is worth mining opportunistically
and cannot be the mechanism. Requiring uniform duration and identical week sets
across a group is too brittle: a single straggler session with a different week
range breaks the classification, which is why it misses `PSYC 1001` (15 x 1h
tutorials) and `FOUN 1101` (33 x 1h tutorials).

### Decision: bounded attend-all

Confirmed with the user. Keep attend-all as the default and cap it.

Derivation per `(courseKey, activityType)` group, in order:

1. If the group's attend-all total exceeds `MENU_CEILING_HOURS` (6.0, twice the
   p90 plausible load), the whole group is **one option group, pick one**.
2. Otherwise labelled sessions form one option group, the spec's rule 1.
3. Whatever is left clusters by time overlap, the spec's rules 2 and 3.
   Non-overlapping sessions default to attend all.

**Only rule 1 is new.** Implementation showed that is the whole fix, and that
the sharper version of rule 2 first drafted here was wrong. Merging a partly
labelled group wholesale places one lecture for `COMP 1601` where the student
owes three, because one of its five lectures happens to carry "G2". What
actually makes rule 1 of the spec safe is the ceiling running ahead of it: of
the 18 partially labelled groups, the 10 damaging ones are all large enough
that the ceiling claims them first, `COMP 1601` Lab at 20 hours among them. The
8 that reach rule 2 are small, and there it behaves.

Measured over all 1,082 courses once built:

| | Spec rules | Bounded attend-all |
|---|---|---|
| Five-course load | 82 placements, 99.0h | **21 placements, 31.0h** |
| `FOUN 1101` alone | 36 placements, 39.0h | 4 placements, 7.0h |
| `COMP 1601` | 12 placements | 5, matching the spec's own worked reading |

Across the warehouse the rules produce 2,323 option groups from 3,603 sessions,
keeping 1,280 blocks off the grid. The ceiling fires 161 times, and the 289
two-session pairs beneath it are untouched and still attend all.

Everything else in section 4 stands, including the requirement that a group be
correctable in the UI and that the override persist per course. The ceiling is a
better default, not a right answer, so `MENU_CEILING_HOURS` lives in one place
with the derivation of 6.0 in a comment beside it.

### Other data findings that shape tasks

- **`normalise_course_code` corrupts two real code shapes.** It maps
  `FOUN 1001 (FULL & PART-TIME)` to `FOUN 1001 (FULL & PART TIME)` because the
  hyphen-to-space rule that accepts `comp-2601` also eats the hyphen inside a
  real code, and it maps `WW101` to `WW 101` and `GW101` to `GW 101`, neither of
  which the warehouse holds. Codes reaching the new API come from
  `courses.json` verbatim, so resolution has to try the raw code before the
  normalised one. Task 1.1.
- **22 distinct activity types, and 5 sessions have a NULL `activity_type`.**
  A None key crashes an ordinary sort, so the group key needs a defined
  fallback. Relevant to E10.
- **`BIOL 1262` is a ready-made E6 fixture.** Its `Lecture` at Thursday 16:00
  runs W2, W4, W6, W8, W12 and its `Lecture Relocated` at Thursday 16:00 runs
  W10. Same day, same time, disjoint weeks, must not be a conflict. Real data,
  no invention needed.

## Architecture decisions

- **The new routes live in `explore_router.py` as a second `APIRouter`** with
  prefix `/api/timetable`, included from `main.py`. That reuses the pool, the
  `query()` wrapper with its retry and timing, and the 5 minute cache, which is
  what the constraint asks for, without pretending the picker is an
  `/explore` page.
- **Sessions are cached per course code**, not per request. A 40-code request
  then hits 40 cache keys and issues one batched query for the misses, so a
  bulk paste and a single add share the same warm data.
- **JS logic moves into modules testable under `node --test`.** Node 24 is
  present and its runner is built in, so no `package.json` and no npm
  dependency tree enter a Python project. Each module keeps working as a
  classic `<script src>` by exporting only when `module` exists.
- **`courseKey` is the normalised course code for both modes.** Upload mode
  resolves through the existing `resolve_course_code` logic and falls back to
  the title-derived id marked `origin: "upload"`.
- **Conflict finding stays pure; conflict classification does not.**
  `findConflicts` answers "do these two events collide, and in which weeks".
  Deciding resolvable versus unavoidable needs the option groups, so it sits in
  the placement module.

## Task list

Sizes: S is 1 to 2 files, M is 3 to 5.

### Phase 1: the sessions API

#### Task 1.1: resolve a course code the way the warehouse actually spells it

**Description:** A resolver that maps a caller-supplied code onto a code the
warehouse holds. Exact match first, then `normalise_course_code`, then give up.
This is what stops `WW101` and `FOUN 1001 (FULL & PART-TIME)` landing in
`notFound`.

**Acceptance criteria:**
- [ ] Every one of the 1,082 warehouse codes resolves to itself
- [ ] `comp1601`, `COMP 1601`, `comp-2601` still resolve as they do today
- [ ] An unknown code returns None rather than raising

**Verification:**
- [ ] `uv run pytest tests/test_explore_queries.py`
- [ ] A scratch script asserts round-trip resolution over all 1,082 live codes

**Dependencies:** None.
**Files:** `timetable_extractor/database/explore_queries.py`,
`tests/test_explore_queries.py`.
**Scope:** S

#### Task 1.2: batched sessions query

**Description:** `sessions_for_courses(conn, codes)` in `explore_queries.py`,
returning course metadata and sessions for many codes in one query rather than
N, shaped for the wire per spec section 6 including real `weeks`.

**Acceptance criteria:**
- [ ] One round trip regardless of how many codes are passed
- [ ] Emits `sessionId`, `type`, `day`, `startTime`, `endTime`, `room`,
      `staff`, `streamLabel`, `weeks`, `weeksRaw`, `sourceCount`
- [ ] Field names are the ones `computeStreamId` already expects
- [ ] Sessions come back in a deterministic order (day, start, end, id)

**Verification:**
- [ ] Scratch run against the live warehouse for `COMP 1601` and `BIOL 1262`
      matches `/explore/course/...` for the same codes
- [ ] `uv run pytest`

**Dependencies:** 1.1.
**Files:** `timetable_extractor/database/explore_queries.py`.
**Scope:** S

#### Task 1.3: `GET /api/timetable/sessions`

**Description:** The public read-only route, on a second `APIRouter` in
`explore_router.py`, reusing the pool and cache. Caps `codes` at 40 and returns
`notFound` rather than 404 so a mixed-quality bulk paste partially succeeds.

**Acceptance criteria:**
- [ ] `?codes=COMP%201601,COMP%202601` returns both courses
- [ ] An unknown code appears in `notFound` and the rest still return
- [ ] Over 40 codes is a 400 whose message names the cap, so the client knows
      what to batch by
- [ ] Cached per code, so a second request for an overlapping set issues no
      query for the codes already seen
- [ ] Route is public, read-only, and appears in `/docs`

**Verification:**
- [ ] `uv run pytest tests/test_timetable_api.py`
- [ ] `curl` against a local server for a 2-code and a 41-code request

**Dependencies:** 1.2.
**Files:** `explore_router.py`, `main.py`.
**Scope:** S

#### Task 1.4: tests for the sessions endpoint

**Description:** Route-level tests with fixtures captured from the live
warehouse, with `query` faked so the suite needs no database, matching how the
existing tests stay hermetic.

**Acceptance criteria:**
- [ ] Fixtures are real captured rows for `COMP 1601`, `BIOL 1262` and
      `FOUN 1101`, not invented ones
- [ ] Covers multiple codes, `notFound`, the 40 cap, and code normalisation
      including `WW101` and `FOUN 1001 (FULL & PART-TIME)`
- [ ] Tests read as statements about behaviour

**Verification:**
- [ ] `uv run pytest` passes with 238 plus the new tests

**Dependencies:** 1.3.
**Files:** `tests/test_timetable_api.py`, `tests/fixtures/warehouse.py`.
**Scope:** S

### Checkpoint: phase 1

- [ ] `uv run pytest` green, no test removed
- [ ] `/calendar` and `/extract` unchanged and working
- [ ] `/explore` unaffected, pool and cache shared not duplicated
- [ ] STATUS.md updated

### Phase 2: pure logic, tested, not yet wired in

#### Task 2.0: a JS test harness

**Description:** `node --test tests/js/`, with each `assets/js` module exporting
under CommonJS only when `module` is defined so browser behaviour is identical.
A pytest shim runs the JS suite too and skips cleanly when node is absent, so
one command still runs everything.

**Acceptance criteria:**
- [ ] `node --test tests/js/` runs and passes
- [ ] `uv run pytest` also runs the JS suite, skipping if node is missing
- [ ] `/calendar` still loads the same files as plain scripts with no console
      errors

**Verification:**
- [ ] Both commands pass
- [ ] Browser check: `/calendar` loads, console clean

**Dependencies:** None. Can run in parallel with phase 1.
**Files:** `tests/js/`, `tests/test_js_suite.py`, `assets/js/calendar-utils.js`.
**Scope:** S

#### Task 2.1: option grouping

**Description:** `assets/js/option-groups.js` implementing bounded attend-all:
the ceiling rule, the merged partial-label rule, then overlap clustering. Group
ids must be stable across reloads for persistence, so ordering is deterministic.

**Acceptance criteria:**
- [ ] `MENU_CEILING_HOURS` is defined once with its derivation in the comment
- [ ] A group over the ceiling yields one option group
- [ ] A partially-labelled group yields one option group, not a split
- [ ] Non-overlapping sessions under the ceiling default to attend all
- [ ] Sessions identical except room land in one group (E20)
- [ ] A NULL activity type does not crash grouping (E10)
- [ ] Group ids are stable for the same input

**Verification:**
- [ ] `node --test` with fixtures for `COMP 1601` lectures and labs,
      `BIOL 1262` labs and tutorials, `FOUN 1101` tutorials, `MATH 1115`
      tutorials, all pulled from the warehouse
- [ ] A scratch run over all 1,665 live groups reproduces the numbers in this
      plan: 54 ambiguous groups reclassified, 291 blocks kept off the grid

**Dependencies:** 2.0.
**Files:** `assets/js/option-groups.js`, `tests/js/option-groups.test.js`,
`tests/js/fixtures/`.
**Scope:** M

#### Task 2.2: week-aware conflicts

**Description:** Rewrite `findConflicts` per section 7. Two events conflict only
if their weeks intersect; a missing or empty `weeks` means every week so
uploaded PDFs behave as they do now; same-course clashes are no longer excluded;
the conflict reports its shared weeks.

**Acceptance criteria:**
- [ ] Overlapping times with disjoint weeks are not a conflict (E6)
- [ ] The conflict object carries the shared weeks
- [ ] Two sessions of the same course can conflict
- [ ] Events with no weeks conflict exactly as they do today

**Verification:**
- [ ] `node --test`, with the `BIOL 1262` Lecture versus Lecture Relocated pair
      as the E6 fixture
- [ ] `uv run pytest` still green

**Dependencies:** 2.0.
**Files:** `assets/js/calendar-utils.js`, `tests/js/conflicts.test.js`.
**Scope:** S

#### Task 2.3: incremental placement

**Description:** `assets/js/placement.js` with 8.1: place one course's option
groups against what is already placed, never moving an existing placement,
deterministic tie-breaks, and a summary the UI can show.

**Acceptance criteria:**
- [ ] Never mutates or moves an existing placement
- [ ] Tie-break order is fewest conflicts, then earliest day, then earliest
      start, and the same input always gives the same result
- [ ] Returns what was placed, what clashed, and what had no clash-free option
- [ ] A single-option group that clashes is still placed and marked unavoidable
      (E4)

**Verification:**
- [ ] `node --test`, including a fixture where a naive placement would move an
      existing choice

**Dependencies:** 2.1, 2.2.
**Files:** `assets/js/placement.js`, `tests/js/placement.test.js`.
**Scope:** M

#### Task 2.4: bulk placement and repair

**Description:** 8.2 in the same module: most-constrained-first ordering, then
8.1 scoring per course, then a bounded repair pass over placements added in
this batch only.

**Acceptance criteria:**
- [ ] Orders incoming courses by fewest options first
- [ ] Repair touches only placements added in this batch, never pinned ones
- [ ] Attempts are capped and the pass stops at the first zero-conflict state
- [ ] Reports honestly, for example "added 6 courses, 1 unavoidable clash on
      Tuesday" (E5)

**Verification:**
- [ ] `node --test` with a fixture built to fail under naive insertion order
      and succeed under most-constrained-first

**Dependencies:** 2.3.
**Files:** `assets/js/placement.js`, `tests/js/placement.test.js`.
**Scope:** M

### Checkpoint: phase 2

- [ ] `node --test` and `uv run pytest` both green
- [ ] Nothing in `templates/` changed yet, `/calendar` behaves exactly as before
- [ ] The live-warehouse scratch run confirms the section 4 numbers
- [ ] STATUS.md updated

### Phase 3: state and persistence

The riskiest phase. It rewrites the model every part of `calendar.html` reads,
so it is split so the app is working at each step.

#### Task 3.1: TimetableState on option groups and courseKey

**Description:** Placements become `{courseKey, groupId, selectedSessionId,
pinned}`. `getAvailableStreams` becomes options-for-a-group.
`fromExtractResponse` and a new `fromWarehouseResponse` both produce the same
shape with `origin` set.

**Acceptance criteria:**
- [ ] Both sources produce the identical in-memory shape
- [ ] `computeStreamId` gives the same id for the same class from either source
- [ ] Pinned placements are immovable by every placement operation
- [ ] `autoPlaceAll` becomes an explicit re-optimise that respects pinning

**Verification:**
- [ ] `node --test` for the state class
- [ ] Browser: an existing saved v2 timetable still renders

**Dependencies:** 2.3.
**Files:** `assets/js/timetable-state.js`, `tests/js/timetable-state.test.js`.
**Scope:** M

#### Task 3.2: v3 persistence and migration

**Description:** `celcat_timetable_v3` per spec section 12, keeping the v1 and
v2 readers. `migrateV2toV3` maps `{courseId, streamType, selectedStreamId}` onto
the new keys. Storage failures surface instead of only logging (E14).

**Acceptance criteria:**
- [ ] A v2 payload migrates without losing a placement
- [ ] A v1 payload still loads through the existing v1 to v2 path
- [ ] `publicationId` is stored, for E16
- [ ] A full or disabled localStorage shows the student a message

**Verification:**
- [ ] `node --test` for the migration, with a real captured v2 payload
- [ ] Browser: load a v2 payload, confirm the same classes are placed

**Dependencies:** 3.1.
**Files:** `assets/js/timetable-state.js`, `tests/js/migration.test.js`.
**Scope:** M

#### Task 3.3: rewire calendar.html to the new state

**Description:** Point the existing grid, event list, detail panel, drag and
drop and conflict panel at the new API. No new UI yet. Dragging to a ghost zone
now pins.

**Acceptance criteria:**
- [ ] Upload path works end to end, offline, with no network
- [ ] Drag to another stream still works and now pins the result
- [ ] Undo and redo still work
- [ ] Detail panel shows real weeks

**Verification:**
- [ ] Browser via chrome-devtools: upload a PDF, place, drag, undo, reload
- [ ] Light and dark, and a 390px viewport
- [ ] Console clean

**Dependencies:** 3.2.
**Files:** `templates/calendar.html`.
**Scope:** M

### Checkpoint: phase 3

- [ ] Upload mode fully working with no network
- [ ] A saved v2 timetable survives the upgrade
- [ ] `uv run pytest` and `node --test` green
- [ ] STATUS.md updated

### Phase 4: picker UI, one course at a time

#### Task 4.1: mode chooser and empty state

**Description:** Section 9.1. Two choices, picker first, shown only when the
calendar is empty. Once there are placements it becomes "add courses" or "add a
PDF" rather than a mode flip.

**Acceptance criteria:**
- [ ] Chooser appears only when empty
- [ ] Upload route from the empty state still reaches `/extract`
- [ ] Keyboard reachable, visible focus

**Verification:**
- [ ] Browser: empty, then non-empty. Light, dark, 390px.

**Dependencies:** 3.3.
**Files:** `templates/calendar.html`.
**Scope:** S

#### Task 4.2: course search

**Description:** Search over `/explore/courses.json` reusing the matching logic
in `assets/js/explore.js`. Rows show code, title, faculty and the week meter so
they look like the explorer.

**Acceptance criteria:**
- [ ] Matches code, title, lecturer and room
- [ ] Typing costs no requests after the first load
- [ ] Offline shows an honest message and leaves upload mode usable (E17)

**Verification:**
- [ ] Browser: search, and again with the network throttled to offline
- [ ] Light, dark, 390px

**Dependencies:** 4.1.
**Files:** `templates/calendar.html`, `assets/js/explore.js`.
**Scope:** M

#### Task 4.3: add and remove one course

**Description:** Selecting a course adds it immediately through 8.1 with no
apply step, and a toast reports the outcome. Undo removes the whole course.

**Acceptance criteria:**
- [ ] Adding is immediate, blocks animate in
- [ ] Toast says what happened, including clashes
- [ ] Adding a course already present is a no-op with a message (E2)
- [ ] Removing a course leaves every other placement where it was (UC6)
- [ ] A course with 25 sessions does not swamp the grid (E11)

**Verification:**
- [ ] Browser: add `COMP 1601`, add it again, add `BIOL 1262`, remove one,
      confirm the others do not move
- [ ] Light, dark, 390px

**Dependencies:** 4.2.
**Files:** `templates/calendar.html`.
**Scope:** M

### Checkpoint: phase 4

- [ ] A student can build a timetable without touching a PDF
- [ ] Upload mode still works, including offline
- [ ] STATUS.md updated

### Phase 5: bulk

#### Task 5.1: multi-select in results

**Description:** Checkboxes with a running "Add N courses" button feeding 8.2.

**Acceptance criteria:**
- [ ] Selection survives typing in the search box
- [ ] One batch is one undo step (E19)

**Verification:** Browser, light, dark, 390px.
**Dependencies:** 4.3.
**Files:** `templates/calendar.html`.
**Scope:** S

#### Task 5.2: paste a list of codes

**Description:** A textarea taking codes separated by commas, spaces or
newlines, with a parse preview naming unrecognised codes before anything is
added.

**Acceptance criteria:**
- [ ] Preview lists what will be added and what was not recognised (E13)
- [ ] Over 40 codes is batched with progress (E12)
- [ ] Capitalisation and a missing space are normalised on entry (E18)
- [ ] Codes containing a space or punctuation, such as
      `FOUN 1001 (FULL & PART-TIME)`, parse correctly

**Verification:**
- [ ] Browser: paste 45 codes including junk lines and one punctuated code
- [ ] Light, dark, 390px

**Dependencies:** 5.1.
**Files:** `templates/calendar.html`.
**Scope:** M

### Checkpoint: phase 5

- [ ] UC2 and UC3 work end to end
- [ ] One Ctrl+Z removes a whole batch
- [ ] STATUS.md updated

### Phase 6: conflict UX

#### Task 6.1: resolvable versus unavoidable, with weeks

**Description:** Classify each conflict per 7.4, list the two kinds separately,
show the weeks, and offer "Fix" only where an alternative exists.

**Acceptance criteria:**
- [ ] Panel reads "clashes in weeks 3, 5, 7" rather than "clashes"
- [ ] "Fix" appears only on resolvable conflicts and applies the alternative
- [ ] An unavoidable clash is named as such and never silently dropped
- [ ] Fixing does not move a pinned placement

**Verification:**
- [ ] Browser with a course pair known to clash, and with the `BIOL 1262`
      disjoint-weeks pair to confirm it is not reported
- [ ] Light, dark, 390px

**Dependencies:** 5.2.
**Files:** `templates/calendar.html`.
**Scope:** M

#### Task 6.2: the option group override

**Description:** Section 4's required correction control. Merge a group with a
sibling ("these are alternatives, I only attend one") or split it, stored per
course in saved state. This is what makes the ceiling a default rather than a
verdict.

**Acceptance criteria:**
- [ ] A group can be merged and split, and the change survives a reload
- [ ] A group the ceiling turned into a menu says so and can be expanded back
- [ ] Overrides are keyed per course so a warehouse refresh keeps them

**Verification:**
- [ ] Browser: override on `PSYC 1001` tutorials, reload, confirm it held
- [ ] `node --test` for override persistence

**Dependencies:** 6.1.
**Files:** `templates/calendar.html`, `assets/js/timetable-state.js`.
**Scope:** M

### Checkpoint: phase 6

- [ ] UC8 and UC9 work
- [ ] The section 4 default is correctable and the correction persists
- [ ] STATUS.md updated

### Phase 7: polish

#### Task 7.1: shareable URL

`/calendar?codes=...` placing through 8.2 against current data (UC11). Codes
containing spaces or punctuation must survive the round trip.
**Scope:** S. **Depends:** 6.2.

#### Task 7.2: stale data prompt

Compare stored `publicationId` on load and offer a refresh (E16). Keep a course
the warehouse no longer publishes, marked stale (E15).
**Scope:** S. **Depends:** 7.1.

#### Task 7.3: grid clamping and rendering gaps

Clamp a session outside 08:00 to 22:00 and flag it rather than letting the block
vanish (E7). Confirm Saturday and Sunday columns are not hidden, 139 and 6
sessions exist (E8). Render "Not published" for a missing room or staff (E9).
**Scope:** S. **Depends:** 7.2.

### Checkpoint: complete

- [ ] All 12 use cases and all 20 edge cases in the spec accounted for
- [ ] `uv run pytest` and `node --test` green
- [ ] Browser verified in light and dark at 390px and desktop
- [ ] Upload path verified offline one final time
- [ ] STATUS.md and README.md updated

## Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Phase 3 breaks the upload path | High | 3.3 is verified offline in a browser before phase 4 starts; v1 and v2 readers stay |
| The 6.0h ceiling is wrong for a course nobody checked | Medium | It is a default, not a verdict. Task 6.2 ships the override the spec requires, and the constant sits in one place |
| Option group ids churn between reloads and orphan saved placements | High | 2.1 makes ordering deterministic and pins id stability as an acceptance criterion; 3.2 tests migration against a real captured payload |
| Bulk repair is slow enough to feel like a hang | Medium | Attempts capped in 2.4, measured on the worst real load rather than assumed |
| Week-aware conflicts change what upload-mode users see | Medium | Empty weeks means every week, so uploads behave exactly as today. Pinned as a test in 2.2 |
| The JS suite is easy to forget | Low | 2.0 wires it into `uv run pytest` so one command runs both |

## Open questions

1. **Validate the ceiling with one real student and one real course list**, as
   section 4 asks. The number to check is whether a five-course load now reads
   as roughly 15 to 20 hours rather than 99.
2. Spec 15.2, whether the picker should filter to a faculty or level by
   default. Deferred; search handles 1,082 rows and the explorer already proves
   it.
2b. **The calendar has no light theme.** `templates/base.html` hardcodes
   `data-bs-theme="dark"` and there is no toggle, so "check light and dark" has
   nothing to check on `/calendar` today. The explorer is different: its own
   stylesheet carries `prefers-color-scheme` blocks. Phase 4 borrows explorer
   markup for the search rows, so it has to decide whether the calendar gains a
   light theme or the borrowed rows are restyled to the dark shell.
3. Spec 15.4, a week selector on the grid. Out of scope here, but week-aware
   conflicts make it cheap later and it would make E6 visible rather than
   theoretical.
4. ~~`normalise_course_code` is wrong for `WW101` and
   `FOUN 1001 (FULL & PART-TIME)` on `/explore/course/...` too.~~ **Closed.**
   Fixed in all three places after phase 1: `/explore/course/{code}`,
   `cli course`, and the picker. Matching now lives in `database/courses.py`.
