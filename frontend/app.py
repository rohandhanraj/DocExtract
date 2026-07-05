"""DocExtract — Streamlit Frontend

Interactive document viewer with split-pane layout:
  Left:  Document page image with bounding-box highlight overlay
  Right: Extracted markdown with clickable elements

Clicking any text element in the right pane highlights the
corresponding source region on the document image.
"""

from __future__ import annotations

import json
import os
import time

import httpx
import streamlit as st

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
st.set_page_config(
    page_title="DocExtract — Document Intelligence",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ---------------------------------------------------------------------------
# Custom CSS
# ---------------------------------------------------------------------------
st.markdown("""
<style>
    /* Global dark theme overrides */
    .stApp {
        background: linear-gradient(135deg, #0f0f1a 0%, #1a1a2e 50%, #16213e 100%);
    }
    
    /* Header styling */
    .main-header {
        background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-size: 2.4rem;
        font-weight: 800;
        letter-spacing: -0.5px;
        margin-bottom: 0;
        font-family: 'Inter', sans-serif;
    }
    .sub-header {
        color: #8892b0;
        font-size: 1rem;
        margin-top: -8px;
        margin-bottom: 24px;
    }
    
    /* Upload area */
    .upload-zone {
        border: 2px dashed rgba(102, 126, 234, 0.4);
        border-radius: 16px;
        padding: 40px;
        text-align: center;
        background: rgba(102, 126, 234, 0.05);
        transition: all 0.3s ease;
    }
    .upload-zone:hover {
        border-color: rgba(102, 126, 234, 0.8);
        background: rgba(102, 126, 234, 0.1);
    }
    
    /* Classification badge */
    .doc-badge {
        display: inline-block;
        padding: 6px 16px;
        border-radius: 20px;
        background: linear-gradient(135deg, #667eea, #764ba2);
        color: white;
        font-weight: 600;
        font-size: 0.85rem;
        letter-spacing: 0.5px;
        margin: 4px 0;
    }
    .confidence-bar {
        height: 4px;
        border-radius: 2px;
        background: rgba(255,255,255,0.1);
        margin-top: 6px;
        overflow: hidden;
    }
    .confidence-fill {
        height: 100%;
        border-radius: 2px;
        background: linear-gradient(90deg, #667eea, #764ba2);
        transition: width 0.8s ease;
    }
    
    /* Progress styling */
    .progress-step {
        padding: 8px 16px;
        margin: 4px 0;
        border-radius: 8px;
        background: rgba(255,255,255,0.03);
        border-left: 3px solid rgba(102, 126, 234, 0.5);
        font-size: 0.9rem;
        color: #ccd6f6;
    }
    .progress-step.active {
        border-left-color: #667eea;
        background: rgba(102, 126, 234, 0.08);
    }
    .progress-step.done {
        border-left-color: #64ffda;
        color: #64ffda;
    }
    
    /* Stats cards */
    .stat-card {
        background: rgba(255,255,255,0.05);
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 12px;
        padding: 16px;
        text-align: center;
    }
    .stat-value {
        font-size: 1.8rem;
        font-weight: 700;
        background: linear-gradient(135deg, #667eea, #64ffda);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }
    .stat-label {
        font-size: 0.75rem;
        color: #8892b0;
        text-transform: uppercase;
        letter-spacing: 1px;
        margin-top: 4px;
    }
    
    /* Hide default streamlit elements */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    .stDeployButton {display: none;}
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Session state initialization
# ---------------------------------------------------------------------------
def init_session():
    defaults = {
        "job_id": None,
        "result": None,
        "processing": False,
        "current_page": 0,
        "highlight_bbox": None,
        "highlight_page": None,
        "progress_messages": [],
        "uploaded_filename": None,
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


init_session()


# ---------------------------------------------------------------------------
# Backend communication
# ---------------------------------------------------------------------------
def upload_file(file_bytes: bytes, filename: str) -> dict | None:
    """Upload file to backend and return job info."""
    try:
        resp = httpx.post(
            f"{BACKEND_URL}/api/upload",
            files={"file": (filename, file_bytes)},
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        st.error(f"Upload failed: {e}")
        return None


def process_document(job_id: str):
    """Consume SSE stream from backend and update session state."""
    messages = []
    result = None

    try:
        with httpx.stream(
            "GET",
            f"{BACKEND_URL}/api/process/{job_id}",
            timeout=httpx.Timeout(300.0, connect=10.0),
        ) as response:
            buffer = ""
            current_event = "message"

            for line in response.iter_lines():
                if line.startswith("event:"):
                    current_event = line[6:].strip()
                elif line.startswith("data:"):
                    data_str = line[5:].strip()
                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    if current_event == "progress":
                        msg = data.get("message", "")
                        messages.append(msg)

                    elif current_event == "classification":
                        messages.append(
                            f"📋 Classified as: {data.get('doc_type', 'unknown')} "
                            f"({data.get('confidence', 0):.0%})"
                        )

                    elif current_event == "result":
                        result = data

                    elif current_event == "error":
                        messages.append(f"❌ {data.get('message', 'Unknown error')}")

                elif line == "":
                    current_event = "message"

    except Exception as e:
        messages.append(f"❌ Connection error: {e}")

    return messages, result


# ---------------------------------------------------------------------------
# Interactive viewer component (HTML + JavaScript)
# ---------------------------------------------------------------------------
def render_viewer(result: dict):
    """Render the split-pane document viewer with click-to-highlight."""

    pages = result.get("pages", [])
    elements = result.get("elements", [])
    markdown = result.get("markdown", "")
    classification = result.get("classification", {})

    if not pages:
        st.warning("No pages were rendered from this document.")
        return

    # --- Stats bar ---
    col_s1, col_s2, col_s3, col_s4 = st.columns(4)
    with col_s1:
        st.markdown(f'<div class="stat-card"><div class="stat-value">{len(pages)}</div><div class="stat-label">Pages</div></div>', unsafe_allow_html=True)
    with col_s2:
        st.markdown(f'<div class="stat-card"><div class="stat-value">{len(elements)}</div><div class="stat-label">Elements</div></div>', unsafe_allow_html=True)
    with col_s3:
        table_cells = sum(1 for e in elements if e.get("element_type") == "table_cell")
        st.markdown(f'<div class="stat-card"><div class="stat-value">{table_cells}</div><div class="stat-label">Table Cells</div></div>', unsafe_allow_html=True)
    with col_s4:
        doc_type = classification.get("doc_type", "unknown").replace("_", " ").title()
        conf = classification.get("confidence", 0)
        st.markdown(f'<div class="stat-card"><div class="doc-badge">{doc_type}</div><div class="confidence-bar"><div class="confidence-fill" style="width:{conf*100}%"></div></div></div>', unsafe_allow_html=True)

    st.markdown("---")

    # --- Split pane: Image viewer | Markdown output ---
    col_img, col_md = st.columns([1, 1], gap="large")

    with col_img:
        st.markdown("### 📷 Document Viewer")

        # Page navigation
        if len(pages) > 1:
            page_idx = st.selectbox(
                "Page",
                range(len(pages)),
                format_func=lambda x: f"Page {x + 1} of {len(pages)}",
                key="page_selector",
                index=st.session_state.current_page,
            )
            st.session_state.current_page = page_idx
        else:
            page_idx = 0

        page_info = pages[page_idx]
        image_url = f"{BACKEND_URL}{page_info['image_url']}"

        # Get bbox for current highlight
        h_bbox = st.session_state.highlight_bbox
        h_page = st.session_state.highlight_page

        # Build the interactive image viewer with canvas overlay
        viewer_html = _build_image_viewer(
            image_url=image_url,
            page_width=page_info.get("width", 612),
            page_height=page_info.get("height", 792),
            highlight_bbox=h_bbox if h_page == page_idx else None,
        )
        st.components.v1.html(viewer_html, height=700, scrolling=True)

    with col_md:
        st.markdown("### 📝 Extracted Content")
        st.caption("Click any element below to highlight its source location on the document")

        # Render interactive element list
        _render_interactive_elements(elements, pages)

        # Also show raw markdown in an expander
        with st.expander("📄 Full Markdown Output", expanded=False):
            st.markdown(markdown)


def _build_image_viewer(
    image_url: str,
    page_width: float,
    page_height: float,
    highlight_bbox: dict | None,
) -> str:
    """Build HTML/JS for the image viewer with canvas highlight overlay."""

    highlight_js = ""
    if highlight_bbox:
        # Normalize bbox coordinates to percentage for responsive overlay
        l_pct = (highlight_bbox["l"] / page_width) * 100
        t_pct = (highlight_bbox["t"] / page_height) * 100
        w_pct = ((highlight_bbox["r"] - highlight_bbox["l"]) / page_width) * 100
        h_pct = ((highlight_bbox["b"] - highlight_bbox["t"]) / page_height) * 100
        highlight_js = f"""
        const overlay = document.getElementById('highlight-overlay');
        overlay.style.left = '{l_pct}%';
        overlay.style.top = '{t_pct}%';
        overlay.style.width = '{w_pct}%';
        overlay.style.height = '{h_pct}%';
        overlay.style.display = 'block';
        overlay.classList.add('pulse');
        """

    return f"""
    <div style="position: relative; width: 100%; background: #0d1117; border-radius: 12px;
                border: 1px solid rgba(255,255,255,0.08); overflow: hidden;">
        <img id="doc-image" src="{image_url}" 
             style="width: 100%; display: block; border-radius: 12px;"
             onerror="this.src='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%22400%22 height=%22300%22><text x=%2250%25%22 y=%2250%25%22 dominant-baseline=%22middle%22 text-anchor=%22middle%22 fill=%22%23666%22 font-size=%2218%22>Image loading...</text></svg>'" />
        
        <div id="highlight-overlay" style="
            position: absolute;
            display: none;
            background: rgba(255, 214, 0, 0.3);
            border: 2px solid rgba(255, 214, 0, 0.8);
            border-radius: 4px;
            pointer-events: none;
            z-index: 10;
            transition: all 0.3s ease;
            box-shadow: 0 0 20px rgba(255, 214, 0, 0.4);
        "></div>
    </div>
    
    <style>
        @keyframes highlightPulse {{
            0% {{ box-shadow: 0 0 5px rgba(255, 214, 0, 0.4); }}
            50% {{ box-shadow: 0 0 25px rgba(255, 214, 0, 0.7); }}
            100% {{ box-shadow: 0 0 5px rgba(255, 214, 0, 0.4); }}
        }}
        .pulse {{
            animation: highlightPulse 1.5s ease-in-out infinite;
        }}
    </style>
    
    <script>
        {highlight_js}
    </script>
    """


def _render_interactive_elements(elements: list[dict], pages: list[dict]):
    """Render each extracted element as a clickable item."""

    if not elements:
        st.info("No elements extracted from this document.")
        return

    # Group by element type for organized display
    headings = [e for e in elements if e.get("element_type") == "heading"]
    paragraphs = [e for e in elements if e.get("element_type") == "paragraph"]
    table_cells = [e for e in elements if e.get("element_type") == "table_cell"]
    others = [
        e for e in elements
        if e.get("element_type") not in ("heading", "paragraph", "table_cell")
    ]

    # Render headings
    if headings:
        st.markdown("#### 📌 Headings")
        for el in headings:
            _render_element_button(el)

    # Render paragraphs
    if paragraphs:
        st.markdown("#### 📝 Text Blocks")
        for el in paragraphs:
            _render_element_button(el)

    # Render table data
    if table_cells:
        st.markdown("#### 📊 Table Data")
        for el in table_cells:
            label = el.get("label", "")
            prefix = f"**{label}:** " if label else ""
            _render_element_button(el, prefix=prefix)

    # Render other elements
    if others:
        st.markdown("#### 📎 Other Elements")
        for el in others:
            _render_element_button(el)


def _render_element_button(el: dict, prefix: str = ""):
    """Render a single element as a clickable button with bbox info."""
    el_id = el.get("id", "")
    text = el.get("text", "")[:120]  # Truncate long text
    bbox = el.get("bbox", {})
    page = bbox.get("page", 0)
    label = el.get("label", "")
    el_type = el.get("element_type", "unknown")

    # Display label if available
    display = f"{prefix}{text}" if not label or prefix else f"{prefix}{text}"
    if not display.strip():
        return

    # Create a unique key for each button
    btn_key = f"btn_{el_id}"

    # Show as a compact clickable element
    col_btn, col_info = st.columns([5, 1])
    with col_btn:
        if st.button(
            f"{'🏷️ ' if label else ''}{display}",
            key=btn_key,
            use_container_width=True,
        ):
            st.session_state.highlight_bbox = bbox
            st.session_state.highlight_page = page
            st.session_state.current_page = page
            st.rerun()

    with col_info:
        st.caption(f"p.{page + 1}")


# ---------------------------------------------------------------------------
# Main Application
# ---------------------------------------------------------------------------
def main():
    # Header
    st.markdown('<h1 class="main-header">📄 DocExtract</h1>', unsafe_allow_html=True)
    st.markdown('<p class="sub-header">Intelligent Document Extraction with Spatial Provenance</p>', unsafe_allow_html=True)

    # File upload
    uploaded_file = st.file_uploader(
        "Upload a document",
        type=["pdf", "png", "jpg", "jpeg", "tiff", "tif", "docx"],
        help="Supported: PDF, images (PNG/JPG/TIFF), DOCX",
        key="file_uploader",
    )

    if uploaded_file is not None:
        # Check if this is a new file
        if st.session_state.uploaded_filename != uploaded_file.name:
            st.session_state.uploaded_filename = uploaded_file.name
            st.session_state.result = None
            st.session_state.job_id = None
            st.session_state.highlight_bbox = None
            st.session_state.highlight_page = None
            st.session_state.current_page = 0

        # Upload and process if not already done
        if st.session_state.result is None and not st.session_state.processing:
            if st.button("🚀 Extract Document", type="primary", use_container_width=True):
                st.session_state.processing = True

                # Upload
                with st.spinner("Uploading document..."):
                    upload_result = upload_file(uploaded_file.read(), uploaded_file.name)

                if upload_result is None:
                    st.session_state.processing = False
                    return

                job_id = upload_result["job_id"]
                st.session_state.job_id = job_id

                # Process with progress display
                progress_container = st.container()
                with progress_container:
                    st.markdown("### ⚡ Processing Pipeline")
                    progress_bar = st.progress(0, text="Starting pipeline...")
                    status_area = st.empty()

                    messages, result = process_document(job_id)

                    # Show progress messages
                    for i, msg in enumerate(messages):
                        progress_bar.progress(
                            min((i + 1) / max(len(messages), 1), 1.0),
                            text=msg,
                        )
                        time.sleep(0.1)

                if result:
                    st.session_state.result = result
                    st.session_state.processing = False
                    st.rerun()
                else:
                    st.error("Processing failed. Check the messages above for details.")
                    for msg in messages:
                        st.markdown(f'<div class="progress-step">{msg}</div>', unsafe_allow_html=True)
                    st.session_state.processing = False

        # Show results if available
        if st.session_state.result is not None:
            render_viewer(st.session_state.result)

    else:
        # Show welcome state
        st.markdown("---")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.markdown("""
            #### 🔍 Smart Parsing
            Docling + SuryaOCR extract text, tables, 
            and structure with bounding boxes.
            """)
        with col2:
            st.markdown("""
            #### 📋 Auto Classification
            Vision LLM identifies document type
            for targeted extraction.
            """)
        with col3:
            st.markdown("""
            #### 🎯 Click to Locate
            Click any extracted field to highlight
            its source on the original document.
            """)


if __name__ == "__main__":
    main()
