"""FastAPI application for the DocExtract document processing pipeline.

Provides endpoints for file upload, SSE-streamed processing, page image
serving, and cached result retrieval.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sse_starlette.sse import EventSourceResponse

from app.config import get_settings
from app.graph import run_pipeline
from app.models import ParseResult

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="DocExtract API",
    description="Document extraction pipeline with bounding-box provenance",
    version="1.0.0",
)

# CORS — allow Streamlit frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory result cache {job_id: ParseResult dict}
_results_cache: dict[str, dict] = {}


@app.on_event("startup")
async def startup() -> None:
    """Initialize services and create directories on startup."""
    settings = get_settings()
    os.makedirs(settings.upload_dir, exist_ok=True)
    logger.info("DocExtract API started — upload_dir=%s", settings.upload_dir)


@app.get("/health")
async def health() -> dict:
    """Health check endpoint for Docker."""
    return {"status": "healthy", "service": "docextract-backend"}


@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)) -> dict:
    """Upload a document file for processing.

    Returns a job_id that can be used to start processing
    and retrieve results.
    """
    settings = get_settings()

    # Validate file extension
    ext = Path(file.filename or "").suffix.lower()
    if ext not in settings.allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {ext}. Allowed: {settings.allowed_extensions}",
        )

    # Generate job ID and save file
    job_id = uuid.uuid4().hex[:12]
    job_dir = os.path.join(settings.upload_dir, job_id)
    os.makedirs(job_dir, exist_ok=True)

    file_path = os.path.join(job_dir, file.filename)

    # Read and validate file size
    contents = await file.read()
    size_mb = len(contents) / (1024 * 1024)
    if size_mb > settings.max_file_size_mb:
        raise HTTPException(
            status_code=400,
            detail=f"File too large: {size_mb:.1f}MB (max: {settings.max_file_size_mb}MB)",
        )

    with open(file_path, "wb") as f:
        f.write(contents)

    logger.info("Uploaded %s (%.1fMB) → job %s", file.filename, size_mb, job_id)

    return {
        "job_id": job_id,
        "filename": file.filename,
        "size_mb": round(size_mb, 2),
    }


@app.get("/api/process/{job_id}")
async def process_document(job_id: str) -> EventSourceResponse:
    """Process an uploaded document via the LangGraph pipeline.

    Returns an SSE stream with progress events and the final result.

    Event types:
        - progress: {node, label, message, step, total, status}
        - classification: {doc_type, confidence}
        - page_ready: {page_num, width, height, image_url}
        - result: {job_id, filename, markdown, elements, pages, classification, status}
        - error: {message}
    """
    settings = get_settings()
    job_dir = os.path.join(settings.upload_dir, job_id)

    if not os.path.exists(job_dir):
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    # Find the uploaded file
    files = [f for f in os.listdir(job_dir) if os.path.isfile(os.path.join(job_dir, f))]
    if not files:
        raise HTTPException(status_code=404, detail=f"No file found for job {job_id}")

    file_path = os.path.join(job_dir, files[0])
    filename = files[0]

    async def event_generator():
        """Generate SSE events from the pipeline."""
        async for event in run_pipeline(file_path, filename, job_id):
            event_type = event.get("event", "progress")
            event_data = event.get("data", {})

            # Cache the final result
            if event_type == "result":
                _results_cache[job_id] = event_data

            yield {
                "event": event_type,
                "data": json.dumps(event_data),
            }

    return EventSourceResponse(event_generator())


@app.get("/api/page-image/{job_id}/{page_num}")
async def get_page_image(job_id: str, page_num: int) -> FileResponse:
    """Serve a rendered page image PNG."""
    settings = get_settings()
    image_path = os.path.join(
        settings.upload_dir, job_id, "pages", f"page_{page_num}.png"
    )

    if not os.path.exists(image_path):
        raise HTTPException(
            status_code=404,
            detail=f"Page image not found: job={job_id}, page={page_num}",
        )

    return FileResponse(
        image_path,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@app.get("/api/results/{job_id}")
async def get_results(job_id: str) -> dict:
    """Retrieve cached processing results for a job."""
    if job_id in _results_cache:
        return _results_cache[job_id]

    raise HTTPException(
        status_code=404,
        detail=f"Results not found for job {job_id}. Process the document first via /api/process/{job_id}",
    )
