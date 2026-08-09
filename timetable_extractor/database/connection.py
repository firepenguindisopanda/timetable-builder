"""
Postgres connection handling.

The connection string comes from DATABASE_URL (see .env.example). Nothing in
this package hardcodes credentials.
"""

from __future__ import annotations

import os
from pathlib import Path

import psycopg

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


class DatabaseNotConfigured(RuntimeError):
    """Raised when DATABASE_URL is missing, so callers can fail helpfully."""


def database_url() -> str:
    """Read DATABASE_URL, loading .env first if python-dotenv is installed."""
    if not os.environ.get("DATABASE_URL"):
        try:
            from dotenv import load_dotenv

            load_dotenv()
        except ImportError:
            pass

    url = os.environ.get("DATABASE_URL")
    if not url:
        raise DatabaseNotConfigured(
            "DATABASE_URL is not set. Copy .env.example to .env and add your "
            "Postgres connection string."
        )
    return url


def connect(url: str | None = None, **kwargs) -> psycopg.Connection:
    """Open a connection. Caller owns the lifetime (use as a context manager)."""
    return psycopg.connect(url or database_url(), **kwargs)


def apply_schema(conn: psycopg.Connection) -> None:
    """Create every table, index and view. Safe to run repeatedly."""
    with conn.cursor() as cur:
        cur.execute(SCHEMA_PATH.read_text())
    conn.commit()
