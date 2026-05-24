from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock
from timetable_extractor.config.models import (
    CourseConfig,
    PageRegions,
    DayColumns,
    DayColumn,
    TimeSlot,
    TextPatterns,
)
from timetable_extractor.calibration.config_generator import ConfigGenerator


class TestConfigGenerator:
    @pytest.fixture
    def generator(self):
        return ConfigGenerator()

    def test_generate_with_complete_extraction(self, generator):
        """Test generate() with full structured LLM extraction data."""
        extraction_result = {
            "entries": [
                {
                    "day": "Monday",
                    "start_time": "09:00",
                    "end_time": "11:00",
                    "module": "COMP1234",
                    "type": "Lecture",
                    "staff": "Smith",
                    "room": "Room 101",
                    "weeks": "S2W1-S2W6",
                },
            ],
        }
        llm_extraction = {
            "page_regions": {
                "header_top": 0.05,
                "header_bottom": 0.12,
                "table_top": 0.12,
                "table_bottom": 0.88,
                "footer_bottom": 0.95,
            },
            "day_columns": {
                "monday": {"left": 0.1, "right": 0.3},
                "tuesday": {"left": 0.3, "right": 0.5},
            },
            "time_slot_map": [
                {"label": "09:00 - 11:00", "top": 0.2, "bottom": 0.3},
            ],
            "text_patterns": {
                "module_code_regex": r"[A-Z]{2,4}\d{4}",
                "activity_types": ["Lecture", "Tutorial"],
            },
            "confidence": 0.92,
            "layout_signature": "comp1234_v1",
        }

        config = generator.generate("COMP1234", extraction_result, llm_extraction)

        assert isinstance(config, CourseConfig)
        assert config.confidence == 0.92
        assert config.layout_signature == "comp1234_v1"
        assert config.page_regions.header_top == 0.05
        assert config.day_columns.monday is not None
        assert config.day_columns.monday.left == 0.1
        assert len(config.time_slot_map) == 1
        assert config.time_slot_map[0].label == "09:00 - 11:00"
        assert "Lecture" in config.text_patterns.activity_types

    def test_generate_with_minimal_data(self, generator):
        """Test generate() with no data — should produce default config."""
        config = generator.generate("COMP9999", {}, {})

        assert isinstance(config, CourseConfig)
        assert config.confidence == 0.0
        assert config.page_regions.header_top == 0.0
        assert config.day_columns.monday is None
        assert config.time_slot_map == []

    def test_generate_with_entries_no_layout(self, generator):
        """Test generate() with entries but no structured layout — heuristic derivation."""
        extraction_result = {
            "entries": [
                {
                    "day": "Monday",
                    "start_time": "09:00",
                    "end_time": "11:00",
                    "module": "COMP1234",
                    "type": "Lecture",
                },
                {
                    "day": "Tuesday",
                    "start_time": "14:00",
                    "end_time": "16:00",
                    "module": "COMP5678",
                    "type": "Lab",
                },
                {
                    "day": "Wednesday",
                    "start_time": "09:00",
                    "end_time": "10:00",
                    "module": "COMP9999",
                    "type": "Tutorial",
                },
            ],
            "confidence": 0.85,
        }
        llm_extraction = extraction_result.copy()

        config = generator.generate("COMP1234", extraction_result, llm_extraction)

        assert isinstance(config, CourseConfig)
        assert config.day_columns.monday is not None
        assert config.day_columns.tuesday is not None
        assert config.day_columns.wednesday is not None
        assert len(config.time_slot_map) > 0
        assert config.confidence == 0.85

    @patch("timetable_extractor.calibration.config_generator.get_collection")
    def test_save(self, mock_get_collection):
        """Test save() stores config in MongoDB."""
        mock_collection = MagicMock()
        mock_collection.insert_one.return_value.inserted_id = MagicMock()
        mock_collection.insert_one.return_value.inserted_id.__str__ = MagicMock(
            return_value="abc123"
        )
        mock_get_collection.return_value = mock_collection

        generator = ConfigGenerator()
        config = CourseConfig(confidence=0.9)
        config_id = generator.save(config, session_id="sess_001")

        assert config_id == "abc123"
        mock_get_collection.assert_called_once_with("course_configs")
        mock_collection.insert_one.assert_called_once()

        saved_doc = mock_collection.insert_one.call_args[0][0]
        assert saved_doc["course_code"] == "unknown"
        assert saved_doc["status"] == "draft"
        assert saved_doc["generated_by"] == "llm"

    @patch("timetable_extractor.calibration.config_generator.get_collection")
    def test_generate_and_save(self, mock_get_collection):
        """Test generate_and_save() composes both methods."""
        mock_collection = MagicMock()
        mock_collection.insert_one.return_value.inserted_id = MagicMock()
        mock_collection.insert_one.return_value.inserted_id.__str__ = MagicMock(
            return_value="def456"
        )
        mock_get_collection.return_value = mock_collection

        generator = ConfigGenerator()
        extraction_result = {
            "entries": [
                {"day": "Monday", "start_time": "09:00", "end_time": "11:00"}
            ],
            "confidence": 0.8,
        }

        config, config_id = generator.generate_and_save(
            "COMP1234", extraction_result, extraction_result
        )

        assert isinstance(config, CourseConfig)
        assert config_id == "def456"
