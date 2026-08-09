# CELCAT Timetable Extraction

This FastAPI server exposes timetable extraction, download, evaluation, and **LLM-powered calibration** workflows as HTTP endpoints.

> **Coming back to this project?** Read [STATUS.md](STATUS.md) first. It records
> what is deployed, what was last verified, and what to do when UWI next
> republishes the timetable. This file is the reference manual.

## Running the Application

Start the server with Uvicorn:

```bash
uv run uvicorn main:app --reload --port 8000
```

## Interactive API Docs

Once running, view the interactive documentation at:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

---

## Configuration

Only one setting is needed to serve the timetable. The rest belong to the
optional LLM calibration feature and can be left out of a deployment that does
not use it.

| Variable | Needed for | Required? |
|----------|-----------|-----------|
| `DATABASE_URL` | Everything: the explorer, the warehouse, the CLI | **Yes** |
| `LOG_LEVEL`, `LOG_FORMAT` | Logging verbosity and JSON output | No, defaults are sane |
| `CORS_ALLOW_ORIGINS` | Comma-separated origin allowlist, default `*` | No |
| `ADMIN_API_KEY` | Unlocking the admin endpoints | Only if you want them |
| `MONGODB_URI`, `MONGODB_DB_NAME` | Storing LLM-generated per-course extraction configs | Only for calibration |
| `NVIDIA_API_KEY`, `NVIDIA_BASE_URL`, `NVIDIA_MODEL` | The vision model that generates those configs | Only for calibration |

### Why MongoDB and NVIDIA are in `.env.example`

They serve the **calibration** workflow only, which is an admin tool for
teaching the deterministic extractor about an awkward PDF layout. Nothing on
the student-facing path touches either one:

- **NVIDIA NIM** is called from `/admin/calibrate` and the calibration CLI, and
  nowhere else. Its imports are inside those endpoints, so the module is never
  loaded unless you call them.
- **MongoDB** stores the configs calibration produces. The extractor reads one
  only when a `course_code` is passed to `extract_timetable()`, and neither the
  warehouse loader nor the explorer passes one. The client is also lazy, so
  importing the app does not open a connection.

A deployment that serves `/explore` and loads the warehouse therefore needs
`DATABASE_URL` and nothing else. Leaving the Mongo and NVIDIA values unset is
safe; the calibration endpoints will fail cleanly if called, and no other route
is affected.

### What is public and what is not

Everything under `/explore` is public, read-only and safe to expose. So is the
`/extract` upload, which parses a PDF the caller supplies and keeps nothing.

These take a path on the server or make it fetch from UWI, so they require
`X-API-Key`:

| Endpoint | Why it is guarded |
|----------|-------------------|
| `POST /extract/batch` | Reads a directory the caller names |
| `POST /evaluate` | Reads a directory the caller names |
| `POST /download` | Makes the server pull up to 1,600 files from UWI |
| `POST /admin/*` | Calibration and config management |

**Leaving `ADMIN_API_KEY` unset closes them rather than opening them.** They
answer `503` with a message naming the missing setting, which is what a
deployment serving only the public timetable should do: those workflows need
the PDF corpus and write access anyway, so they cannot work in the cloud.

CORS allows cross-origin reads by default (the timetable is public data) but
never with credentials. Nothing authenticates by cookie, so a credentialed
cross-origin request is neither needed nor safe. Narrow it with
`CORS_ALLOW_ORIGINS=https://one.example,https://two.example`.

### Connection pooling

The explorer holds a small read-only pool that validates a connection before
lending it out (`check=ConnectionPool.check_connection`), and retires
connections after 120s idle. Managed Postgres services (Neon, Supabase, RDS
behind a proxy) close idle connections without notifying the client, so without
that check the first page view after a quiet spell fails with
`SSL connection has been closed unexpectedly` and then works on refresh.

---

## Validating a New Semester

CELCAT's layout and text conventions drift between semesters, and the failures
are usually silent - a whole day of classes landing on the wrong row - rather
than a crash. After each semester's PDFs are published, download them and run
the corpus validator:

```bash
# Fetch every course PDF for the new semester
uv run python -m timetable_extractor.download --all

# Extract all of them and check the results
uv run python validate_corpus.py
```

The validator cross-references extracted rooms and course codes against the
authoritative lists in `finder.xml` (downloaded automatically) and reports:

- files that crashed or produced no entries
- per-field coverage, flagging `day` / `start_time` / `end_time` as required
- sanity checks: invalid days, malformed or inverted times, blocks that merged
  two sessions together, and courses whose code doesn't match the PDF's module
- **course codes that the registry doesn't publish** - a code invented out of
  stray text creates a phantom course and splits a real course's timetable in
  two. Codes that resolve only after repair (wrapped mid-word, or with a staff
  name glued on) are reported separately as a warning, since the loader snaps
  those back onto the published code
- rooms that don't appear in the official room registry

Add `--include-subdirs` to validate the staff and room PDFs too, which is the
same corpus the database loads.

It exits non-zero when a required field drops below `--fail-under` (default
99%) or any sanity check fails, so it can gate CI:

```bash
uv run python validate_corpus.py --fail-under 99 --json report.json
```

Run `uv run pytest` alongside it - the unit tests pin the PDF text conventions
(week formats, day labels, room names, activity types) that tend to shift.

---

## Timetable Warehouse (Postgres)

The site publishes three views of the same timetable - one PDF per course, per
room and per staff member. Loading all three and merging them yields a far
richer dataset than any single view: course PDFs name the room, room PDFs name
the teacher, and a session confirmed by several PDFs is more trustworthy than
one seen once.

Set `DATABASE_URL` in `.env`, then:

```bash
# Download every resource type (1,082 courses + 336 staff + 210 rooms)
uv run python -m timetable_extractor.download --all
uv run python -m timetable_extractor.download --all --type staff --out-dir downloaded_pdfs/staff
uv run python -m timetable_extractor.download --all --type room  --out-dir downloaded_pdfs/rooms

uv run python -m timetable_extractor.database.cli init   # create schema
uv run python -m timetable_extractor.database.cli load   # extract + load
uv run python -m timetable_extractor.database.cli stats
```

### Querying

```bash
uv run python -m timetable_extractor.database.cli course COMP2601
uv run python -m timetable_extractor.database.cli room "Daaga Auditorium"
uv run python -m timetable_extractor.database.cli free-rooms Monday 10:00 12:00 --week 3
uv run python -m timetable_extractor.database.cli clashes "COMP 2605" "COMP 2611"
uv run python -m timetable_extractor.database.cli staff-load
```

Clash detection is week-aware. Two classes only collide if they overlap in
time *and* share a teaching week, so a lecture in W1-W6,W8-W12 and its W7
relocation are correctly reported as clashing in different weeks.

### Schema

`timetable_extractor/database/schema.sql`, with the reasoning in comments.

| Table | Holds |
|-------|-------|
| `publications` | One row per republish of the site, keyed by the XML's hash |
| `sync_runs` | Every update check, including no-ops - the update history |
| `resources` | The finder.xml index (courses, staff, rooms) |
| `courses` / `staff` / `rooms` | Normalised entities |
| `pdf_files` | Per-file ETag, Last-Modified and content hash |
| `sessions` | The fact table, one row per class per publication |
| `session_staff` / `session_sources` | Who teaches it; which PDFs confirmed it |

Sessions are stored *per publication* rather than overwritten, so successive
loads accumulate history and semesters can be diffed. The `current_sessions`
view flattens the latest publication for everyday queries.

---

## Observability

### The failure this is built around

CELCAT layout drift does not crash the extractor, it moves classes. The worked
example is `deW`: `Wed` reversed was missing from `REVERSED_DAYS`, so in about
one PDF in five no Wednesday row was built. `y_to_day` then fell back to the
nearest band above and filed that day's classes under **Tuesday**. Nothing
raised, no field was empty, every PDF looked individually fine. The only
symptom was a corpus-wide day histogram reading Tuesday 1,294 / Wednesday 567.

So the questions the telemetry answers are:

1. Did this extraction silently misfile anything?
2. Which PDFs produced nothing, or dropped a page?
3. Is the published layout drifting from what the parser expects?
4. For the explorer: is a page slow, and is it the database or the render?

### Extraction findings

`extract_timetable()` returns a `diagnostics` block alongside the entries and
logs one warning per finding. The four in `CORRUPTING_FINDINGS` mean a class
may be on the wrong day:

| Finding | Meaning |
|---------|---------|
| `day_label_unmatched` | A left-column word that looks like a day label but is not in the table. **This is the signal that catches the next `deW`.** |
| `day_band_missing` | A row-sized gap between two day bands: a day nobody claimed |
| `day_fallback_used` | A block sat in no row and was placed by proximity instead |
| `day_unknown` | No day bands at all on the page |
| `day_bands_without_rules` | No grid lines, so every block is positioned by guesswork (not corrupting on its own) |
| `time_header_missing` | A page was skipped entirely - every class on it was dropped |
| `no_entries` | The PDF parsed but yielded nothing |

`validate_corpus.py` aggregates these across the corpus, prints samples, and
**exits non-zero** on any corrupting finding - so the CI gate that already
guards field coverage now also guards day placement.

It also computes the weekday skew directly: if the busiest weekday carries more
than `DAY_SKEW_THRESHOLD` (1.8x) the median weekday's classes, the run fails.
That single number is what the `deW` bug looked like from the outside.

### Structured logs

`timetable_extractor/observability.py` provides JSON logging with a correlation
id on every line.

```bash
LOG_FORMAT=json LOG_LEVEL=info uv run uvicorn main:app --port 8000
```

```json
{"ts":"2026-08-09T20:14:02.881Z","level":"warning","logger":"timetable_extractor.extract",
 "event":"extract.day_label_unmatched","correlation_id":"3f9c1a2b4d5e",
 "source":"m104178.pdf","count":1,"samples":[{"text":"deW","y":275.4}]}
```

Every HTTP request gets an id (honouring an inbound `X-Request-ID`, echoed on
the response), and is logged with its route template, status and duration.
Static assets log at debug so they do not bury anything. Explorer queries log
their duration, at info once past `SLOW_QUERY_MS`.

Set `LOG_FORMAT=json` in production and leave it unset for readable CLI output.

### Data health endpoint

`GET /explore/ops.json` - aggregates only, no credentials needed:

```json
{
  "status": "degraded",
  "problems": ["Tuesday has 2.28x the median weekday's classes, which usually
                means a day label was not recognised..."],
  "freshness": {"status": "current", "...": "..."},
  "day_distribution": {"skew_ratio": 2.28, "skewed": true, "...": "..."},
  "cache": {"courses": {"hits": 41, "misses": 1, "hit_rate": 0.976}}
}
```

`status` is `ok` or `degraded`. It is symptom-based on purpose: it reports
"classes are probably on the wrong day" and "the data is stale", both of which
a student would feel, rather than CPU or pool internals.

### After changing the extractor

Sessions are keyed on their content, so a parser fix that moves a class to a
different day inserts a corrected row **without** removing the wrong one,
leaving the class on both days. Re-load with `--replace`:

```bash
uv run python -m timetable_extractor.database.cli load --replace
```

---

## The Timetable Explorer

`/explore` is the student-facing, read-only view of the warehouse. It writes
nothing and touches only `current_sessions`, so it is safe to expose while the
extraction tools stay behind the admin key.

| Path | Shows |
|------|-------|
| `/explore` | Campus heat grid, search over every course, room and lecturer |
| `/explore/course/{code}` | One course: its week grid and every session |
| `/explore/rooms`, `/explore/room/{code}` | Rooms and what is booked in them |
| `/explore/staff`, `/explore/staff/{name}` | Lecturers and their teaching week |

Course codes are normalised, so `/explore/course/comp2601` and
`/explore/course/COMP%202601` both resolve.

### Freshness

Every page carries a provenance rail showing three separate timestamps, because
they answer different questions:

* **UWI published** - `publications.published_at`, the date on the source
* **Imported** - `publications.discovered_at`, when we loaded it
* **Checked** - the most recent `sync_runs.started_at`, when we last asked

Showing only the first cannot distinguish "UWI has not changed it" from "we
stopped looking three weeks ago". The rail turns amber when the last check is
over two days old, and calls out the case where a check *detected* a change
that has not been imported yet - the one situation where the page is knowingly
behind. That state clears once `sync pull` and `database.cli load` have run.

### Teaching weeks

The explorer is built around the week band. A class is not "Monday 09:00" but
"Monday 09:00, weeks 2, 4, 6, 8, 10, 12", and the 12-segment meter beside every
session shows exactly that - fortnightly labs read as a comb, a one-week
relocation as a single mark. The same twelve segments are the week filter on
the landing page.

### Caching and load

The course index (about 1,100 rows) is served once as JSON and filtered in the
browser, so typing costs no requests; it gzips to roughly 44 KB. Aggregate
queries sit behind a 5-minute in-process cache, and the explorer holds its own
small read-only connection pool. After reloading the warehouse, call
`explore_router.clear_cache()` or restart the server to publish the new data
immediately.

---

## Detecting Updates

UWI republishes the whole site in one batch. The server sends `Last-Modified`
and `ETag` on every file and honours conditional requests, so checking costs
one `304` per file instead of a download.

```bash
uv run python -m timetable_extractor.sync check     # has it changed?
uv run python -m timetable_extractor.sync pull      # re-download only what changed
uv run python -m timetable_extractor.sync history   # what we have observed
```

`check` exits `10` when the timetable was republished and `0` when it was not,
which makes it easy to drive from a scheduler:

```cron
# Check every morning at 07:00; pull and reload when something changed.
0 7 * * * cd ~/code/timetable-builder && \
  uv run python -m timetable_extractor.sync check --quiet; \
  [ $? -eq 10 ] && uv run python -m timetable_extractor.sync pull && \
  uv run python -m timetable_extractor.database.cli load
```

The server exposes only its *current* `Last-Modified` - there is no history
endpoint - so `sync_runs` and `publications` are the only place a record of
past updates can accumulate. Run the check on a schedule and the history
builds itself.

---

## LLM Calibration Module

The calibration module uses an LLM (NVIDIA NIM vision models) as an **admin calibration tool** to analyze CELCAT timetable PDFs and generate course-specific extraction configurations. These configs are stored in MongoDB and loaded by the deterministic extractor for improved accuracy on subsequent extractions.


### Prerequisites

1. **MongoDB Atlas** - Create a free cluster and get your connection URI
2. **NVIDIA API Key** - Get a free API key from [NVIDIA NIM](https://build.nvidia.com/explore/discover)
3. **Environment setup** - Copy `.env.example` to `.env` and fill in:

```bash
# MongoDB Atlas
MONGODB_URI=mongodb+srv://<user>:<pass>@cluster0.jiwv0.mongodb.net/
MONGODB_DB_NAME=timetable_calibration

# LLM Provider (NVIDIA NIM)
NVIDIA_API_KEY=nvapi-<your-key>
NVIDIA_BASE_URL=https://ai.api.nvidia.com/v1/gr/meta/llama-3.2-90b-vision-instruct/chat/completions
NVIDIA_MODEL=meta/llama-3.2-90b-vision-instruct

# Admin Auth
ADMIN_API_KEY=<generate-a-random-key>
```

### CLI Usage

The calibration module provides a CLI accessible via `uv run python -m timetable_extractor.calibration.cli`:

```bash
# Run calibration on a PDF (extraction -> config generation -> report)
uv run python -m timetable_extractor.calibration.cli calibrate \
    --pdf path/to/timetable.pdf \
    --course-code COSC1111

# List calibration sessions
uv run python -m timetable_extractor.calibration.cli list-sessions

# View session details
uv run python -m timetable_extractor.calibration.cli get-session <session-id>

# List generated configs
uv run python -m timetable_extractor.calibration.cli list-configs

# Promote a draft config to active (so the deterministic extractor uses it)
uv run python -m timetable_extractor.calibration.cli activate-config <config-id>
```

### Admin API Endpoints

All admin endpoints require an `X-API-Key` header matching your `ADMIN_API_KEY` env var.

| Method | Path | Description |
|--------|------|-------------|
| POST | `/admin/calibrate` | Upload a PDF and run calibration (multipart: `file` + `course_code`) |
| GET | `/admin/sessions` | List calibration sessions (optional `course_code` filter) |
| GET | `/admin/sessions/{id}` | Get session details and report |
| GET | `/admin/configs` | List course configs (filter by `status`/`course_code`) |
| POST | `/admin/configs/{id}/activate` | Promote a draft config to active |

### How It Works

1. **Admin** uploads or provides a PDF of a CELCAT timetable for a specific course
2. **LLM Provider** (default: NVIDIA NIM vision model) analyzes the PDF in two phases:
   - **Phase 1 - Extraction**: The LLM extracts timetable entries (course name, day, time, room, activity type) from the PDF
   - **Phase 2 - Config Generation**: The LLM analyzes the layout structure (day columns, time slots, page regions, text patterns) and generates a structured configuration
3. **Config Generator** saves the configuration to MongoDB as a `draft` config
4. **Report Generator** produces a markdown report including pattern discovery, anomalies, and recommendations
5. **Admin** reviews the report and promotes the config to `active` via CLI or API
6. **Deterministic Extractor** automatically loads the active config when processing PDFs for that course code

### Provider System

The LLM provider is swappable. Implement the `LLMProvider` protocol (defined in `timetable_extractor/calibration/providers/base.py`) with two methods:

- `extract_timetable(pdf_path: str) -> dict` - Extract timetable data from the PDF
- `generate_config(pdf_path: str, extraction: dict) -> dict` - Generate config from extraction
