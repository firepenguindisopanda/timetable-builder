# CELCAT Timetable Extraction

This FastAPI server exposes the timetable extraction, download, and evaluation workflows as HTTP endpoints.

## Running the Application

You can start the server using Uvicorn directly:
```bash
uvicorn main:app --reload --port 8000
```

Or, if you are managing the project with `uv`:
```bash
uv run uvicorn main:app --reload --port 8000
```

## Interactive API Docs

Once running, view the interactive documentation at:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
