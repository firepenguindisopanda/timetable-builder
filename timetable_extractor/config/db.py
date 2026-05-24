"""
MongoDB client singleton for the calibration module.
Uses environment variables for connection.
"""

from __future__ import annotations

from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database
from pydantic_settings import BaseSettings

# Lazy-loaded globals
_client: MongoClient | None = None
_db: Database | None = None


class MongoSettings(BaseSettings):
    """MongoDB connection settings from environment."""

    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_db_name: str = "timetable_calibration"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


class NemotronSettings(BaseSettings):
    """NVIDIA NIM API settings for the Nemotron LLM provider."""

    nvidia_api_key: str = ""
    nvidia_base_url: str = "https://ai.api.nvidia.com/v1/gr/meta/llama-3.2-90b-vision-instruct/chat/completions"
    nvidia_model: str = "nvidia/nemotron-4-340b-vision"
    nvidia_max_tokens: int = 4096
    nvidia_temperature: float = 0.1

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


def get_mongo_client() -> MongoClient:
    """Return a singleton MongoClient (sync)."""
    global _client
    if _client is None:
        settings = MongoSettings()
        _client = MongoClient(settings.mongodb_uri)
    return _client


def get_database() -> Database:
    """Return a singleton Database handle."""
    global _db
    if _db is None:
        settings = MongoSettings()
        _db = get_mongo_client()[settings.mongodb_db_name]
    return _db


def get_collection(name: str) -> Collection:
    """Get a named collection from the calibration database."""
    return get_database()[name]


class AdminSettings(BaseSettings):
    """Admin authentication settings from environment."""

    admin_api_key: str = ""
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


def close_mongo_client() -> None:
    """Close the MongoDB connection (call on shutdown)."""
    global _client, _db
    if _client is not None:
        _client.close()
        _client = None
        _db = None
