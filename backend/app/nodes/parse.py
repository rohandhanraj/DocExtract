"""Parse node — runs Docling + SuryaOCR with PyMuPDF4LLM fallback."""

from __future__ import annotations

import logging

from app.services.docling_service import get_docling_service

logger = logging.getLogger(__name__)


def parse_node(state: dict) -> dict:
    """Parse the document using Docling + SuryaOCR.

    Extracts all text elements with bounding boxes and generates
    a markdown representation of the document.

    Falls back to PyMuPDF4LLM if Docling fails.

    Updates state with:
        elements: list of DocElement dicts
        raw_markdown: markdown string
        docling_doc: the parsed document object (not serialized)
        status: "parsed"
    """
    file_path = state["file_path"]
    job_id = state.get("job_id", "unknown")

    logger.info("Parsing %s (job %s)", file_path, job_id)

    docling = get_docling_service()

    try:
        # Parse with Docling (falls back to PyMuPDF4LLM internally)
        doc = docling.parse(file_path)

        # Extract elements with bounding boxes
        elements = docling.extract_elements(doc)
        elements_dicts = [el.model_dump() for el in elements]

        # Generate markdown
        markdown = docling.to_markdown(doc)

        parser_used = "PyMuPDF4LLM" if hasattr(doc, "file_path") and hasattr(doc, "markdown") else "Docling+SuryaOCR"

        logger.info(
            "Parsed %s: %d elements, %d chars markdown (engine: %s)",
            file_path, len(elements), len(markdown), parser_used,
        )

        return {
            "elements": elements_dicts,
            "raw_markdown": markdown,
            "parser_used": parser_used,
            "status": "parsed",
            "messages": [f"🔍 Parsed with {parser_used}: {len(elements)} elements extracted"],
        }

    except Exception as e:
        logger.error("All parsing failed for %s: %s", file_path, e)
        return {
            "elements": [],
            "raw_markdown": "",
            "parser_used": "none",
            "status": "error",
            "error": f"Parsing failed: {e}",
            "messages": [f"❌ Parsing failed: {e}"],
        }
