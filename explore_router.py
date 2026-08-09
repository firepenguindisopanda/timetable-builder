"""
The public, read-only timetable explorer.

Everything under `/explore` is a view of the warehouse and never writes to it.
Pages are server-rendered; the one large payload (the course index) is served
as JSON so the browser can search and filter 1,000-odd courses without a round
trip per keystroke.

Reference data changes at most once a day, when UWI republishes, so the
expensive aggregate queries sit behind a short in-process cache.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

import psycopg
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates

from timetable_extractor.database import explore_queries as eq
from timetable_extractor.database.connection import DatabaseNotConfigured, database_url
from timetable_extractor.observability import correlation_id, get_logger

router = APIRouter(prefix="/explore", tags=["explore"])

logger = get_logger("timetable.explore")

#: A query slower than this gets an info line rather than debug. The explorer's
#: aggregates all run well under 500ms against a warm database.
SLOW_QUERY_MS = 500.0

templates = Jinja2Templates(directory=Path(__file__).resolve().parent / "templates")
templates.env.filters["urlpath"] = lambda value: quote(str(value), safe="")
# Positioning a week grid is arithmetic, not markup, so the template calls into
# Python for it rather than doing minute maths in Jinja.
templates.env.globals["week_layout"] = eq.week_layout

# How long a cached query stays fresh. The underlying data changes when the
# warehouse is reloaded, which is a daily event at most.
CACHE_TTL_SECONDS = 300


# Connection pool

_pool = None
_pool_lock = threading.Lock()


def get_pool():
    """
    Open the connection pool on first use.

    Built lazily so importing this module never touches the network, and so a
    server with no DATABASE_URL still starts and serves an honest error page.

    Managed Postgres (Neon, Supabase, RDS behind a proxy) hangs up on idle
    connections, and it does so without telling the client. A pooled connection
    that has been sitting unused since the last page view is therefore already
    dead when it is handed out, and the query fails with "SSL connection has
    been closed unexpectedly" - once. The next request gets a fresh connection
    and works, which is why the failure looked like it healed on refresh.

    `check` costs one round trip per checkout and removes the whole class of
    problem: the pool validates a connection before lending it and quietly
    replaces it if it is dead.
    """
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                from psycopg_pool import ConnectionPool

                _pool = ConnectionPool(
                    database_url(),
                    min_size=1,
                    max_size=4,
                    kwargs={"autocommit": True},
                    # Validate before lending. Without this the first visit
                    # after an idle spell always 503s.
                    check=ConnectionPool.check_connection,
                    # Retire connections before the server's own idle timeout
                    # can reach them, so `check` rarely has to do the work.
                    max_idle=120.0,
                    max_lifetime=1800.0,
                    timeout=10.0,
                    open=True,
                )
    return _pool


def close_pool() -> None:
    """Release pooled connections at shutdown."""
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


class ExplorerUnavailable(Exception):
    """
    The warehouse could not be reached.

    The message is rendered on a public page, so it must never carry the
    driver's own text: a psycopg connection error names the host, port and
    database user. The detail belongs in the log, tied to the request id the
    page asks the reader to quote.
    """


def query(fn: Callable[..., Any], *args: Any) -> Any:
    """
    Run a read-only query function against a pooled connection.

    Timed so "the page is slow" can be answered with "the database took 900ms"
    rather than a guess. Only slow queries are logged at info; the rest stay at
    debug so a busy page does not emit a line per query.
    """
    started = time.perf_counter()
    try:
        pool = get_pool()
    except DatabaseNotConfigured as exc:
        logger.error(
            "explore.db_unconfigured",
            extra={"event": "explore.db_unconfigured", "query": fn.__name__},
        )
        raise ExplorerUnavailable(
            "This server has no timetable database configured."
        ) from exc

    # One retry, because a connection can also be dropped *during* a query,
    # which no amount of checking beforehand can prevent. Every query here is
    # a read, so running it twice is safe.
    for attempt in (1, 2):
        try:
            with pool.connection() as conn:
                result = fn(conn, *args)
            break
        except psycopg.OperationalError as exc:
            if attempt == 1:
                logger.warning(
                    "explore.query_retry",
                    extra={
                        "event": "explore.query_retry",
                        "query": fn.__name__,
                        "error_type": type(exc).__name__,
                    },
                )
                continue
            logger.exception(
                "explore.query_failed",
                extra={
                    "event": "explore.query_failed",
                    "query": fn.__name__,
                    "error_type": type(exc).__name__,
                    "attempts": attempt,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                },
            )
            raise ExplorerUnavailable(
                "The timetable database did not respond."
            ) from exc
        except Exception as exc:  # pragma: no cover - depends on the database
            # The driver's message names the host and database user, so it is
            # logged and not raised onward.
            logger.exception(
                "explore.query_failed",
                extra={
                    "event": "explore.query_failed",
                    "query": fn.__name__,
                    "error_type": type(exc).__name__,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                },
            )
            raise ExplorerUnavailable(
                "The timetable database did not respond."
            ) from exc

    duration_ms = round((time.perf_counter() - started) * 1000, 1)
    logger.log(
        logging.INFO if duration_ms >= SLOW_QUERY_MS else logging.DEBUG,
        "explore.query",
        extra={
            "event": "explore.query",
            "query": fn.__name__,
            "duration_ms": duration_ms,
            "slow": duration_ms >= SLOW_QUERY_MS,
        },
    )
    return result


# Cache

_cache: dict[str, tuple[float, Any]] = {}
_cache_lock = threading.Lock()


#: Hit and miss counts per key, so cache effectiveness is a question the logs
#: can answer rather than something to infer from latency.
_cache_stats: Counter[str] = Counter()


def cached(key: str, producer: Callable[[], Any]) -> Any:
    """Memoise a query result for CACHE_TTL_SECONDS."""
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < CACHE_TTL_SECONDS:
            _cache_stats[f"{key}.hit"] += 1
            return hit[1]

    _cache_stats[f"{key}.miss"] += 1
    value = producer()
    with _cache_lock:
        _cache[key] = (now, value)

    logger.debug(
        "explore.cache_miss",
        extra={"event": "explore.cache_miss", "key": key},
    )
    return value


def cache_stats() -> dict[str, Any]:
    """Hit rate per cached key, for the ops endpoint."""
    keys = sorted({k.rsplit(".", 1)[0] for k in _cache_stats})
    out = {}
    for key in keys:
        hits = _cache_stats[f"{key}.hit"]
        misses = _cache_stats[f"{key}.miss"]
        total = hits + misses
        out[key] = {
            "hits": hits,
            "misses": misses,
            "hit_rate": round(hits / total, 3) if total else None,
        }
    return out


def clear_cache() -> None:
    """Drop every cached result; used after the warehouse is reloaded."""
    with _cache_lock:
        _cache.clear()
    logger.info("explore.cache_cleared", extra={"event": "explore.cache_cleared"})


# Shared page context


def _iso(value: Any) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else None


def freshness_context() -> dict[str, Any]:
    """
    The provenance banner every explorer page carries.

    Timestamps go to the template as ISO strings and are rendered relative in
    the browser, so a student in Trinidad sees local time rather than the
    server's.
    """
    data = cached("freshness", lambda: query(eq.freshness))
    checked_at = data.get("checked_at")

    age_hours = None
    if checked_at is not None:
        from datetime import datetime, timezone

        age_hours = (
            datetime.now(timezone.utc) - checked_at
        ).total_seconds() / 3600

    # Three distinct states, because "we have not looked recently" is a
    # different problem from "UWI changed it and we have not caught up".
    if data.get("update_pending"):
        status, label = "pending", "Update not yet imported"
    elif age_hours is None:
        status, label = "unknown", "Never checked"
    elif age_hours > 24 * 7:
        status, label = "stale", "Not checked in over a week"
    elif age_hours > 48:
        status, label = "ageing", "Last checked over 2 days ago"
    else:
        status, label = "current", "Up to date"

    return {
        "status": status,
        "status_label": label,
        "published_at": _iso(data.get("published_at")),
        "imported_at": _iso(data.get("imported_at")),
        "checked_at": _iso(checked_at),
        "resource_count": data.get("resource_count", 0),
        "check_count": data.get("check_count", 0),
        "publication_count": data.get("publication_count", 0),
    }


def page_context(request: Request, active: str, **extra: Any) -> dict[str, Any]:
    """Base template context shared by every explorer page."""
    context = {
        "request": request,
        "active": active,
        "total_weeks": eq.TOTAL_WEEKS,
        "day_order": eq.DAY_ORDER,
        "freshness": freshness_context(),
        "unavailable": None,
    }
    context.update(extra)
    return context


def error_page(request: Request, status_code: int, detail: str):
    """
    Render an explorer error in the explorer's own shell.

    A student who mistypes a course code should land on a page that tells them
    how codes work, not on a JSON body.
    """
    headings = {
        404: "That is not in the timetable",
        503: "The timetable is not available right now",
    }
    try:
        context = page_context(request, "explore")
    except ExplorerUnavailable:
        # The provenance rail needs the database too; without it, drop the rail
        # rather than turning a 404 into a 500.
        context = {
            "request": request,
            "active": "explore",
            "total_weeks": eq.TOTAL_WEEKS,
            "day_order": eq.DAY_ORDER,
            "freshness": None,
        }

    context.update(
        heading=headings.get(status_code, "Something went wrong"),
        detail=detail,
    )
    return templates.TemplateResponse(
        request=request,
        name="explore/error.html",
        context=context,
        status_code=status_code,
    )


def _unavailable(request: Request, active: str, message: str):
    """Render the shell with an explanation instead of failing with a 500."""
    return templates.TemplateResponse(
        request=request,
        name="explore/unavailable.html",
        context={
            "request": request,
            "active": active,
            "total_weeks": eq.TOTAL_WEEKS,
            "day_order": eq.DAY_ORDER,
            "freshness": None,
            "unavailable": message,
            # The only thing that ties this page to the logged cause.
            "request_id": correlation_id.get(),
        },
        status_code=503,
    )


# Pages


@router.get("", include_in_schema=False)
async def explore_index(request: Request):
    """Landing page: campus heat, search, and the full course list."""
    try:
        stats = cached("overview", lambda: query(eq.overview))
        heat = cached("heat", lambda: query(eq.campus_heat))
        courses = cached("courses", lambda: query(eq.course_index))
    except ExplorerUnavailable as exc:
        return _unavailable(request, "explore", str(exc))

    faculties = sorted({c["faculty"] for c in courses if c["faculty"]})
    types = sorted({t for c in courses for t in (c["types"] or [])})

    return templates.TemplateResponse(
        request=request,
        name="explore/index.html",
        context=page_context(
            request,
            "explore",
            stats=stats,
            heat=heat,
            course_count=len(courses),
            faculties=faculties,
            activity_types=types,
        ),
    )


@router.get("/courses.json", include_in_schema=False)
async def courses_json():
    """The whole course index, for client-side search and filtering."""
    try:
        courses = cached("courses", lambda: query(eq.course_index))
    except ExplorerUnavailable as exc:
        return JSONResponse({"error": str(exc)}, status_code=503)

    return JSONResponse(
        {"courses": courses},
        headers={"Cache-Control": "public, max-age=300"},
    )


@router.get("/ops.json", tags=["ops"])
async def ops_health():
    """
    Machine-readable data health, for monitoring rather than for students.

    Aggregates only - the timetable it summarises is already public. The
    `day_distribution.skewed` flag is the one worth alerting on: it is the
    symptom a student would feel (classes on the wrong day), not a cause.
    """
    try:
        fresh = freshness_context()
        days = cached("day_distribution", lambda: query(eq.day_distribution))
        stats = cached("overview", lambda: query(eq.overview))
    except ExplorerUnavailable as exc:
        return JSONResponse(
            {"status": "unavailable", "detail": str(exc)}, status_code=503
        )

    problems = []
    if days["skewed"]:
        problems.append(
            f"{days['busiest_weekday']} has {days['skew_ratio']}x the median "
            "weekday's classes, which usually means a day label was not "
            "recognised and that day's classes landed on the day above"
        )
    if fresh["status"] in {"stale", "unknown"}:
        problems.append(f"freshness: {fresh['status_label'].lower()}")
    if fresh["status"] == "pending":
        problems.append("a republished timetable has not been imported yet")

    return JSONResponse(
        {
            "status": "degraded" if problems else "ok",
            "problems": problems,
            "freshness": fresh,
            "totals": stats,
            "day_distribution": days,
            "cache": cache_stats(),
        },
        headers={"Cache-Control": "no-store"},
    )


@router.get("/course/{code:path}", include_in_schema=False)
async def course_page(request: Request, code: str):
    """One course: its week pattern, its grid, and every session."""
    try:
        course = query(eq.course_detail, code)
    except ExplorerUnavailable as exc:
        return _unavailable(request, "explore", str(exc))

    if course is None:
        raise HTTPException(
            status_code=404,
            detail=f"No course '{eq.normalise_course_code(code)}' in this timetable",
        )

    return templates.TemplateResponse(
        request=request,
        name="explore/course.html",
        context=page_context(request, "explore", course=course),
    )


@router.get("/rooms", include_in_schema=False)
async def rooms_page(request: Request):
    """Every room with something booked in it."""
    try:
        rooms = cached("rooms", lambda: query(eq.room_index))
    except ExplorerUnavailable as exc:
        return _unavailable(request, "rooms", str(exc))

    return templates.TemplateResponse(
        request=request,
        name="explore/rooms.html",
        context=page_context(request, "rooms", rooms=rooms),
    )


@router.get("/room/{code:path}", include_in_schema=False)
async def room_page(request: Request, code: str):
    """One room's week."""
    try:
        room = query(eq.room_detail, code)
    except ExplorerUnavailable as exc:
        return _unavailable(request, "rooms", str(exc))

    if room is None:
        raise HTTPException(status_code=404, detail=f"Nothing booked in '{code}'")

    return templates.TemplateResponse(
        request=request,
        name="explore/room.html",
        context=page_context(request, "rooms", room=room),
    )


@router.get("/staff", include_in_schema=False)
async def staff_page(request: Request):
    """Every lecturer with a class this semester."""
    try:
        people = cached("staff", lambda: query(eq.staff_index))
    except ExplorerUnavailable as exc:
        return _unavailable(request, "staff", str(exc))

    return templates.TemplateResponse(
        request=request,
        name="explore/staff_index.html",
        context=page_context(request, "staff", people=people),
    )


@router.get("/staff/{name:path}", include_in_schema=False)
async def staff_detail_page(request: Request, name: str):
    """One lecturer's teaching week."""
    try:
        person = query(eq.staff_detail, name)
    except ExplorerUnavailable as exc:
        return _unavailable(request, "staff", str(exc))

    if person is None:
        raise HTTPException(status_code=404, detail=f"No classes listed for '{name}'")

    return templates.TemplateResponse(
        request=request,
        name="explore/staff.html",
        context=page_context(request, "staff", person=person),
    )
