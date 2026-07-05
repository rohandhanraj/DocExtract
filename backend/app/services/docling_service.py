"""Docling document parsing service with SuryaOCR integration.

Provides a singleton wrapper around Docling's DocumentConverter for
parsing documents with full bounding-box provenance. Falls back to
PyMuPDF4LLM when Docling parsing fails.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from app.models import BBox, DocElement, ElementType

logger = logging.getLogger(__name__)


def _map_docling_type(label: str) -> ElementType:
    """Map Docling's content type labels to our ElementType enum."""
    mapping = {
        "paragraph": ElementType.PARAGRAPH,
        "text": ElementType.PARAGRAPH,
        "heading": ElementType.HEADING,
        "section_header": ElementType.HEADING,
        "title": ElementType.HEADING,
        "table": ElementType.TABLE,
        "list_item": ElementType.LIST_ITEM,
        "caption": ElementType.CAPTION,
        "footnote": ElementType.FOOTER,
        "page_header": ElementType.HEADER,
        "page_footer": ElementType.FOOTER,
        "picture": ElementType.IMAGE,
        "figure": ElementType.IMAGE,
    }
    return mapping.get(label.lower(), ElementType.UNKNOWN)


class DoclingService:
    """Singleton service wrapping Docling's DocumentConverter.

    Initializes the converter once with SuryaOCR and reuses across requests.
    """

    def __init__(self) -> None:
        self._converter = None
        self._initialized = False

    def _ensure_initialized(self) -> None:
        """Lazy-initialize the Docling converter on first use."""
        if self._initialized:
            return

        try:
            from docling.document_converter import DocumentConverter

            # Initialize with default pipeline (includes SuryaOCR if installed)
            self._converter = DocumentConverter()
            self._initialized = True
            logger.info("Docling DocumentConverter initialized successfully")
        except Exception as e:
            logger.error("Failed to initialize Docling: %s", e)
            raise

    def parse(self, file_path: str):
        """Parse a document with Docling, returning a DoclingDocument.

        Args:
            file_path: Path to the document file.

        Returns:
            DoclingDocument object with full structural and spatial data.

        Raises:
            Exception if both Docling and fallback fail.
        """
        self._ensure_initialized()

        try:
            result = self._converter.convert(file_path)
            logger.info("Docling parsed %s successfully", file_path)
            return result.document
        except Exception as e:
            logger.warning("Docling failed on %s: %s — trying PyMuPDF4LLM fallback", file_path, e)
            return self._fallback_parse(file_path)

    def _fallback_parse(self, file_path: str):
        """Fallback parsing using PyMuPDF4LLM.

        Returns a lightweight wrapper that provides markdown and basic
        element extraction via PyMuPDF's get_text("dict").
        """
        try:
            import pymupdf4llm
            md_text = pymupdf4llm.to_markdown(file_path)
            logger.info("PyMuPDF4LLM fallback succeeded for %s", file_path)
            return _PyMuPDFFallbackDoc(file_path, md_text)
        except Exception as e:
            logger.error("Both Docling and PyMuPDF4LLM failed for %s: %s", file_path, e)
            raise RuntimeError(f"All parsing engines failed for {file_path}") from e

    def extract_elements(self, doc) -> list[DocElement]:
        """Extract all text elements with bounding boxes from a parsed document.

        Works with both Docling DoclingDocument and our fallback wrapper.
        """
        if isinstance(doc, _PyMuPDFFallbackDoc):
            return doc.extract_elements()

        return self._extract_docling_elements(doc)

    def _extract_docling_elements(self, doc) -> list[DocElement]:
        """Walk a Docling DoclingDocument and extract elements with provenance."""
        elements: list[DocElement] = []

        try:
            # Iterate through all content items in the document
            for item, _level in doc.iterate_items():
                text = ""
                bbox = None
                elem_type = ElementType.UNKNOWN

                # Get text content
                if hasattr(item, "text"):
                    text = item.text or ""

                # Get element type from label
                if hasattr(item, "label"):
                    elem_type = _map_docling_type(str(item.label))

                # Get bounding box from provenance
                if hasattr(item, "prov") and item.prov:
                    for prov in item.prov:
                        if hasattr(prov, "bbox") and prov.bbox is not None:
                            b = prov.bbox
                            page_no = prov.page_no if hasattr(prov, "page_no") else 0
                            # Docling bbox: l, t, r, b
                            bbox = BBox(
                                l=float(b.l),
                                t=float(b.t),
                                r=float(b.r),
                                b=float(b.b),
                                page=int(page_no) - 1,  # Convert to 0-indexed
                            )
                            break

                if text.strip() and bbox is not None:
                    elements.append(
                        DocElement(
                            id=f"el-{uuid.uuid4().hex[:8]}",
                            text=text.strip(),
                            bbox=bbox,
                            element_type=elem_type,
                        )
                    )

            # Handle table cells separately
            if hasattr(doc, "tables"):
                for table in doc.tables:
                    if hasattr(table, "table_cells"):
                        for cell in table.table_cells:
                            cell_text = cell.text if hasattr(cell, "text") else ""
                            if not cell_text.strip():
                                continue
                            cell_bbox = None
                            if hasattr(cell, "prov") and cell.prov:
                                for prov in cell.prov:
                                    if hasattr(prov, "bbox") and prov.bbox:
                                        b = prov.bbox
                                        page_no = prov.page_no if hasattr(prov, "page_no") else 0
                                        cell_bbox = BBox(
                                            l=float(b.l),
                                            t=float(b.t),
                                            r=float(b.r),
                                            b=float(b.b),
                                            page=int(page_no) - 1,
                                        )
                                        break
                            if cell_bbox:
                                elements.append(
                                    DocElement(
                                        id=f"el-{uuid.uuid4().hex[:8]}",
                                        text=cell_text.strip(),
                                        bbox=cell_bbox,
                                        element_type=ElementType.TABLE_CELL,
                                    )
                                )

        except Exception as e:
            logger.warning("Error extracting Docling elements: %s", e)

        logger.info("Extracted %d elements with bounding boxes", len(elements))
        return elements

    def to_markdown(self, doc) -> str:
        """Convert parsed document to markdown.

        Uses Docling's built-in export for DoclingDocument, or the
        cached markdown from the fallback wrapper.
        """
        if isinstance(doc, _PyMuPDFFallbackDoc):
            return doc.markdown

        try:
            return doc.export_to_markdown()
        except Exception as e:
            logger.warning("Markdown export failed: %s", e)
            return ""


class _PyMuPDFFallbackDoc:
    """Lightweight wrapper for PyMuPDF fallback parsing results.

    Provides the same interface as DoclingDocument for downstream consumers.
    """

    def __init__(self, file_path: str, markdown: str) -> None:
        self.file_path = file_path
        self.markdown = markdown

    def extract_elements(self) -> list[DocElement]:
        """Extract text elements with bboxes using PyMuPDF's dict output."""
        import fitz

        elements: list[DocElement] = []
        try:
            pdf = fitz.open(self.file_path)
            for page_num, page in enumerate(pdf):
                blocks = page.get_text("dict")["blocks"]
                for block in blocks:
                    if block.get("type") != 0:  # Skip image blocks
                        continue
                    for line in block.get("lines", []):
                        for span in line.get("spans", []):
                            text = span.get("text", "").strip()
                            if not text:
                                continue
                            sbbox = span.get("bbox", [0, 0, 0, 0])
                            elements.append(
                                DocElement(
                                    id=f"el-{uuid.uuid4().hex[:8]}",
                                    text=text,
                                    bbox=BBox(
                                        l=sbbox[0],
                                        t=sbbox[1],
                                        r=sbbox[2],
                                        b=sbbox[3],
                                        page=page_num,
                                    ),
                                    element_type=ElementType.PARAGRAPH,
                                )
                            )
            pdf.close()
        except Exception as e:
            logger.warning("PyMuPDF element extraction failed: %s", e)

        return elements


# Module-level singleton
_docling_service: DoclingService | None = None


def get_docling_service() -> DoclingService:
    """Get or create the Docling service singleton."""
    global _docling_service
    if _docling_service is None:
        _docling_service = DoclingService()
    return _docling_service
