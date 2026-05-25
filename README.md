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
