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
    notes: str | None = None
    raw_text: str


class ExtractionDiagnostics(BaseModel):
    """
    What went quietly wrong while reading a PDF.

    A layout change does not make extraction fail, it makes it wrong, so the
    response carries the near-misses rather than only the entries.
    """

    findings: dict[str, int] = Field(
        default_factory=dict,
        description="Count per finding, e.g. {'day_label_unmatched': 1}",
    )
    samples: dict[str, list[dict]] = Field(
        default_factory=dict, description="Up to five examples per finding"
    )
    corrupting: int = Field(
        default=0,
        description="Findings that mean a class may be on the wrong day",
    )


class TimetableResult(BaseModel):
    """Extraction output for a single PDF file."""

    source_file: str
    semester: str | None = None
    course_title: str | None = None
    entries: list[TimetableEntry]
    diagnostics: ExtractionDiagnostics | None = None


class ExtractResponse(BaseModel):
    """Response for extraction endpoints."""

    results: list[TimetableResult]
    total_files: int
    total_entries: int
    findings: dict[str, int] = Field(
        default_factory=dict,
        description="Findings summed across every file in this request",
    )
    corrupting: int = Field(
        default=0,
        description="Total findings that may have misplaced a class",
    )


class PublicationInfo(BaseModel):
    """The current publication and which load of it is being served."""

    id: int
    revision: int = Field(
        description="Starts at 1 and rises by 1 each time the sessions are rewritten."
    )
    publishedAt: str | None = Field(description="When UWI published it, ISO 8601.")
    loadedAt: str | None = Field(description="When this revision was written, ISO 8601.")
    resourceCount: int


class SemesterInfo(BaseModel):
    """The semester the current publication is filed under."""

    label: str | None
    academicYear: str | None
    number: int | None
    weekOne: str | None = Field(
        description="Monday of teaching week 1, or null when the semester's dates are not known."
    )
    totalWeeks: int


class SyncInfo(BaseModel):
    """When UWI was last asked about a republish, and whether one is waiting."""

    checkedAt: str | None
    updatePending: bool


class TermInfo(BaseModel):
    """One term the warehouse holds a timetable for."""

    term: str = Field(description="The term as `?term=` takes it, like 2026-27-s2.")
    label: str = Field(description='"Semester 2 2026/27 (inspection copy)".')
    academicYear: str
    number: int
    stage: str | None = Field(
        description="`inspection` for UWI's draft published for checking, else `final`."
    )
    publicationId: int
    default: bool = Field(description="True for the term served when none is named.")


class PublicationResponse(BaseModel):
    """`GET /api/timetable/publication`. See PUBLICATION-ENDPOINT-SPEC.md."""

    apiVersion: int = Field(
        description="Changes only when a field is removed, renamed or retyped."
    )
    term: str = Field(description="The term answered for, like 2026-27-s1.")
    stage: str | None = Field(
        description="`inspection` while the term's timetable is UWI's draft, else `final`."
    )
    terms: list[TermInfo] = Field(
        description="Every term held, oldest first, so a client can offer a switch."
    )
    publication: PublicationInfo
    semester: SemesterInfo
    sync: SyncInfo


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
