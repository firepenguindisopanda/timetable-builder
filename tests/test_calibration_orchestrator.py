from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from timetable_extractor.calibration.config_generator import ConfigGenerator
from timetable_extractor.calibration.orchestrator import CalibrationOrchestrator
from timetable_extractor.calibration.report_generator import ReportGenerator
from timetable_extractor.config.models import CourseConfig


class MockLLMProvider:
    """Mock LLM provider that returns canned responses for testing."""

    async def extract_timetable(self, pdf_path: str) -> dict:
        return {
            "entries": [
                {
                    "day": "Monday",
                    "start_time": "09:00 AM",
                    "end_time": "11:00 AM",
                    "module": "COMP1234",
                    "type": "Lecture",
                    "staff": "Smith",
                    "room": "Room 101",
                },
                {
                    "day": "Wednesday",
                    "start_time": "02:00 PM",
                    "end_time": "04:00 PM",
                    "module": "COMP1234",
                    "type": "Lab",
                    "staff": "Jones",
                    "room": "Lab 2",
                },
            ],
            "layout_notes": "Standard CELCAT layout with 5 day columns",
            "confidence": 0.95,
        }

    async def generate_config(
        self, pdf_path: str, course_code: str, extraction_result: dict
    ) -> CourseConfig:
        return CourseConfig(confidence=0.95)


class TestCalibrationOrchestrator:
    @pytest.fixture
    def mock_provider(self):
        return MockLLMProvider()

    @pytest.fixture
    def mock_config_generator(self):
        gen = MagicMock(spec=ConfigGenerator)
        gen.generate_and_save.return_value = (CourseConfig(confidence=0.95), "mock_config_123")
        return gen

    @pytest.fixture
    def mock_report_generator(self):
        rg = MagicMock(spec=ReportGenerator)
        rg.generate_pattern_report.return_value = (
            "# Calibration Report\n\nMock report for testing"
        )
        return rg

    @pytest.mark.asyncio
    @patch("timetable_extractor.calibration.orchestrator.get_collection")
    async def test_calibrate_full_pipeline(
        self,
        mock_get_collection,
        mock_provider,
        mock_config_generator,
        mock_report_generator,
    ):
        """Test the full calibration pipeline with mock components."""
        mock_collection = MagicMock()
        mock_collection.insert_one.return_value.inserted_id.__str__ = MagicMock(
            return_value="507f1f77bcf86cd799439011",
        )
        mock_collection.find_one.return_value = None
        mock_get_collection.return_value = mock_collection

        orchestrator = CalibrationOrchestrator(
            provider=mock_provider,
            config_generator=mock_config_generator,
            report_generator=mock_report_generator,
        )

        result = await orchestrator.calibrate(
            pdf_path="/mock/path/test.pdf",
            course_code="COMP1234",
        )

        assert result["course_code"] == "COMP1234"
        assert result["session_id"] == "507f1f77bcf86cd799439011"
        assert result["config_id"] == "mock_config_123"
        assert result["confidence"] == 0.95
        assert result["entries_count"] == 2
        assert "report" in result
        assert "Mock report" in result["report"]

    @pytest.mark.asyncio
    @patch("timetable_extractor.calibration.orchestrator.get_collection")
    async def test_orchestrator_uses_default_components(
        self, mock_get_collection,
    ):
        """Test that orchestrator creates default components when not provided."""
        orchestrator = CalibrationOrchestrator(provider=MockLLMProvider())

        assert orchestrator._config_generator is not None
        assert orchestrator._report_generator is not None
