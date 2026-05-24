"""
Converts LLM extraction results into CourseConfig models
and persists them to MongoDB.
"""

from __future__ import annotations

from typing import Any

from timetable_extractor.config.db import get_collection
from timetable_extractor.config.models import (
    CourseConfig,
    DayColumn,
    DayColumns,
    MongoCourseConfig,
    PageRegions,
    TextPatterns,
    TimeSlot,
)

_DAY_ORDER = [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
]

WEEKDAY_NAMES = {
    "mon", "monday", "tue", "tues", "tuesday",
    "wed", "weds", "wednesday",
    "thu", "thur", "thurs", "thursday",
    "fri", "friday",
    "sat", "saturday",
    "sun", "sunday",
}

_TIME_PATTERN = r"\b\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?\s*(?:-|to|–)\s*\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?\b"
_ROOM_PATTERN = r"[A-Z0-9]{2,5}\.\d{2}\.\d{2}[A-Z]?"
_STAFF_PATTERN = r"[A-Z][a-z]+,\s*[A-Z]\."


def _normalise_day_label(label: str) -> str | None:
    """Return canonical weekday key for a day label, or None."""
    low = label.strip().lower().rstrip("s")
    for canonical, variants in {
        "monday": ("mon", "monday"),
        "tuesday": ("tue", "tues", "tuesday"),
        "wednesday": ("wed", "weds", "wednesday"),
        "thursday": ("thu", "thur", "thurs", "thursday"),
        "friday": ("fri", "friday"),
        "saturday": ("sat", "saturday"),
        "sunday": ("sun", "sunday"),
    }.items():
        if low in variants:
            return canonical
    return None


def _build_default_page_regions() -> PageRegions:
    return PageRegions(
        header_top=0.0,
        header_bottom=0.15,
        table_top=0.15,
        table_bottom=0.85,
        footer_bottom=0.92,
    )


def _build_default_text_patterns() -> TextPatterns:
    return TextPatterns(
        module_code_regex=r"[A-Z]{2,4}\d{4}",
        room_pattern=_ROOM_PATTERN,
        activity_types=["Lecture", "Tutorial", "Lab", "Practical", "Workshop"],
        staff_pattern=_STAFF_PATTERN,
    )


def _derive_day_columns(entries: list[dict[str, Any]]) -> DayColumns:
    """Infer day-column positions from entry data."""
    seen_days: list[str] = []
    for entry in entries:
        day = entry.get("day", "")
        normalised = _normalise_day_label(day)
        if normalised and normalised not in seen_days:
            seen_days.append(normalised)

    if not seen_days:
        return DayColumns()

    col_width = 1.0 / len(seen_days)
    columns: dict[str, DayColumn | None] = {d: None for d in _DAY_ORDER}
    for i, day in enumerate(seen_days):
        columns[day] = DayColumn(left=round(i * col_width, 4), right=round((i + 1) * col_width, 4))

    return DayColumns(**columns)


def _clean_time_str(t: str) -> str:
    """Strip AM/PM suffix and return clean HH:MM string."""
    t = t.strip().upper()
    t = t.replace("AM", "").replace("PM", "").strip()
    return t


def _derive_time_slots(entries: list[dict[str, Any]]) -> list[TimeSlot]:
    """Collect unique time ranges from entries and assign vertical positions."""
    seen: list[tuple[str, float, float]] = []
    for entry in entries:
        label = entry.get("time", "") or entry.get("start_time", "") + " - " + entry.get("end_time", "")
        if not label or not entry.get("start_time"):
            continue
        label = label.strip()
        if not label or any(existing[0] == label for existing in seen):
            continue
        start_str = _clean_time_str(str(entry.get("start_time", "00:00")))
        end_str = _clean_time_str(str(entry.get("end_time", "23:59")))
        try:
            start_h, start_m = start_str.split(":")
            end_h, end_m = end_str.split(":")
        except ValueError:
            continue
        top = (int(start_h) * 60 + int(start_m)) / (24 * 60)
        bottom = (int(end_h) * 60 + int(end_m)) / (24 * 60)
        seen.append((label, top, bottom))

    seen.sort(key=lambda x: x[1])
    return [TimeSlot(label=label, top=top, bottom=bottom) for label, top, bottom in seen]


class ConfigGenerator:
    """Converts LLM extraction results into CourseConfig and persists to MongoDB."""

    def generate(
        self,
        course_code: str,
        extraction_result: dict[str, Any],
        llm_extraction: dict[str, Any],
    ) -> CourseConfig:
        """Build a CourseConfig from LLM extraction data.

        Args:
            course_code: The course identifier.
            extraction_result: Raw output from Phase 1 extraction
                (contains entries, layout_notes, etc.).
            llm_extraction: Raw output from Phase 2 config analysis
                (contains page_regions, day_columns, time_slot_map,
                 text_patterns, confidence, layout_signature, etc.).

        Returns:
            A populated CourseConfig instance (not yet persisted).
        """
        entries: list[dict[str, Any]] = extraction_result.get("entries", [])

        page_regions = self._parse_page_regions(llm_extraction, entries)
        day_columns = self._parse_day_columns(llm_extraction, entries)
        time_slot_map = self._parse_time_slots(llm_extraction, entries)
        text_patterns = self._parse_text_patterns(llm_extraction)
        confidence = llm_extraction.get("confidence", 0.0)
        layout_signature = llm_extraction.get("layout_signature", "")

        return CourseConfig(
            page_regions=page_regions,
            day_columns=day_columns,
            time_slot_map=time_slot_map,
            text_patterns=text_patterns,
            confidence=confidence,
            layout_signature=layout_signature,
        )

    def save(
        self,
        course_config: CourseConfig,
        course_code: str = "unknown",
        session_id: str | None = None,
    ) -> str:
        """Persist a CourseConfig to MongoDB wrapped in metadata.

        Args:
            course_config: The config to persist.
            course_code: The actual course code (overrides layout_signature).
            session_id: Optional calibration session ID to link.

        Returns:
            The inserted document's _id as a string.
        """
        doc = MongoCourseConfig(
            course_code=course_code or course_config.layout_signature or "unknown",
            config=course_config,
            llm_session_id=session_id,
        )

        result = get_collection("course_configs").insert_one(doc.model_dump(by_alias=True))
        return str(result.inserted_id)

    def generate_and_save(
        self,
        course_code: str,
        extraction_result: dict[str, Any],
        llm_extraction: dict[str, Any],
        session_id: str | None = None,
    ) -> tuple[CourseConfig, str]:
        """Convenience: generate a CourseConfig and persist it in one call.

        Returns:
            (course_config, config_id) tuple.
        """
        cfg = self.generate(course_code, extraction_result, llm_extraction)
        config_id = self.save(cfg, course_code=course_code, session_id=session_id)
        return cfg, config_id

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_page_regions(
        llm_extraction: dict[str, Any],
        entries: list[dict[str, Any]],
    ) -> PageRegions:
        raw = llm_extraction.get("page_regions")
        if isinstance(raw, dict):
            return PageRegions(**raw)
        return _build_default_page_regions()

    @staticmethod
    def _parse_day_columns(
        llm_extraction: dict[str, Any],
        entries: list[dict[str, Any]],
    ) -> DayColumns:
        raw = llm_extraction.get("day_columns")
        if isinstance(raw, dict):
            processed: dict[str, Any] = {}
            for day_key in _DAY_ORDER:
                col_data = raw.get(day_key)
                if isinstance(col_data, dict):
                    processed[day_key] = DayColumn(**col_data)
                else:
                    processed[day_key] = None
            return DayColumns(**processed)
        return _derive_day_columns(entries)

    @staticmethod
    def _parse_time_slots(
        llm_extraction: dict[str, Any],
        entries: list[dict[str, Any]],
    ) -> list[TimeSlot]:
        raw = llm_extraction.get("time_slot_map")
        if isinstance(raw, list):
            return [TimeSlot(**item) if isinstance(item, dict) else item for item in raw]
        return _derive_time_slots(entries)

    @staticmethod
    def _parse_text_patterns(llm_extraction: dict[str, Any]) -> TextPatterns:
        raw = llm_extraction.get("text_patterns")
        if isinstance(raw, dict):
            return TextPatterns(**raw)
        return _build_default_text_patterns()
