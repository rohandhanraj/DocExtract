"""Ingest node — validates file and renders pages to PNG images."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import fitz  # PyMuPDF

from app.config import get_settings
from app.models import PageInfo

logger = logging.getLogger(__name__)


def ingest_node(state: dict) -> dict:
    """Validate the uploaded file and render each page to a PNG image.

    Reads the file from state["file_path"], renders pages at the
    configured DPI using PyMuPDF, and stores page metadata.

    Updates state with:
        pages: list of PageInfo dicts
        status: "ingested"
        messages: progress log
    """
    settings = get_settings()
    file_path = state["file_path"]
    job_id = state.get("job_id", "unknown")

    logger.info("Ingesting %s (job %s)", file_path, job_id)

    # Validate file exists
    if not Path(file_path).exists():
        return {
            "error": f"File not found: {file_path}",
            "status": "error",
            "messages": [f"❌ File not found: {file_path}"],
        }

    # Validate extension
    ext = Path(file_path).suffix.lower()
    if ext not in settings.allowed_extensions:
        return {
            "error": f"Unsupported file type: {ext}",
            "status": "error",
            "messages": [f"❌ Unsupported file type: {ext}"],
        }

    # Create output directory for page images
    pages_dir = os.path.join(settings.upload_dir, job_id, "pages")
    os.makedirs(pages_dir, exist_ok=True)

    pages: list[dict] = []

    try:
        # Handle image files — wrap in a single-page PDF for consistent processing
        if ext in [".png", ".jpg", ".jpeg", ".tiff", ".tif"]:
            pages.append(
                _render_image_page(file_path, pages_dir, job_id, page_num=0)
            )
        else:
            # PDF or DOCX — render with PyMuPDF
            doc = fitz.open(file_path)
            for page_num in range(len(doc)):
                page = doc[page_num]
                page_info = _render_pdf_page(page, page_num, pages_dir, job_id, settings.page_dpi)
                pages.append(page_info)
            doc.close()

    except Exception as e:
        logger.error("Ingestion failed for %s: %s", file_path, e)
        return {
            "error": f"Ingestion failed: {e}",
            "status": "error",
            "messages": [f"❌ Ingestion failed: {e}"],
        }

    logger.info("Ingested %d pages from %s", len(pages), file_path)
    return {
        "pages": pages,
        "status": "ingested",
        "messages": [f"✅ Ingested {len(pages)} page(s)"],
    }


def _render_pdf_page(page, page_num: int, pages_dir: str, job_id: str, dpi: int) -> dict:
    """Render a single PDF page to PNG and return PageInfo dict."""
    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    pixmap = page.get_pixmap(matrix=matrix)

    image_filename = f"page_{page_num}.png"
    image_path = os.path.join(pages_dir, image_filename)
    pixmap.save(image_path)

    return PageInfo(
        page_num=page_num,
        width=float(page.rect.width),
        height=float(page.rect.height),
        image_url=f"/api/page-image/{job_id}/{page_num}",
    ).model_dump()


def _render_image_page(file_path: str, pages_dir: str, job_id: str, page_num: int) -> dict:
    """Handle image file as a single page — copy and record dimensions."""
    from PIL import Image
    import shutil

    image_filename = f"page_{page_num}.png"
    image_dest = os.path.join(pages_dir, image_filename)

    # Convert to PNG if needed
    img = Image.open(file_path)
    width, height = img.size
    img.save(image_dest, "PNG")
    img.close()

    return PageInfo(
        page_num=page_num,
        width=float(width),
        height=float(height),
        image_url=f"/api/page-image/{job_id}/{page_num}",
    ).model_dump()
