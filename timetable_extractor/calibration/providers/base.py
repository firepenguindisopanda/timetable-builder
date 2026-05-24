"""
LLM Provider protocol and base types.

Any vision-capable LLM provider can implement this protocol
to be used in the calibration pipeline.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class LLMProvider(Protocol):
    """Protocol for LLM providers with vision capabilities."""

    name: str
    model: str

    async def extract_timetable(self, pdf_path: str) -> dict:
        """Phase 1: Extract course code + timetable entries from PDF images.

        Args:
            pdf_path: Path to the PDF file on disk.

        Returns:
            dict with keys: course_code, course_name, semester, entries, layout_notes
        """
        ...

    async def generate_config(self, pdf_path: str, extraction: dict) -> dict:
        """Phase 2: Analyze layout and generate parser configuration.

        Args:
            pdf_path: Path to the PDF file on disk.
            extraction: The result from extract_timetable().

        Returns:
            dict with keys: page_regions, day_columns, time_slot_map,
                          text_patterns, anomalies, confidence, layout_signature
        """
        ...
