# CELCAT Timetable Extraction

This FastAPI server exposes timetable extraction, download, evaluation, and **LLM-powered calibration** workflows as HTTP endpoints.

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

## Validating a New Semester

CELCAT's layout and text conventions drift between semesters, and the failures
are usually silent — a whole day of classes landing on the wrong row — rather
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
- rooms that don't appear in the official room registry

It exits non-zero when a required field drops below `--fail-under` (default
99%) or any sanity check fails, so it can gate CI:

```bash
uv run python validate_corpus.py --fail-under 99 --json report.json
```

Run `uv run pytest` alongside it — the unit tests pin the PDF text conventions
(week formats, day labels, room names, activity types) that tend to shift.

---

## Timetable Warehouse (Postgres)

The site publishes three views of the same timetable — one PDF per course, per
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
| `sync_runs` | Every update check, including no-ops — the update history |
| `resources` | The finder.xml index (courses, staff, rooms) |
| `courses` / `staff` / `rooms` | Normalised entities |
| `pdf_files` | Per-file ETag, Last-Modified and content hash |
| `sessions` | The fact table, one row per class per publication |
| `session_staff` / `session_sources` | Who teaches it; which PDFs confirmed it |

Sessions are stored *per publication* rather than overwritten, so successive
loads accumulate history and semesters can be diffed. The `current_sessions`
view flattens the latest publication for everyday queries.

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

The server exposes only its *current* `Last-Modified` — there is no history
endpoint — so `sync_runs` and `publications` are the only place a record of
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
# Run calibration on a PDF (extraction → config generation → report)
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
