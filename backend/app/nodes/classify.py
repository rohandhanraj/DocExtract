"""Classify node — uses VLM to identify document type."""

from __future__ import annotations

import asyncio
import logging
import os

from app.config import get_settings
from app.services.llm_service import get_llm_service

logger = logging.getLogger(__name__)


def classify_node(state: dict) -> dict:
    """Classify the document type using the VLM.

    Sends the first page image to the vision model and receives
    a classification result (doc_type + confidence).

    Falls back to {"doc_type": "unknown", "confidence": 0.0} if
    the VLM is unavailable or classification fails.
    """
    pages = state.get("pages", [])
    job_id = state.get("job_id", "unknown")
    settings = get_settings()

    if not pages:
        logger.warning("No pages available for classification (job %s)", job_id)
        return {
            "classification": {"doc_type": "unknown", "confidence": 0.0},
            "status": "classified",
            "messages": ["⚠️ No pages available — skipping classification"],
        }

    # Use the first page image for classification
    first_page = pages[0]
    page_image_path = os.path.join(
        settings.upload_dir, job_id, "pages", f"page_{first_page['page_num']}.png"
    )

    if not os.path.exists(page_image_path):
        logger.warning("First page image not found: %s", page_image_path)
        return {
            "classification": {"doc_type": "unknown", "confidence": 0.0},
            "status": "classified",
            "messages": ["⚠️ Page image not found — skipping classification"],
        }

    # Run async classification in sync context (LangGraph nodes are sync)
    llm_service = get_llm_service()
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                result = pool.submit(
                    asyncio.run, llm_service.classify_document(page_image_path)
                ).result()
        else:
            result = asyncio.run(llm_service.classify_document(page_image_path))
    except Exception as e:
        logger.warning("Classification error: %s", e)
        result = None

    if result is None:
        classification = {"doc_type": "unknown", "confidence": 0.0}
        msg = "⚠️ Classification failed — proceeding as unknown"
    else:
        classification = result.model_dump()
        msg = f"📋 Classified as: {result.doc_type} ({result.confidence:.0%})"

    logger.info("Classification result for job %s: %s", job_id, classification)
    return {
        "classification": classification,
        "status": "classified",
        "messages": [msg],
    }
