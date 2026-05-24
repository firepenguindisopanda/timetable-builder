"""
Load the active extraction config for a given course from MongoDB.
Returns None if no active config exists (extractor falls back to generic logic).
"""

from __future__ import annotations

from typing import Any

from timetable_extractor.config.db import get_collection
from timetable_extractor.config.models import CourseConfig


def load_active_config(course_code: str) -> CourseConfig | None:
    """
    Load the active config for a course from MongoDB.

    Args:
        course_code: e.g. "COMP6205"

    Returns:
        CourseConfig if an active config exists, None otherwise.
    """
    collection = get_collection("course_configs")
    doc = collection.find_one(
        {"course_code": course_code.upper(), "status": "active"},
        sort=[("version", -1)],
    )
    if doc is None:
        return None
    return CourseConfig(**doc["config"])


def list_configs(
    status: str | None = None,
    course_code: str | None = None,
) -> list[dict[str, Any]]:
    """List configs from MongoDB with optional filters."""
    collection = get_collection("course_configs")
    query: dict[str, Any] = {}
    if status:
        query["status"] = status
    if course_code:
        query["course_code"] = course_code.upper()

    docs = collection.find(query).sort("created_at", -1)
    return list(docs)


def activate_config(config_id: str) -> bool:
    """
    Promote a draft config to active.
    Deactivates any other active configs for the same course.
    """
    from bson import ObjectId

    collection = get_collection("course_configs")
    doc = collection.find_one({"_id": ObjectId(config_id)})
    if doc is None:
        return False

    course_code = doc["course_code"]

    # Deactivate all other active configs for this course
    collection.update_many(
        {"course_code": course_code, "status": "active"},
        {"$set": {"status": "superseded"}},
    )

    # Activate the target config
    collection.update_one(
        {"_id": ObjectId(config_id)},
        {"$set": {"status": "active", "updated_at": None}},
    )
    return True
