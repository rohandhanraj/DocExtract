"""Extract node — enhances parsed elements with VLM field labeling."""

from __future__ import annotations

import asyncio
import logging
import os

from app.config import get_settings
from app.services.llm_service import get_llm_service

logger = logging.getLogger(__name__)


def extract_node(state: dict) -> dict:
    """Enhance extracted elements with VLM-powered field labeling.

    Takes the raw elements from Docling parsing and enriches them
    with semantic field labels (e.g., "Business Name", "License Number")
    using the VLM. Falls back to raw Docling elements when VLM is unavailable.

    Updates state with:
        elements: list of enriched DocElement dicts
        status: "extracted"
    """
    elements = state.get("elements", [])
    classification = state.get("classification", {})
    pages = state.get("pages", [])
    job_id = state.get("job_id", "unknown")
    settings = get_settings()

    doc_type = classification.get("doc_type", "unknown")

    if not elements:
        return {
            "status": "extracted",
            "messages": ["⚠️ No elements to extract fields from"],
        }

    # Attempt VLM-enhanced field extraction
    llm_service = get_llm_service()
    if not llm_service.is_available:
        logger.info("VLM unavailable — using raw Docling elements for job %s", job_id)
        return {
            "elements": elements,
            "status": "extracted",
            "messages": ["📝 Using structural extraction (VLM unavailable)"],
        }

    # Group elements by page for per-page VLM extraction
    pages_elements: dict[int, list[dict]] = {}
    for el in elements:
        page = el.get("bbox", {}).get("page", 0)
        pages_elements.setdefault(page, []).append(el)

    enriched_count = 0

    for page_num, page_elements in pages_elements.items():
        page_image_path = os.path.join(
            settings.upload_dir, job_id, "pages", f"page_{page_num}.png"
        )
        if not os.path.exists(page_image_path):
            continue

        # Build raw text from page elements
        raw_text = "\n".join(el.get("text", "") for el in page_elements)

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    fields = pool.submit(
                        asyncio.run,
                        llm_service.extract_fields(page_image_path, doc_type, raw_text),
                    ).result()
            else:
                fields = asyncio.run(
                    llm_service.extract_fields(page_image_path, doc_type, raw_text)
                )
        except Exception as e:
            logger.warning("VLM extraction failed for page %d: %s", page_num, e)
            fields = []

        if not fields:
            continue

        # Match VLM field labels to Docling elements by text similarity
        for field in fields:
            field_value = field.get("value", "").strip().lower()
            field_name = field.get("field_name", "")
            if not field_value:
                continue

            best_match = None
            best_score = 0.0

            for el in page_elements:
                el_text = el.get("text", "").strip().lower()
                if not el_text:
                    continue
                # Simple containment matching
                if field_value in el_text or el_text in field_value:
                    score = len(field_value) / max(len(el_text), 1)
                    if score > best_score:
                        best_score = score
                        best_match = el

            if best_match and best_score > 0.3:
                best_match["label"] = field_name
                enriched_count += 1

    msg = f"🏷️ Enriched {enriched_count} fields with VLM labels" if enriched_count > 0 else "📝 VLM labeling found no matches"
    logger.info("Extract node for job %s: %s", job_id, msg)

    return {
        "elements": elements,  # Modified in-place with labels
        "status": "extracted",
        "messages": [msg],
    }
