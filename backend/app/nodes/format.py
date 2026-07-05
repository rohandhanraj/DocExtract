"""Format node — builds final markdown + element-to-bbox mapping."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def format_node(state: dict) -> dict:
    """Build the final output with markdown and element-bbox mapping.

    Takes the parsed markdown and enriched elements, ensures all
    elements have stable IDs, and produces the final ParseResult.

    Updates state with:
        markdown: final markdown string
        elements: finalized element list
        status: "complete"
    """
    raw_markdown = state.get("raw_markdown", "")
    elements = state.get("elements", [])
    classification = state.get("classification", {})
    parser_used = state.get("parser_used", "unknown")
    job_id = state.get("job_id", "unknown")

    # Ensure all elements have unique IDs
    seen_ids = set()
    for i, el in enumerate(elements):
        if not el.get("id") or el["id"] in seen_ids:
            el["id"] = f"el-{i:04d}"
        seen_ids.add(el["id"])

    # Build a summary header for the markdown
    doc_type = classification.get("doc_type", "unknown")
    confidence = classification.get("confidence", 0.0)

    header_lines = []
    if doc_type != "unknown":
        header_lines.append(f"> **Document Type:** {doc_type.replace('_', ' ').title()} ({confidence:.0%} confidence)")
        header_lines.append("")

    final_markdown = "\n".join(header_lines) + raw_markdown if header_lines else raw_markdown

    # Stats
    element_count = len(elements)
    table_cells = sum(1 for el in elements if el.get("element_type") == "table_cell")
    labeled = sum(1 for el in elements if el.get("label"))

    summary = (
        f"✅ Complete: {element_count} elements"
        f" ({table_cells} table cells, {labeled} labeled fields)"
        f" | Parser: {parser_used}"
    )

    logger.info("Format node for job %s: %s", job_id, summary)

    return {
        "markdown": final_markdown,
        "elements": elements,
        "status": "complete",
        "messages": [summary],
    }
