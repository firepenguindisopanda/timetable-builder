"""
Structured logging and extraction diagnostics.

A CELCAT layout change does not crash the extractor. It quietly moves classes.
The "deW" case is the worked example: `Wed` reversed was missing from the day
label table, so in roughly one PDF in five no Wednesday row was ever built,
and every Wednesday class fell through to the band above and was filed under
Tuesday. Nothing raised. The only visible symptom was a day histogram that
looked a bit odd, three semesters later.

So the questions this module exists to answer are:

1. Did this extraction silently misfile anything? (unmatched day labels,
   missing day bands, blocks placed by fallback rather than by a real row)
2. Which PDFs produced nothing, or produced entries missing required fields?
3. Is the published layout drifting away from what the parser expects?
4. For the explorer: is a page slow, and is it the database or the render?

Everything here is either a structured log event or a counter attached to the
extraction result. There is no prose logging: every event has a stable name
and machine-readable fields, so a semester's worth of runs can be aggregated.
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
import time
import uuid
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator

# Correlation id for the current request or extraction run. Without it, log
# lines from concurrent work interleave into something unreadable.
correlation_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "correlation_id", default=None
)


def new_correlation_id() -> str:
    return uuid.uuid4().hex[:12]


@contextmanager
def correlated(cid: str | None = None) -> Iterator[str]:
    """Attach a correlation id to every log line emitted inside the block."""
    cid = cid or new_correlation_id()
    token = correlation_id.set(cid)
    try:
        yield cid
    finally:
        correlation_id.reset(token)


class JsonFormatter(logging.Formatter):
    """
    One JSON object per line.

    Anything passed as `extra={...}` is merged in at the top level, so events
    stay queryable instead of being interpolated into a message string.
    """

    RESERVED = frozenset(
        logging.LogRecord("", 0, "", 0, "", (), None).__dict__
    ) | {"message", "asctime", "taskName"}

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
            + f".{int(record.msecs):03d}Z",
            "level": record.levelname.lower(),
            "logger": record.name,
            "event": getattr(record, "event", record.getMessage()),
        }

        cid = correlation_id.get()
        if cid:
            payload["correlation_id"] = cid

        for key, value in record.__dict__.items():
            if key not in self.RESERVED and key != "event":
                payload[key] = value

        if record.exc_info:
            payload["error"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


def configure_logging(level: str | None = None, json_output: bool | None = None) -> None:
    """
    Install the root handler. Safe to call more than once.

    Defaults come from LOG_LEVEL and LOG_FORMAT so a deployment can turn on
    debug detail without a code change. Plain text stays the default for
    interactive CLI use, where JSON would be unreadable.
    """
    level = (level or os.environ.get("LOG_LEVEL") or "INFO").upper()
    if json_output is None:
        json_output = os.environ.get("LOG_FORMAT", "").lower() == "json"

    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, "_timetable_handler", False):
            root.removeHandler(handler)

    handler = logging.StreamHandler()
    handler._timetable_handler = True  # type: ignore[attr-defined]
    handler.setFormatter(
        JsonFormatter()
        if json_output
        else logging.Formatter("%(levelname)-7s %(name)s %(message)s")
    )
    root.addHandler(handler)
    root.setLevel(level)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


@contextmanager
def timed(logger: logging.Logger, event: str, **fields: Any) -> Iterator[dict[str, Any]]:
    """
    Time a block and log its duration, whether or not it raised.

    Yields a dict the caller can add fields to once they are known - a row
    count, say - so the timing line carries the context that explains it.
    """
    extra: dict[str, Any] = {}
    started = time.perf_counter()
    try:
        yield extra
    except Exception:
        logger.exception(
            "failed",
            extra={
                "event": f"{event}_failed",
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                **fields,
                **extra,
            },
        )
        raise
    else:
        logger.info(
            event,
            extra={
                "event": event,
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                **fields,
                **extra,
            },
        )


# Extraction diagnostics

# Findings that mean classes may have been placed on the wrong day or dropped.
# These are the ones worth failing a build over.
CORRUPTING_FINDINGS = frozenset(
    {
        "day_label_unmatched",
        "day_band_missing",
        "day_fallback_used",
        "day_unknown",
    }
)


@dataclass
class Diagnostics:
    """
    What went quietly wrong while reading one PDF.

    Collected rather than logged one-by-one so a caller extracting 1,600 files
    can aggregate across the corpus instead of grepping 1,600 log lines.
    """

    source: str = ""
    findings: Counter = field(default_factory=Counter)
    samples: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    #: Cap on stored examples per finding, so a badly broken PDF cannot
    #: balloon a batch run's memory.
    sample_limit: int = 5

    def add(self, finding: str, **fields: Any) -> None:
        self.findings[finding] += 1
        bucket = self.samples.setdefault(finding, [])
        if len(bucket) < self.sample_limit:
            bucket.append(fields)

    @property
    def corrupting(self) -> int:
        """Findings that imply a class may be on the wrong day."""
        return sum(n for f, n in self.findings.items() if f in CORRUPTING_FINDINGS)

    def as_dict(self) -> dict[str, Any]:
        return {
            "findings": dict(self.findings),
            "samples": self.samples,
            "corrupting": self.corrupting,
        }

    def emit(self, logger: logging.Logger) -> None:
        """
        Log one line per distinct finding.

        Anything that can misplace a class is a warning: it is handled, the
        run continues, but a human should look at the trend.
        """
        for finding, count in sorted(self.findings.items()):
            logger.warning(
                finding,
                extra={
                    "event": f"extract.{finding}",
                    "source": self.source,
                    "count": count,
                    "samples": self.samples.get(finding, []),
                },
            )


__all__ = [
    "CORRUPTING_FINDINGS",
    "Diagnostics",
    "JsonFormatter",
    "configure_logging",
    "correlated",
    "correlation_id",
    "get_logger",
    "new_correlation_id",
    "timed",
]
