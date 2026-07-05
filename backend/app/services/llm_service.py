"""Vision LLM service for document classification and field extraction.

Uses init_chat_model from LangChain to initialize a VLM via an
OpenAI-compatible endpoint. Falls back gracefully when the VLM
endpoint is unreachable.
"""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage

from app.config import get_settings
from app.models import ClassificationResult

logger = logging.getLogger(__name__)

# Document types the classifier can identify
DOCUMENT_TYPES = [
    "business_license",
    "bank_statement",
    "tax_document",
    "permit",
    "invoice",
    "contract",
    "receipt",
    "form",
    "other",
]

CLASSIFICATION_PROMPT = """You are a document classification expert. Analyze this document image and classify it into exactly ONE of these categories:

{doc_types}

Respond ONLY with valid JSON in this exact format (no markdown, no code blocks):
{{"doc_type": "<category>", "confidence": <0.0-1.0>}}"""

EXTRACTION_PROMPT = """You are a document data extraction expert. This is a {doc_type} document.

Extract all key fields and their values from this document. For each field, provide:
- field_name: a short label (e.g., "Business Name", "License Number", "Total Amount")
- value: the extracted text value

The raw OCR text from the document is:
---
{raw_text}
---

Respond ONLY with valid JSON array (no markdown, no code blocks):
[{{"field_name": "...", "value": "..."}}, ...]"""


class LLMService:
    """Manages VLM interactions for classification and extraction."""

    def __init__(self) -> None:
        self._model = None
        self._available = False
        self._initialize()

    def _initialize(self) -> None:
        """Initialize the VLM via init_chat_model with OpenAI-compatible endpoint."""
        settings = get_settings()
        try:
            self._model = init_chat_model(
                model=settings.vlm_model,
                model_provider="openai",
                base_url=settings.vlm_base_url,
                api_key=settings.vlm_api_key,
                temperature=0.1,
                max_tokens=1024,
            )
            self._available = True
            logger.info("VLM initialized: %s at %s", settings.vlm_model, settings.vlm_base_url)
        except Exception as e:
            logger.warning("VLM initialization failed, running without LLM: %s", e)
            self._available = False

    @property
    def is_available(self) -> bool:
        return self._available

    def _encode_image(self, image_path: str) -> str:
        """Read image file and return base64-encoded string."""
        return base64.b64encode(Path(image_path).read_bytes()).decode("utf-8")

    async def classify_document(self, page_image_path: str) -> ClassificationResult:
        """Classify a document by sending its first page image to the VLM.

        Returns ClassificationResult with doc_type and confidence.
        Falls back to {"doc_type": "unknown", "confidence": 0.0} on failure.
        """
        if not self._available:
            logger.info("VLM unavailable — skipping classification")
            return ClassificationResult(doc_type="unknown", confidence=0.0)

        try:
            image_b64 = self._encode_image(page_image_path)
            prompt = CLASSIFICATION_PROMPT.format(doc_types="\n".join(f"- {dt}" for dt in DOCUMENT_TYPES))

            message = HumanMessage(
                content=[
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{image_b64}"},
                    },
                ]
            )

            response = await self._model.ainvoke([message])
            result = json.loads(response.content.strip())
            return ClassificationResult(
                doc_type=result.get("doc_type", "unknown"),
                confidence=min(max(result.get("confidence", 0.0), 0.0), 1.0),
            )
        except Exception as e:
            logger.warning("Classification failed, falling back: %s", e)
            return ClassificationResult(doc_type="unknown", confidence=0.0)

    async def extract_fields(
        self, page_image_path: str, doc_type: str, raw_text: str
    ) -> list[dict]:
        """Use VLM to extract labeled fields from a document page.

        Returns list of {"field_name": "...", "value": "..."} dicts.
        Returns empty list on failure (caller uses raw Docling elements).
        """
        if not self._available:
            return []

        try:
            image_b64 = self._encode_image(page_image_path)
            prompt = EXTRACTION_PROMPT.format(
                doc_type=doc_type.replace("_", " "),
                raw_text=raw_text[:3000],  # Truncate to avoid context overflow
            )

            message = HumanMessage(
                content=[
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{image_b64}"},
                    },
                ]
            )

            response = await self._model.ainvoke([message])
            fields = json.loads(response.content.strip())
            if isinstance(fields, list):
                return fields
            return []
        except Exception as e:
            logger.warning("Field extraction failed, falling back to Docling: %s", e)
            return []


# Module-level singleton
_llm_service: LLMService | None = None


def get_llm_service() -> LLMService:
    """Get or create the LLM service singleton."""
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMService()
    return _llm_service
