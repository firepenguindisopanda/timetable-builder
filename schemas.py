"""
Pydantic response/request schemas for the CELCAT Timetable Extraction API.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

class TimetableEntry(BaseModel):
    """A single class block extracted from a timetable PDF."""

    day: str
    start_time: str
    end_time: str
    type: str | None = None
    weeks: str | None = None
    week_count: int | None = None
    course: str | None = None
    staff: str | None = None
    room: str | None = None
    group_label: str | None = None
    raw_text: str


class TimetableResult(BaseModel):
    """Extraction output for a single PDF file."""

    source_file: str
    semester: str | None = None
    course_title: str | None = None
    entries: list[TimetableEntry]


class ExtractResponse(BaseModel):
    """Response for extraction endpoints."""

    results: list[TimetableResult]
    total_files: int
    total_entries: int


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str


class DownloadRequest(BaseModel):
    faculty: str | None = None
    dept: str | None = None
    codes: list[str] | None = None
    res_type: str = "module"
    all_resources: bool = False
    limit: int | None = None
    dry_run: bool = False


class DownloadResponse(BaseModel):
    downloaded: int
    skipped: int
    failed: int


class EvaluateRequest(BaseModel):
    pdf_dir: str = "./downloaded_pdfs"
    tolerance: float = 5.0


class EvaluateResponse(BaseModel):
    total_pdfs: int
    discrepancies: list[dict]
    missing: list[dict]
    errors: list[dict]


class BatchExtractRequest(BaseModel):
    pdf_dir: str = Field(
        default="./downloaded_pdfs",
        description="Directory containing PDF files to extract",
    )


# --- Calibration Schemas ---

class CalibrateRequest(BaseModel):
    course_code: str

class CalibrateResponse(BaseModel):
    session_id: str
    course_code: str
    config_id: str
    confidence: float
    entries_count: int
    report: str
    status: str = "completed"

class SessionSummary(BaseModel):
    session_id: str
    course_code: str
    status: str
    confidence: float | None = None
    config_id: str | None = None
    created_at: str | None = None

class ConfigSummary(BaseModel):
    config_id: str
    course_code: str
    status: str
    generated_by: str
    version: int
    confidence: float
    created_at: str | None = None

class SessionListResponse(BaseModel):
    sessions: list[SessionSummary]
    total: int

class ConfigListResponse(BaseModel):
    configs: list[ConfigSummary]
    total: int

class ActivateConfigRequest(BaseModel):
    config_id: str

class ActivateConfigResponse(BaseModel):
    config_id: str
    course_code: str
    status: str = "active"
    message: str = "Config activated"
