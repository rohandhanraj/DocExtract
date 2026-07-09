"""Pipeline state definition shared across all subgraphs.

The PipelineState TypedDict flows through the parent graph and all three
subgraphs (Ingest, Analysis, Extraction).  List fields that accumulate
across pages use ``Annotated[list, operator.add]`` so each node can
return a partial list and LangGraph merges them automatically.

``thread_id`` is the universal primary key — used by the LangGraph
checkpointer (AsyncPostgresSaver) and referenced in the ``user_docs``
Postgres table.
"""

from __future__ import annotations

import operator
from typing import Any, Annotated

from typing_extensions import TypedDict


class PipelineState(TypedDict, total=False):
    """State that flows through the entire pipeline graph."""

    # ── Input (set at invocation) ─────────────────────────────────────
    user_data: dict[str, Any]            # Row from ``users`` table
    raw_file_metadata: dict[str, Any]    # {filename, raw_s3_key, …}
    thread_id: str                       # PRIMARY KEY everywhere
    bucket_name: str

    # ── Ingest SubGraph outputs ───────────────────────────────────────
    local_file_paths: list[str]                                            # Decrypted local paths
    high_res_image_refs: Annotated[list[dict[str, Any]], operator.add]     # S3 refs per page
    high_res_base64_refs: Annotated[list[dict[str, Any]], operator.add]    # S3 refs per page
    markdown_text_refs: Annotated[list[dict[str, Any]], operator.add]      # S3 refs per page
    json_extracted_refs: Annotated[list[dict[str, Any]], operator.add]     # S3 refs per page
    pages: Annotated[list[dict[str, Any]], operator.add]                   # PageInfo dicts

    # ── Analysis SubGraph outputs ─────────────────────────────────────
    markdown_texts: list[str]            # Fetched markdown content
    classification_label: str            # e.g. "business_license"
    classification_confidence: float
    should_proceed: bool                 # Whether to proceed to extraction

    # ── Extraction SubGraph outputs ───────────────────────────────────
    extraction_page_numbers: list[int]   # Hardcoded per doc type
    extraction_template: dict[str, Any]  # Prompt template from DB
    extraction_schema: dict[str, Any]    # JSON schema from DB
    raw_extracted_fields: dict[str, Any] # Raw VLM output
    verified_fields: dict[str, Any]      # Good fields after validation

    # ── Control ───────────────────────────────────────────────────────
    status: str
    error: str
    messages: Annotated[list[str], operator.add]
    current_subgraph: str
