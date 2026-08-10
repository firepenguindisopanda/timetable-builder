"""
CELCAT Timetable Extraction - FastAPI Server

Exposes the timetable extraction, download, and evaluation workflows
as HTTP endpoints. The existing timetable_extractor package provides
all core logic; this module only wires it up to FastAPI.

Run with:
    uvicorn app:app --reload --port 8000
    # or using uv:
    uv run uvicorn main:app --reload --port 8000

Interactive docs:
    http://localhost:8000/docs
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import List, Optional

import logging
import os
import time
from collections import Counter
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exception_handlers import http_exception_handler
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from schemas import (
    ActivateConfigRequest,
    ActivateConfigResponse,
    BatchExtractRequest,
    CalibrateRequest,
    CalibrateResponse,
    ConfigListResponse,
    ConfigSummary,
    DownloadRequest,
    DownloadResponse,
    EvaluateRequest,
    EvaluateResponse,
    ExtractResponse,
    HealthResponse,
    SessionListResponse,
    SessionSummary,
    TimetableResult,
)
from timetable_extractor import extract_timetable, observability

import explore_router
import static_version

# --- Admin Auth ---

class AdminVerifyRequest(BaseModel):
    api_key: str


def get_admin_settings():
    from timetable_extractor.config.db import AdminSettings

    return AdminSettings()


async def require_admin_key(
    x_api_key: str | None = Header(None),
    settings = Depends(get_admin_settings),
):
    """
    Check the X-API-Key header against ADMIN_API_KEY.

    With no key configured the admin surface is closed rather than open: a
    deployment that never sets one simply cannot reach these endpoints. That
    is reported as 503 and not 500, because an intentionally disabled feature
    is not a server fault, and a deployment serving only the public timetable
    is expected to leave the key unset.
    """
    if not settings.admin_api_key:
        raise HTTPException(
            status_code=503,
            detail=(
                "Admin endpoints are disabled on this deployment. "
                "Set ADMIN_API_KEY to enable them."
            ),
        )
    if not x_api_key:
        raise HTTPException(
            status_code=401,
            detail="Missing X-API-Key header. Log in at /admin/login first.",
        )
    if x_api_key != settings.admin_api_key:
        raise HTTPException(status_code=403, detail="Invalid API key")
    return x_api_key


observability.configure_logging()
logger = observability.get_logger("timetable.http")

# Static assets are logged at debug: they are numerous, uninteresting when
# healthy, and would bury the request events that matter.
QUIET_PATH_PREFIXES = ("/assets", "/favicon")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Hold the explorer's read-only connection pool for the process lifetime."""
    logger.info("server_start", extra={"event": "server_start", "version": "1.0.0"})
    yield
    explore_router.close_pool()
    logger.info("server_stop", extra={"event": "server_stop"})


app = FastAPI(
    title="CELCAT Timetable Extraction API",
    description=(
        "Extract structured class data (day, times, course, staff, room) "
        "from CELCAT-generated timetable PDFs."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# The timetable is public data, so cross-origin reads are allowed by default,
# but `allow_credentials=True` alongside them was both unsafe and inert:
# browsers reject a wildcard origin on a credentialed request. Nothing here
# authenticates with cookies - the admin key travels in a header - so
# credentialed cross-origin requests are not needed at all.
# Set CORS_ALLOW_ORIGINS to a comma-separated list to narrow it further.
CORS_ALLOW_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("CORS_ALLOW_ORIGINS", "*").split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOW_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-API-Key"],
)

# The explorer's course index is ~380 KB of JSON that compresses to a fraction
# of that, and it is fetched on every visit to /explore.
app.add_middleware(GZipMiddleware, minimum_size=1024)

@app.middleware("http")
async def request_telemetry(request: Request, call_next):
    """
    Give every request an id, time it, and log the outcome.

    The id goes out on the response so a student reporting "this page was
    slow" can quote something that finds the exact request in the logs.
    """
    incoming = request.headers.get("x-request-id")
    with observability.correlated(incoming) as request_id:
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "request_failed",
                extra={
                    "event": "request_failed",
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                },
            )
            raise

        duration_ms = round((time.perf_counter() - started) * 1000, 1)
        response.headers["x-request-id"] = request_id

        quiet = request.url.path.startswith(QUIET_PATH_PREFIXES)
        # Route template, not the raw path: a per-course path would make
        # aggregation useless and, in a metrics backend, unbounded.
        route = request.scope.get("route")
        level = (
            logging.DEBUG
            if quiet and response.status_code < 400
            else logging.WARNING
            if response.status_code >= 500
            else logging.INFO
        )
        logger.log(
            level,
            "request",
            extra={
                "event": "request",
                "method": request.method,
                "path": request.url.path,
                "route": getattr(route, "path", request.url.path),
                "status": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        return response


app.include_router(explore_router.router)
# Public and read-only, and deliberately from the same module as /explore so
# both share one connection pool and one cache over the warehouse.
app.include_router(explore_router.api_router)


@app.exception_handler(StarletteHTTPException)
async def explorer_aware_http_exception(request: Request, exc: StarletteHTTPException):
    """Render explorer errors as pages; everything else keeps the JSON default."""
    if request.url.path.startswith("/explore"):
        return explore_router.error_page(request, exc.status_code, str(exc.detail))
    return await http_exception_handler(request, exc)

templates = Jinja2Templates(directory=Path(__file__).resolve().parent / "templates")
# Every asset URL carries this, so a deploy that changes a script changes the
# URL asking for it and no browser can pair new HTML with stale JavaScript.
templates.env.globals["asset_version"] = static_version.asset_version()

# Serve static files from assets folder
assets_dir = Path(__file__).resolve().parent / "assets"
if assets_dir.exists():
    app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """
    Browsers ask for this at the root whatever the page says, so serve it there
    rather than letting every visit log a 404.
    """
    icon = assets_dir / "favicon.ico"
    if not icon.exists():
        raise HTTPException(status_code=404, detail="No favicon")
    return FileResponse(
        icon,
        media_type="image/x-icon",
        headers={"Cache-Control": "public, max-age=86400"},
    )


def _build_extract_response(results: list[dict]) -> ExtractResponse:
    """Convert raw extraction dicts into a typed ExtractResponse."""
    typed_results = [TimetableResult(**r) for r in results]
    total_entries = sum(len(r.entries) for r in typed_results)

    # Roll the per-file findings up, so a caller can tell at a glance whether
    # this batch parsed cleanly without walking every result.
    findings: Counter[str] = Counter()
    corrupting = 0
    for result in typed_results:
        if result.diagnostics:
            findings.update(result.diagnostics.findings)
            corrupting += result.diagnostics.corrupting

    return ExtractResponse(
        results=typed_results,
        total_files=len(typed_results),
        total_entries=total_entries,
        findings=dict(findings),
        corrupting=corrupting,
    )


@app.get("/", include_in_schema=False)
async def index(request: Request):
    """Serve the single-page dashboard."""
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"active": "home", "version": "1.0.0", "request": request},
    )


@app.get("/health", response_model=HealthResponse)
async def health():
    """Liveness check."""
    return HealthResponse(version="1.0.0")


# --- Admin Authentication Pages ---


@app.get("/admin/login", include_in_schema=False)
async def admin_login_page(request: Request):
    """Serve the admin login page."""
    return templates.TemplateResponse(
        request=request,
        name="admin_login.html",
        context={
            "active": "admin",
            "version": "1.0.0",
            "request": request,
        },
    )


@app.get("/admin", include_in_schema=False)
async def admin_dashboard_page(request: Request):
    """Serve the admin dashboard page."""
    return templates.TemplateResponse(
        request=request,
        name="admin.html",
        context={
            "active": "admin",
            "version": "1.0.0",
            "request": request,
        },
    )


@app.post("/admin/verify")
async def admin_verify_key(request: AdminVerifyRequest, settings=Depends(get_admin_settings)):
    """Check if the provided API key matches the configured admin key."""
    if not settings.admin_api_key:
        raise HTTPException(status_code=500, detail="Admin API key not configured on server")
    if request.api_key == settings.admin_api_key:
        return {"valid": True, "message": "Key verified"}
    raise HTTPException(status_code=403, detail="Invalid API key")


@app.post("/extract", response_model=ExtractResponse)
async def extract_from_upload(files: List[UploadFile] = File(...)):
    """
    Upload one or more CELCAT timetable PDFs and receive structured
    extraction results as JSON.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")

    tmp_dir = tempfile.mkdtemp(prefix="celcat_")
    try:
        results: list[dict] = []
        for upload in files:
            if not upload.filename:
                continue

            # Save uploaded file to temp directory
            dest = Path(tmp_dir) / upload.filename
            with open(dest, "wb") as f:
                content = await upload.read()
                f.write(content)

            # Run extraction
            try:
                result = extract_timetable(str(dest))
                results.append(result)
            except Exception as e:
                raise HTTPException(
                    status_code=422,
                    detail=f"Failed to extract '{upload.filename}': {e}",
                )

        return _build_extract_response(results)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@app.post("/extract/batch", response_model=ExtractResponse)
async def extract_from_disk(
    request: BatchExtractRequest,
    _: str = Depends(require_admin_key),
):
    """
    Extract timetables from PDF files already present on disk.
    Provide the directory path containing the PDFs.

    Admin only: the caller names a directory on the server and learns whether
    it exists and what parses out of it, which is not something a public
    deployment should answer for arbitrary paths.
    """
    pdf_dir = Path(request.pdf_dir)
    if not pdf_dir.exists():
        raise HTTPException(
            status_code=404, detail=f"Directory not found: {request.pdf_dir}"
        )
    if not pdf_dir.is_dir():
        raise HTTPException(
            status_code=400, detail=f"Path is not a directory: {request.pdf_dir}"
        )

    pdf_files = sorted(pdf_dir.glob("*.pdf"))
    if not pdf_files:
        raise HTTPException(
            status_code=404,
            detail=f"No PDF files found in: {request.pdf_dir}",
        )

    results: list[dict] = []
    for pdf_path in pdf_files:
        try:
            result = extract_timetable(str(pdf_path))
            results.append(result)
        except Exception as e:
            raise HTTPException(
                status_code=422,
                detail=f"Failed to extract '{pdf_path.name}': {e}",
            )

    return _build_extract_response(results)


@app.get("/download", include_in_schema=False)
async def download_page(request: Request):
    """Serve the download page."""
    return templates.TemplateResponse(
        request=request,
        name="download.html",
        context={"active": "download", "version": "1.0.0", "request": request},
    )


@app.get("/evaluate", include_in_schema=False)
async def evaluate_page(request: Request):
    """Serve the evaluate page."""
    return templates.TemplateResponse(
        request=request,
        name="evaluate.html",
        context={"active": "evaluate", "version": "1.0.0", "request": request},
    )


@app.get("/extract", include_in_schema=False)
async def extract_page(request: Request):
    """Serve the extraction page."""
    return templates.TemplateResponse(
        request=request,
        name="extract.html",
        context={"active": "extract", "version": "1.0.0", "request": request},
    )


@app.get("/batch", include_in_schema=False)
async def batch_page(request: Request):
    """Serve the batch extraction page."""
    return templates.TemplateResponse(
        request=request,
        name="batch.html",
        context={"active": "batch", "version": "1.0.0", "request": request},
    )


@app.get("/calendar", include_in_schema=False)
async def calendar_page(request: Request):
    """Serve the calendar page."""
    return templates.TemplateResponse(
        request=request,
        name="calendar.html",
        context={"active": "calendar", "version": "1.0.0", "request": request},
    )


@app.post("/download", response_model=DownloadResponse)
async def download_timetables_endpoint(
    request: DownloadRequest,
    _: str = Depends(require_admin_key),
):
    """
    Download timetable PDFs from UWI's CELCAT server.
    Supports filtering by faculty, department, or course codes.

    Admin only: this makes the server fetch up to 1,600 files from UWI and
    write them to disk, which is not a thing a stranger should be able to
    trigger.
    """
    from timetable_extractor import download_timetables

    try:
        summary = download_timetables(
            faculty=request.faculty,
            dept=request.dept,
            codes=request.codes,
            res_type=request.res_type,
            all_resources=request.all_resources,
            limit=request.limit,
            dry_run=request.dry_run,
        )
        return DownloadResponse(**summary)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/evaluate", response_model=EvaluateResponse)
async def evaluate_headers_endpoint(
    request: EvaluateRequest,
    _: str = Depends(require_admin_key),
):
    """
    Evaluate time-header consistency across all PDFs in a directory.
    Reports discrepancies, missing headers, and read errors.

    Admin only: like batch extraction, it reads a caller-supplied path on the
    server.
    """
    from timetable_extractor import evaluate_headers

    try:
        result = evaluate_headers(request.pdf_dir, tolerance=request.tolerance)
        return EvaluateResponse(**result)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- Calibration Endpoints ---

@app.post("/admin/calibrate", response_model=CalibrateResponse)
async def admin_calibrate(
    request: CalibrateRequest,
    file: UploadFile = File(...),
    _: str = Depends(require_admin_key),
):
    """
    Upload a course timetable PDF and run LLM calibration.
    Generates a course-specific extraction config.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file uploaded")

    tmp_dir = tempfile.mkdtemp(prefix="calibrate_")
    try:
        dest = Path(tmp_dir) / (file.filename or "timetable.pdf")
        with open(dest, "wb") as f:
            content = await file.read()
            f.write(content)

        from timetable_extractor.calibration.orchestrator import CalibrationOrchestrator
        from timetable_extractor.calibration.providers.nemotron import NemotronProvider

        provider = NemotronProvider()
        orchestrator = CalibrationOrchestrator(provider=provider)

        try:
            result = await orchestrator.calibrate(str(dest), request.course_code)
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Calibration failed: {e}",
            )

        return CalibrateResponse(
            session_id=result["session_id"],
            course_code=result["course_code"],
            config_id=result["config_id"],
            confidence=result["confidence"],
            entries_count=result["entries_count"],
            report=result["report"],
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@app.get("/admin/sessions", response_model=SessionListResponse)
async def admin_list_sessions(
    course_code: str | None = None,
    limit: int = 20,
    _: str = Depends(require_admin_key),
):
    """List calibration sessions, optionally filtered by course code."""
    from timetable_extractor.calibration.orchestrator import CalibrationOrchestrator
    from timetable_extractor.calibration.providers.nemotron import NemotronProvider

    provider = NemotronProvider()
    orchestrator = CalibrationOrchestrator(provider=provider)

    sessions = await orchestrator.list_sessions(course_code=course_code, limit=limit)

    summaries = [
        SessionSummary(
            session_id=str(s.get("_id", "")),
            course_code=s.get("course_code", ""),
            status=s.get("status", ""),
            confidence=s.get("confidence"),
            config_id=s.get("config_id"),
            created_at=str(s.get("created_at", "")),
        )
        for s in sessions
    ]

    return SessionListResponse(sessions=summaries, total=len(summaries))


@app.get("/admin/sessions/{session_id}")
async def admin_get_session(
    session_id: str,
    _: str = Depends(require_admin_key),
):
    """Get details of a specific calibration session."""
    from timetable_extractor.calibration.orchestrator import CalibrationOrchestrator
    from timetable_extractor.calibration.providers.nemotron import NemotronProvider

    provider = NemotronProvider()
    orchestrator = CalibrationOrchestrator(provider=provider)

    session = await orchestrator.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return session


@app.get("/admin/configs", response_model=ConfigListResponse)
async def admin_list_configs(
    course_code: str | None = None,
    status: str | None = None,
    _: str = Depends(require_admin_key),
):
    """List course configs, optionally filtered by course code or status."""
    import asyncio

    from timetable_extractor.config.loader import list_configs

    loop = asyncio.get_event_loop()
    configs = await loop.run_in_executor(None, list_configs, status, course_code)

    summaries = []
    for c in configs:
        config_data = c.get("config", {})
        summaries.append(
            ConfigSummary(
                config_id=str(c.get("_id", "")),
                course_code=c.get("course_code", ""),
                status=c.get("status", ""),
                generated_by=c.get("generated_by", ""),
                version=c.get("version", 1),
                confidence=config_data.get("confidence", 0.0),
                created_at=str(c.get("created_at", "")),
            )
        )

    return ConfigListResponse(configs=summaries, total=len(summaries))


@app.post("/admin/configs/{config_id}/activate", response_model=ActivateConfigResponse)
async def admin_activate_config(
    config_id: str,
    _: str = Depends(require_admin_key),
):
    """Activate a draft course config."""
    import asyncio

    from bson import ObjectId

    from timetable_extractor.config.db import get_collection
    from timetable_extractor.config.loader import activate_config

    # Look up config to get course_code before activation
    doc = get_collection("course_configs").find_one({"_id": ObjectId(config_id)})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Config {config_id} not found")

    course_code = doc.get("course_code", "")

    loop = asyncio.get_event_loop()
    try:
        success = await loop.run_in_executor(None, activate_config, config_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not success:
        raise HTTPException(status_code=500, detail=f"Failed to activate config {config_id}")

    return ActivateConfigResponse(
        config_id=config_id,
        course_code=course_code,
        status="active",
        message=f"Config {config_id} activated for course {course_code}",
    )
