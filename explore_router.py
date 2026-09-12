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
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

import psycopg
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates

import static_version
from timetable_extractor.database import changes as cq
from timetable_extractor.database import explore_queries as eq
from timetable_extractor.database.connection import DatabaseNotConfigured, database_url
from timetable_extractor.observability import correlation_id, get_logger

router = APIRouter(prefix="/explore", tags=["explore"])

logger = get_logger("timetable.explore")

#: A query slower than this gets an info line rather than debug. The explorer's
#: aggregates all run well under 500ms against a warm database.
SLOW_QUERY_MS = 500.0


def long_date(value: datetime, year: bool = True) -> str:
    """Render a date as "11 September 2026", with no leading zero on the day.

    The obvious spelling is ``strftime("%-d %B %Y")``, and that is what the
    changes page used until it was run on Windows. ``%-d`` is a glibc
    extension: it works on the Linux deployment and raises ``ValueError:
    Invalid format string`` on Windows' CRT, so every one of the 13
    `/explore/changes` tests failed on a developer machine while the live page
    rendered perfectly. Formatting the day separately is portable.
    """
    tail = value.strftime("%B %Y") if year else value.strftime("%B")
    return f"{value.day} {tail}"


templates = Jinja2Templates(directory=Path(__file__).resolve().parent / "templates")
templates.env.filters["urlpath"] = lambda value: quote(str(value), safe="")
templates.env.filters["long_date"] = long_date
templates.env.globals["asset_version"] = static_version.asset_version()
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


#: Sentinel for "not cached", so that a cached None still counts as a hit.
MISSING = object()


def cache_get(key: str, stat: str | None = None) -> Any:
    """
    A cached value, or MISSING if it is absent or stale.

    `stat` names the bucket the hit or miss is counted under. It matters for
    per-course keys: counted under their own names, 1,082 course codes would
    bury the handful of aggregates the ops endpoint exists to report.
    """
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < CACHE_TTL_SECONDS:
            _cache_stats[f"{stat or key}.hit"] += 1
            return hit[1]

    _cache_stats[f"{stat or key}.miss"] += 1
    return MISSING


def cache_put(key: str, value: Any) -> None:
    """Store a value against the current clock."""
    with _cache_lock:
        _cache[key] = (time.monotonic(), value)


def cached(key: str, producer: Callable[[], Any]) -> Any:
    """Memoise a query result for CACHE_TTL_SECONDS."""
    value = cache_get(key)
    if value is not MISSING:
        return value

    value = producer()
    cache_put(key, value)

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
        # A saved timetable stores the publication it was built against, so it
        # can notice the warehouse moving underneath it and offer to catch up.
        # This is the cheapest way for it to ask which publication is current.
        "publication_id": data.get("publication_id"),
        "published_at": _iso(data.get("published_at")),
        "imported_at": _iso(data.get("imported_at")),
        "checked_at": _iso(checked_at),
        "resource_count": data.get("resource_count", 0),
        "check_count": data.get("check_count", 0),
        "publication_count": data.get("publication_count", 0),
    }


def changes_banner_context() -> dict[str, Any] | None:
    """
    The one-line summary that sits under the provenance rail.

    Deliberately derived from the same cached change set the page itself
    reads, rather than a count query of its own. A banner claiming 55 moved
    classes above a page listing 47 would be worse than no banner, and the
    two counts differ because "moved" is a reading of the stored change, not
    the stored change itself.

    Returns None when there is nothing to say: one publication, or a republish
    that changed nothing.
    """
    try:
        data = cached("changes", lambda: query(cq.changes_for_page))
    except ExplorerUnavailable:
        # The rail above already reports the warehouse being unreachable.
        # Repeating it here would say the same thing twice.
        return None

    if not data or not data.get("total"):
        return None

    counts = data["counts"]
    return {
        # A saved dismissal is keyed on this, so a later republish brings the
        # banner back rather than staying dismissed forever.
        "publication_id": data["to_id"],
        "published_at": _iso(data["to_published_at"]),
        "moved": counts.get(cq.CLASS_MOVED, 0),
        "confirmed": counts.get(cq.CLASS_VENUE_CONFIRMED, 0),
        "courses_added": len(data["courses_added"]),
        "courses_dropped": len(data["courses_dropped"]),
        "total": data["total"],
    }


def page_context(request: Request, active: str, **extra: Any) -> dict[str, Any]:
    """Base template context shared by every explorer page."""
    context = {
        "request": request,
        "active": active,
        "total_weeks": eq.TOTAL_WEEKS,
        "day_order": eq.DAY_ORDER,
        "freshness": freshness_context(),
        "changes_banner": changes_banner_context(),
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


@router.get("/changes", include_in_schema=False)
async def changes_page(request: Request):
    """
    What the last republish changed.

    One hop: the current publication against the one before it. A student two
    publications behind needs a different answer, and gets it from the builder
    rather than here - see CHANGES-FEED-SPEC.md section 4.5.
    """
    try:
        changes = cached("changes", lambda: query(cq.changes_for_page))
    except ExplorerUnavailable as exc:
        return _unavailable(request, "changes", str(exc))

    return templates.TemplateResponse(
        request=request,
        name="explore/changes.html",
        context=page_context(
            request,
            "changes",
            changes=changes,
            # An explicit parameter, not the referrer: the referrer is empty on
            # a hard refresh and absent under some privacy settings, so the
            # back link would come and go for reasons a student cannot see.
            from_calendar=request.query_params.get("from") == "calendar",
        ),
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


# The timetable builder API
#
# Public and read-only like the pages above, and sharing their pool and cache,
# but answering JSON to the calendar rather than rendering anything. It lives
# here rather than in main.py so that there is one connection pool and one
# cache over the warehouse instead of two.

api_router = APIRouter(prefix="/api/timetable", tags=["timetable"])


#: How many courses one request may ask about. A whole semester is six or
#: seven, so this is not a limit a student meets by hand. It is here so that a
#: pasted list of hundreds is batched by the caller instead of arriving as one
#: query for most of the campus.
MAX_CODES_PER_REQUEST = 40


def _split_codes(raw: str) -> list[str]:
    """
    Split the `codes` parameter on commas only.

    Not on whitespace: "FOUN 1001 (FULL & PART-TIME)" and "CAPE BIOL" are real
    course codes with spaces in them, and splitting those apart would turn one
    course into three unrecognised fragments.
    """
    return [part.strip() for part in raw.split(",") if part.strip()]


@api_router.get("/sessions")
async def timetable_sessions(
    codes: str = Query(
        ...,
        description=(
            "Comma-separated course codes, with or without the space: "
            "COMP 1601,COMP2601. Unrecognised codes come back in notFound."
        ),
        examples=["COMP 1601,COMP 2601"],
    ),
):
    """
    Sessions for a set of courses, shaped for the timetable builder.

    Unrecognised codes are reported in `notFound` rather than failing the
    request, because a list pasted off a registration screenshot is expected to
    be of mixed quality and the courses that did resolve are still worth
    having.
    """
    wanted = _split_codes(codes)
    if not wanted:
        raise HTTPException(
            status_code=400, detail="codes must name at least one course"
        )
    if len(wanted) > MAX_CODES_PER_REQUEST:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{len(wanted)} codes requested; this endpoint takes at most "
                f"{MAX_CODES_PER_REQUEST} per request"
            ),
        )

    try:
        index = cached(
            "code_index", lambda: eq.build_code_index(query(eq.course_codes))
        )
        freshness = cached("freshness", lambda: query(eq.freshness))
        publication_id = freshness.get("publication_id")
        # The builder prints this on a student's timetable. The id alone is a
        # serial number and says nothing on paper; the date says how old the
        # data behind the page is.
        published_at = _iso(freshness.get("published_at"))

        # Resolved codes keep the caller's order and lose duplicates, so that
        # asking for the same course twice is one entry rather than two.
        resolved: dict[str, str] = {}
        not_found: list[str] = []
        for raw in wanted:
            published = eq.resolve_published_code(raw, index)
            if published is None:
                not_found.append(raw)
            else:
                resolved.setdefault(published, raw)

        # Sessions are cached per course, so overlapping requests share their
        # work: adding a seventh course does not re-fetch the other six.
        courses: dict[str, Any] = {}
        misses = []
        for code in resolved:
            hit = cache_get(f"sessions:{code}", stat="sessions")
            if hit is MISSING:
                misses.append(code)
            else:
                courses[code] = hit

        if misses:
            for course in query(eq.sessions_for_courses, misses):
                cache_put(f"sessions:{course['code']}", course)
                courses[course["code"]] = course
    except ExplorerUnavailable as exc:
        return JSONResponse({"error": str(exc)}, status_code=503)

    return JSONResponse(
        {
            "publicationId": publication_id,
            "publishedAt": published_at,
            "courses": [courses[code] for code in resolved if code in courses],
            "notFound": not_found,
        },
        headers={"Cache-Control": "public, max-age=300"},
    )


@api_router.get("/changes")
async def timetable_changes(
    codes: str = Query(
        ...,
        description=(
            "Comma-separated course codes, with or without the space. "
            "Unrecognised codes come back in notFound; recognised courses "
            "with nothing to report are simply absent from changes."
        ),
        examples=["ECCD 0110,FREN 3401"],
    ),
    since: int | None = Query(
        None,
        description=(
            "The publication the caller's timetable was built against. "
            "Omit for the previous publication, which is the right answer "
            "for someone who has not built one."
        ),
    ),
):
    """
    What changed for a set of courses, for the timetable builder.

    The answer depends on who is asking. A visitor wants the last republish;
    a student wants everything since the publication their timetable was
    built against, however many republishes ago that was. `since` is how they
    say which.

    That difference is computed as a direct diff between the two publications,
    never by replaying the hops between them: a class that moved and moved
    back would otherwise be reported as two changes when the honest answer is
    none. See CHANGES-FEED-SPEC.md section 4.5.
    """
    wanted = _split_codes(codes)
    if not wanted:
        raise HTTPException(
            status_code=400, detail="codes must name at least one course"
        )
    if len(wanted) > MAX_CODES_PER_REQUEST:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{len(wanted)} codes requested; this endpoint takes at most "
                f"{MAX_CODES_PER_REQUEST} per request"
            ),
        )

    try:
        index = cached(
            "code_index", lambda: eq.build_code_index(query(eq.course_codes))
        )

        resolved: dict[str, str] = {}
        unresolved: list[str] = []
        for raw in wanted:
            published = eq.resolve_published_code(raw, index)
            if published is None:
                unresolved.append(raw)
            else:
                resolved.setdefault(published, raw)

        # Unresolved codes are asked about too, rather than dismissed here.
        # A code that stopped resolving is exactly the symptom of a rename,
        # and a saved timetable holding `EDMA 11**` needs to be told it is now
        # `EDMA 1142` - which is the one answer "not found" cannot give.
        asked = list(resolved) + unresolved

        # Not cached per code set: the key would be unbounded in the number of
        # distinct course combinations, and the stored path is an indexed read.
        # The browser is told to hold the answer for five minutes instead.
        result = query(cq.changes_for_courses, asked, since) if asked else None
    except ExplorerUnavailable as exc:
        return JSONResponse({"error": str(exc)}, status_code=503)

    # A code that came back as a rename is not missing; it moved.
    renamed_from = {
        change["previousCode"]
        for change in (result or {}).get("changes", [])
        if change.get("previousCode")
    }
    not_found = [code for code in unresolved if code not in renamed_from]

    if result is None:
        # One publication, or nothing resolved. Neither is an error: there is
        # simply nothing that changed.
        return JSONResponse(
            {
                "fromPublicationId": None,
                "toPublicationId": None,
                "publishedAt": None,
                "previousPublishedAt": None,
                "sinceUnavailable": False,
                "changes": [],
                "notFound": not_found,
            },
            headers={"Cache-Control": "public, max-age=300"},
        )

    return JSONResponse(
        {
            "fromPublicationId": result["from_id"],
            "toPublicationId": result["to_id"],
            "publishedAt": _iso(result["to_published_at"]),
            "previousPublishedAt": _iso(result["from_published_at"]),
            # True when the caller named a publication the warehouse no longer
            # holds, so the answer is the default hop rather than theirs.
            "sinceUnavailable": result["since_unavailable"],
            "changes": result["changes"],
            "notFound": not_found,
        },
        headers={"Cache-Control": "public, max-age=300"},
    )
