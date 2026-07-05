"""Pydantic data models for the document extraction pipeline."""

from __future__ import annotations
from pydantic import BaseModel, Field
from enum import Enum


class ElementType(str, Enum):
    """Types of document elements extracted by the parser."""
    PARAGRAPH = "paragraph"
    HEADING = "heading"
    TABLE = "table"
    TABLE_CELL = "table_cell"
    LIST_ITEM = "list_item"
    CAPTION = "caption"
    FOOTER = "footer"
    HEADER = "header"
    IMAGE = "image"
    UNKNOWN = "unknown"


class BBox(BaseModel):
    """Bounding box coordinates for a document element.

    Uses the (l, t, r, b) convention — left, top, right, bottom —
    matching Docling's provenance format. All values in PDF points.
    """
    l: float = Field(description="Left x-coordinate")
    t: float = Field(description="Top y-coordinate")
    r: float = Field(description="Right x-coordinate")
    b: float = Field(description="Bottom y-coordinate")
    page: int = Field(description="0-indexed page number")


class DocElement(BaseModel):
    """A single extracted element with spatial metadata."""
    id: str = Field(description="Unique element identifier for frontend tracking")
    text: str = Field(description="Extracted text content")
    bbox: BBox = Field(description="Bounding box on the source page")
    element_type: ElementType = Field(default=ElementType.UNKNOWN)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    label: str = Field(default="", description="Field label from LLM extraction (e.g. 'Business Name')")


class PageInfo(BaseModel):
    """Rendered page image metadata."""
    page_num: int
    width: float
    height: float
    image_url: str = Field(description="URL path to the rendered page PNG")


class ClassificationResult(BaseModel):
    """Document classification output."""
    doc_type: str = Field(default="unknown")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class ParseResult(BaseModel):
    """Complete pipeline output returned to the frontend."""
    job_id: str
    filename: str
    markdown: str = ""
    elements: list[DocElement] = []
    pages: list[PageInfo] = []
    classification: ClassificationResult = Field(default_factory=ClassificationResult)
    status: str = "pending"
    error: str = ""


class StreamEvent(BaseModel):
    """Server-Sent Event payload."""
    event: str = Field(description="Event type: progress | classification | page_ready | result | error")
    data: dict = Field(default_factory=dict)
