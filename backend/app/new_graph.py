# SubGraphs
"""
SubGraph 1: Ingest
- receives user_data and raw_file_metadata from user_jobs collection
- Downloads raw encrypted files from S3/Filesystem
- Decrypts files using user_data decrypt key
- convert pages to high resolution images and images to base64 encoded strings to use in frontend and other parts as we proceed. Finally push both images and base64 encoded images to S3 in same bucket but different folder(name: {job_id}/high_res_images/filename without extension/page_number.jpeg and {job_id}/high_res_images_base64/filename without extension/page_number.jpeg) and hold their reference in the state
- Parse + OCR using Docling-SuryaOCR over the high resolution images to get the complete text in each page as markdown file and text along with boundings and other information as json file and push them to S3 in same bucket but different folder(name: {job_id}/markdown_text/filename without extension/page_number.md and {job_id}/json_extracted/filename without extension/page_number.json) and hold their reference in the state
- persist state after Ingesting everything (pages, markdown_text and json_extracted references)
"""


"""
SubGraph 2: Analysis
- Fetch the markdown_text using the reference in state
- Classifies document type 
- Update Classification Label in state
- Update User data db with classified label(classification_label)
- Decides to proceed with extraction or not based on the classified label and update the state
- persist state after classification and proceed decision
"""

"""
SubGraph 3: Extraction
- Detect Pages and update state with list of page numbers to be extracted
- Based on the classified label (business_license, bank_statement, tax_document, permit, invoice, contract, receipt, form, other), select the appropriate extraction prompt template from templates table in DB and extraction schema
- Batch Extracts fields from the pages through a VLM using the json_extracted references and the high res base64 encoded images references in the prompt
- Verify the Extracted Fields based on the extraction schema and 
- Update state with Good Extracted Fields.
- persist state after extraction and update the User data db with the extracted fields
"""

# Nodes
"""
Node 1: Ingest subgraph
Node 2: Analysis subgraph
Node 3: Extraction subgraph
"""
"""LangGraph pipeline definition for the document extraction workflow.

Streams progress updates via SSE-compatible events.

The whole graph can be interrupted at end of any subgraph and while resuming the flow from any subgraph will expect the previous outcomes to be present in the state fields.

"""

from __future__ import annotations

import logging
from typing import Any, AsyncGenerator, TypedDict

from langgraph.graph import StateGraph, START, END

from app.nodes.ingest import ingest_node
from app.nodes.classify import classify_node
from app.nodes.parse import parse_node
from app.nodes.extract import extract_node
from app.nodes.format import format_node
from operator import add

logger = logging.getLogger(__name__)


class PipelineState(TypedDict, total=False):
    """State that flows through the pipeline graph."""
    # Input
    user_data: dict[str, Any]
    bucket_name: str
    raw_file_metadata: str
    job_id: str

    # Accumulated by nodes
    parsed_image: list[]
    parsed_text: list[str, add]
    pages: list[dict]
    classification: dict
    elements: list[dict]
    raw_markdown: str
    markdown: str
    parser_used: str

    # Control
    status: str
    error: str
    messages: list[str]


def _build_pipeline() -> Any:
    """Build and compile the LangGraph pipeline."""
    graph = (
        StateGraph(PipelineState)
        .add_node("ingest", ingest_node)
        .add_node("classify", classify_node)
        .add_node("parse", parse_node)
        .add_node("extract", extract_node)
        .add_node("format", format_node)
        .add_edge(START, "ingest")
        .add_edge("ingest", "classify")
        .add_edge("classify", "parse")
        .add_edge("parse", "extract")
        .add_edge("extract", "format")
        .add_edge("format", END)
    )
    return graph.compile()


# Compile the pipeline once at module level
pipeline = _build_pipeline()


# Node display names for progress reporting
NODE_LABELS = {
    "ingest": "📥 Ingesting document",
    "classify": "📋 Classifying document type",
    "parse": "🔍 Parsing with Docling + SuryaOCR",
    "extract": "🏷️ Extracting fields with VLM",
    "format": "📝 Formatting output",
}


async def run_pipeline(
    file_path: str, filename: str, job_id: str
) -> AsyncGenerator[dict, None]:
    """Run the document extraction pipeline with streaming progress.

    Yields SSE-compatible event dicts:
        {"event": "progress", "data": {"node": "...", "message": "...", "step": N, "total": 5}}
        {"event": "classification", "data": {"doc_type": "...", "confidence": 0.95}}
        {"event": "page_ready", "data": {"page_num": 0, "image_url": "..."}}
        {"event": "result", "data": {<ParseResult fields>}}
        {"event": "error", "data": {"message": "..."}}
    """
    initial_state: PipelineState = {
        "file_path": file_path,
        "filename": filename,
        "job_id": job_id,
        "pages": [],
        "classification": {},
        "elements": [],
        "raw_markdown": "",
        "markdown": "",
        "parser_used": "",
        "status": "pending",
        "error": "",
        "messages": [],
    }

    total_steps = 5
    step = 0

    # Accumulate state from stream updates
    accumulated: dict = {**initial_state}

    try:
        for chunk in pipeline.stream(initial_state, stream_mode="updates"):
            for node_name, update in chunk.items():
                step += 1
                node_label = NODE_LABELS.get(node_name, node_name)
                messages = update.get("messages", [])
                status = update.get("status", "")

                # Merge update into accumulated state
                for key, value in update.items():
                    if value is not None and value != "" and value != []:
                        accumulated[key] = value

                # Yield progress event
                yield {
                    "event": "progress",
                    "data": {
                        "node": node_name,
                        "label": node_label,
                        "message": messages[-1] if messages else node_label,
                        "step": step,
                        "total": total_steps,
                        "status": status,
                    },
                }

                # Check for errors
                if status == "error":
                    yield {
                        "event": "error",
                        "data": {"message": update.get("error", "Unknown error")},
                    }
                    return

                # Yield classification result when available
                if node_name == "classify" and "classification" in update:
                    yield {
                        "event": "classification",
                        "data": update["classification"],
                    }

                # Yield page ready events
                if node_name == "ingest" and "pages" in update:
                    for page in update["pages"]:
                        yield {
                            "event": "page_ready",
                            "data": page,
                        }

        # Yield final result from accumulated state (no second invocation)
        yield {
            "event": "result",
            "data": {
                "job_id": job_id,
                "filename": filename,
                "markdown": accumulated.get("markdown", ""),
                "elements": accumulated.get("elements", []),
                "pages": accumulated.get("pages", []),
                "classification": accumulated.get("classification", {}),
                "status": accumulated.get("status", "complete"),
            },
        }

    except Exception as e:
        logger.error("Pipeline error for job %s: %s", job_id, e, exc_info=True)
        yield {
            "event": "error",
            "data": {"message": str(e)},
        }
