"""
Pydantic models for course-specific extraction configs.
"""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class PageRegions(BaseModel):
    """Normalized page boundaries (0.0 to 1.0)."""
    header_top: float = 0.0
    header_bottom: float = 0.15
    table_top: float = 0.15
    table_bottom: float = 0.85
    footer_bottom: float = 0.92


class DayColumn(BaseModel):
    """Normalized x-coordinate range for a single day."""
    left: float
    right: float


class DayColumns(BaseModel):
    """Mapping from day name to column range."""
    monday: DayColumn | None = None
    tuesday: DayColumn | None = None
    wednesday: DayColumn | None = None
    thursday: DayColumn | None = None
    friday: DayColumn | None = None
    saturday: DayColumn | None = None
    sunday: DayColumn | None = None


class TimeSlot(BaseModel):
    """A single time slot with normalized y-coordinate range."""
    label: str
    top: float
    bottom: float


class TextPatterns(BaseModel):
    """Regex patterns for extracting structured text from blocks."""
    module_code_regex: str | None = None
    room_pattern: str | None = None
    activity_types: list[str] = Field(default_factory=list)
    staff_pattern: str | None = None


class CourseConfig(BaseModel):
    """Full extraction config for a single course."""
    page_regions: PageRegions = Field(default_factory=PageRegions)
    day_columns: DayColumns = Field(default_factory=DayColumns)
    time_slot_map: list[TimeSlot] = Field(default_factory=list)
    text_patterns: TextPatterns = Field(default_factory=TextPatterns)
    confidence: float = 0.0
    layout_signature: str = ""


class MongoCourseConfig(BaseModel):
    """The document stored in MongoDB course_configs collection."""
    _id: Any = None  # ObjectId, set by MongoDB
    course_id: str = ""
    course_code: str
    version: int = 1
    status: str = "draft"  # draft | active | superseded | rejected
    generated_by: str = "llm"
    llm_session_id: str | None = None
    config: CourseConfig
    rejection_reason: str | None = None

    model_config = {"arbitrary_types_allowed": True}


class CalibrationSession(BaseModel):
    """Record of a single LLM calibration run."""
    _id: Any = None
    course_code: str
    pdf_filename: str
    pdf_metadata: dict = Field(default_factory=dict)
    llm_provider: str = "nemotron"
    llm_model: str = ""
    prompt_template_version: str = "v1"
    phase1_response: dict = Field(default_factory=dict)
    phase2_response: dict = Field(default_factory=dict)
    generated_config_id: str | None = None
    pattern_report: dict = Field(default_factory=dict)
    accuracy_score: float | None = None
    admin_feedback: str | None = None

    model_config = {"arbitrary_types_allowed": True}
