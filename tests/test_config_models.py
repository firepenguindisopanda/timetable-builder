from __future__ import annotations

import pytest
from timetable_extractor.config.models import (
    PageRegions,
    DayColumn,
    DayColumns,
    TimeSlot,
    TextPatterns,
    CourseConfig,
    MongoCourseConfig,
    CalibrationSession,
)


class TestPageRegions:
    def test_default_values(self):
        pr = PageRegions()
        assert pr.header_top == 0.0
        assert pr.header_bottom == 0.15
        assert pr.table_top == 0.15
        assert pr.table_bottom == 0.85
        assert pr.footer_bottom == 0.92

    def test_custom_values(self):
        pr = PageRegions(header_top=0.1, table_top=0.2)
        assert pr.header_top == 0.1
        assert pr.table_top == 0.2


class TestCourseConfig:
    def test_default_factory(self):
        config = CourseConfig()
        assert config.page_regions.header_top == 0.0
        assert config.day_columns.monday is None
        assert config.time_slot_map == []
        assert config.text_patterns.activity_types == []
        assert config.confidence == 0.0
        assert config.layout_signature == ""

    def test_with_values(self):
        config = CourseConfig(
            time_slot_map=[TimeSlot(label="09:00", top=0.2, bottom=0.3)],
            day_columns=DayColumns(monday=DayColumn(left=0.1, right=0.3)),
            text_patterns=TextPatterns(activity_types=["Lecture", "Lab"]),
            confidence=0.95,
        )
        assert len(config.time_slot_map) == 1
        assert config.time_slot_map[0].label == "09:00"
        assert config.day_columns.monday is not None
        assert config.day_columns.monday.left == 0.1
        assert "Lecture" in config.text_patterns.activity_types
        assert config.confidence == 0.95

    def test_serialization_roundtrip(self):
        config = CourseConfig(confidence=0.8)
        data = config.model_dump()
        restored = CourseConfig(**data)
        assert restored.confidence == 0.8
        assert restored.page_regions.header_bottom == 0.15


class TestMongoCourseConfig:
    def test_required_fields(self):
        config = MongoCourseConfig(course_code="COMP1234", config=CourseConfig())
        assert config.course_code == "COMP1234"
        assert config.status == "draft"
        assert config.generated_by == "llm"
        assert config.version == 1

    def test_active_status(self):
        config = MongoCourseConfig(
            course_code="COMP5678",
            config=CourseConfig(),
            status="active",
            generated_by="manual",
        )
        assert config.status == "active"
        assert config.generated_by == "manual"


class TestCalibrationSession:
    def test_required_fields(self):
        session = CalibrationSession(
            course_code="COMP1234",
            pdf_filename="timetable_COMP1234.pdf",
        )
        assert session.course_code == "COMP1234"
        assert session.pdf_filename == "timetable_COMP1234.pdf"
        assert session.llm_provider == "nemotron"

    def test_with_provider(self):
        session = CalibrationSession(
            course_code="COMP5678",
            pdf_filename="test.pdf",
            llm_provider="openai",
            prompt_template_version="v2",
        )
        assert session.llm_provider == "openai"
        assert session.prompt_template_version == "v2"