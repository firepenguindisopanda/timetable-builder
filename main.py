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
from typing import List

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from schemas import (
    BatchExtractRequest,
    DownloadRequest,
    DownloadResponse,
    EvaluateRequest,
    EvaluateResponse,
    ExtractResponse,
    HealthResponse,
    TimetableResult,
)
from timetable_extractor import extract_timetable

app = FastAPI(
    title="CELCAT Timetable Extraction API",
    description=(
        "Extract structured class data (day, times, course, staff, room) "
        "from CELCAT-generated timetable PDFs."
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

templates = Jinja2Templates(directory=Path(__file__).resolve().parent / "templates")

# Serve static files from assets folder
assets_dir = Path(__file__).resolve().parent / "assets"
if assets_dir.exists():
    app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")


def _build_extract_response(results: list[dict]) -> ExtractResponse:
    """Convert raw extraction dicts into a typed ExtractResponse."""
    typed_results = [TimetableResult(**r) for r in results]
    total_entries = sum(len(r.entries) for r in typed_results)
    return ExtractResponse(
        results=typed_results,
        total_files=len(typed_results),
        total_entries=total_entries,
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
async def extract_from_disk(request: BatchExtractRequest):
    """
    Extract timetables from PDF files already present on disk.
    Provide the directory path containing the PDFs.
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
async def download_timetables_endpoint(request: DownloadRequest):
    """
    Download timetable PDFs from UWI's CELCAT server.
    Supports filtering by faculty, department, or course codes.
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
async def evaluate_headers_endpoint(request: EvaluateRequest):
    """
    Evaluate time-header consistency across all PDFs in a directory.
    Reports discrepancies, missing headers, and read errors.
    """
    from timetable_extractor import evaluate_headers

    try:
        result = evaluate_headers(request.pdf_dir, tolerance=request.tolerance)
        return EvaluateResponse(**result)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
