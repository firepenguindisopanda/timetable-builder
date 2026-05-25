"""
Central coordinator for the LLM calibration pipeline.

Runs extraction, config generation, and report generation
in sequence, persisting progress and results to MongoDB.
"""

from __future__ import annotations

import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from bson import ObjectId

from timetable_extractor.calibration.config_generator import ConfigGenerator
from timetable_extractor.calibration.providers.base import LLMProvider
from timetable_extractor.calibration.report_generator import ReportGenerator
from timetable_extractor.config.db import get_collection
from timetable_extractor.config.models import CourseConfig


class CalibrationOrchestrator:
    """Orchestrates the full LLM calibration pipeline for a course PDF."""

    def __init__(
        self,
        provider: LLMProvider,
        config_generator: Optional[ConfigGenerator] = None,
        report_generator: Optional[ReportGenerator] = None,
    ) -> None:
        self._provider = provider
        self._config_generator = config_generator or ConfigGenerator()
        self._report_generator = report_generator or ReportGenerator()

    async def calibrate(
        self,
        pdf_path: str | Path,
        course_code: str,
        session_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Run the full calibration pipeline: extract, configure, report."""
        pdf_path_str = str(pdf_path)
        sessions_coll = get_collection("calibration_sessions")

        # a) Create or retrieve session
        if session_id:
            doc = sessions_coll.find_one({"_id": ObjectId(session_id)})
            if doc is None:
                raise ValueError(f"Calibration session not found: {session_id}")
        else:
            now = datetime.now(timezone.utc)
            doc = {
                "course_code": course_code,
                "status": "in_progress",
                "phases": {},
                "created_at": now,
            }
            result = sessions_coll.insert_one(doc)
            session_id = str(result.inserted_id)

        # b) Phase 1 - LLM Extraction
        try:
            extraction_result = await self._provider.extract_timetable(pdf_path_str)
            sessions_coll.update_one(
                {"_id": ObjectId(session_id)},
                {"$set": {
                    "phases.extraction": {
                        "status": "completed",
                        "confidence": extraction_result.get("confidence", 0),
                    },
                }},
            )
        except Exception:
            sessions_coll.update_one(
                {"_id": ObjectId(session_id)},
                {"$set": {
                    "status": "failed",
                    "phases.extraction": {"status": "failed", "error": traceback.format_exc()},
                }},
            )
            raise

        # c) Phase 2 - Config Generation
        try:
            config, config_id = self._config_generator.generate_and_save(
                course_code,
                extraction_result,
                llm_extraction=extraction_result,
                session_id=session_id,
            )
            sessions_coll.update_one(
                {"_id": ObjectId(session_id)},
                {"$set": {
                    "phases.config_generation": {
                        "status": "completed",
                        "config_id": config_id,
                    },
                }},
            )
        except Exception:
            sessions_coll.update_one(
                {"_id": ObjectId(session_id)},
                {"$set": {
                    "status": "failed",
                    "phases.config_generation": {
                        "status": "failed",
                        "error": traceback.format_exc(),
                    },
                }},
            )
            raise

        # d) Phase 3 - Report Generation
        try:
            report = self._report_generator.generate_pattern_report(
                course_code,
                extraction_result,
                extraction_result,
                config,
            )
            sessions_coll.update_one(
                {"_id": ObjectId(session_id)},
                {"$set": {"phases.report": {"status": "completed"}}},
            )
        except Exception:
            sessions_coll.update_one(
                {"_id": ObjectId(session_id)},
                {"$set": {
                    "status": "failed",
                    "phases.report": {"status": "failed", "error": traceback.format_exc()},
                }},
            )
            raise

        # e) Final update
        confidence = extraction_result.get("confidence", 0.0)
        entries = extraction_result.get("entries", [])
        anomalies = extraction_result.get("anomalies", [])
        sessions_coll.update_one(
            {"_id": ObjectId(session_id)},
            {"$set": {
                "status": "completed",
                "config_id": config_id,
                "confidence": confidence,
                "report": report,
                "anomalies": anomalies,
                "updated_at": datetime.now(timezone.utc),
            }},
        )

        # f) Return result dict
        return {
            "session_id": session_id,
            "course_code": course_code,
            "config_id": config_id,
            "confidence": confidence,
            "entries_count": len(entries),
            "report": report,
            "config": config.model_dump() if isinstance(config, CourseConfig) else config,
        }

    async def get_session(self, session_id: str) -> Optional[dict[str, Any]]:
        """Load a calibration session from MongoDB by its _id."""
        doc = get_collection("calibration_sessions").find_one(
            {"_id": ObjectId(session_id)},
        )
        if doc is not None:
            doc["_id"] = str(doc["_id"])
        return doc

    async def list_sessions(
        self,
        course_code: Optional[str] = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """List calibration sessions, optionally filtered by course_code."""
        query = {}
        if course_code:
            query["course_code"] = course_code
        docs = list(
            get_collection("calibration_sessions")
            .find(query)
            .sort("created_at", -1)
            .limit(limit)
        )
        for doc in docs:
            doc["_id"] = str(doc["_id"])
        return docs
