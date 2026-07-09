# Graph Report - DocExtract  (2026-07-08)

## Corpus Check
- 19 files · ~356,806 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 165 nodes · 276 edges · 10 communities detected
- Extraction: 65% EXTRACTED · 35% INFERRED · 0% AMBIGUOUS · INFERRED: 97 edges (avg confidence: 0.61)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 6|Community 6]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 14|Community 14]]

## God Nodes (most connected - your core abstractions)
1. `BBox` - 19 edges
2. `DocElement` - 19 edges
3. `ElementType` - 18 edges
4. `get_settings()` - 13 edges
5. `DoclingService` - 13 edges
6. `ClassificationResult` - 12 edges
7. `DoclingSuryaOCRPipeline` - 12 edges
8. `ParseResult` - 10 edges
9. `PageInfo` - 9 edges
10. `LLMService` - 9 edges

## Surprising Connections (you probably didn't know these)
- `get_settings()` --calls--> `startup()`  [INFERRED]
  backend/app/config.py → backend/app/main.py
- `get_settings()` --calls--> `upload_file()`  [INFERRED]
  backend/app/config.py → backend/app/main.py
- `get_settings()` --calls--> `process_document()`  [INFERRED]
  backend/app/config.py → backend/app/main.py
- `get_settings()` --calls--> `get_page_image()`  [INFERRED]
  backend/app/config.py → backend/app/main.py
- `get_settings()` --calls--> `classify_node()`  [INFERRED]
  backend/app/config.py → backend/app/nodes/classify.py

## Communities

### Community 0 - "Community 0"
Cohesion: 0.14
Nodes (25): DoclingService, get_docling_service(), _map_docling_type(), _PyMuPDFFallbackDoc, Docling document parsing service with SuryaOCR integration.  Provides a singleto, Extract all text elements with bounding boxes from a parsed document.          W, Walk a Docling DoclingDocument and extract elements with provenance., Convert parsed document to markdown.          Uses Docling's built-in export for (+17 more)

### Community 1 - "Community 1"
Cohesion: 0.12
Nodes (17): classify_node(), Classify node — uses VLM to identify document type., Classify the document type using the VLM.      Sends the first page image to the, extract_node(), Extract node — enhances parsed elements with VLM field labeling., Enhance extracted elements with VLM-powered field labeling.      Takes the raw e, get_llm_service(), LLMService (+9 more)

### Community 2 - "Community 2"
Cohesion: 0.15
Nodes (10): DoclingSuryaOCRPipeline, Document processing pipeline using Docling + Surya OCR., Converts and exports to a layout-preserved Markdown text., Converts and exports to JSON with bounding box coordinates for text, images, and, Runs the docling conversion using Surya OCR and returns the conversion result., Converts and exports to markdown. Returns markdown representation., test_layout_reconstruction_mock(), test_pipeline_conversion_integration() (+2 more)

### Community 3 - "Community 3"
Cohesion: 0.17
Nodes (13): BaseSettings, _find_env_file(), get_settings(), Application configuration via environment variables., Resolve relative paths against PROJECT_ROOT, leave absolute paths as-is., Use .env.local for local dev, fall back to .env., All settings are loaded from environment variables or .env file., Convert relative paths to absolute using project root. (+5 more)

### Community 4 - "Community 4"
Cohesion: 0.17
Nodes (15): get_page_image(), get_results(), health(), process_document(), FastAPI application for the DocExtract document processing pipeline.  Provides e, Process an uploaded document via the LangGraph pipeline.      Returns an SSE str, Serve a rendered page image PNG., Retrieve cached processing results for a job. (+7 more)

### Community 5 - "Community 5"
Cohesion: 0.19
Nodes (14): BaseModel, Enum, ingest_node(), Ingest node — validates file and renders pages to PNG images., Handle image file as a single page — copy and record dimensions., Validate the uploaded file and render each page to a PNG image.      Reads the f, Render a single PDF page to PNG and return PageInfo dict., _render_image_page() (+6 more)

### Community 6 - "Community 6"
Cohesion: 0.17
Nodes (14): _build_image_viewer(), main(), process_document(), DocExtract — Streamlit Frontend  Interactive document viewer with split-pane lay, Upload file to backend and return job info., Consume SSE stream from backend and update session state., Render the split-pane document viewer with click-to-highlight., Build HTML/JS for the image viewer with canvas highlight overlay. (+6 more)

### Community 7 - "Community 7"
Cohesion: 0.22
Nodes (8): _build_pipeline(), PipelineState, LangGraph pipeline definition for the document extraction workflow.  Defines a 5, State that flows through the pipeline graph., Build and compile the LangGraph pipeline., Run the document extraction pipeline with streaming progress.      Yields SSE-co, run_pipeline(), TypedDict

### Community 8 - "Community 8"
Cohesion: 0.5
Nodes (3): format_node(), Format node — builds final markdown + element-to-bbox mapping., Build the final output with markdown and element-bbox mapping.      Takes the pa

### Community 14 - "Community 14"
Cohesion: 1.0
Nodes (1): Converts and exports to JSON with bounding box coordinates for text, images, and

## Knowledge Gaps
- **40 isolated node(s):** `Application configuration via environment variables.`, `Resolve relative paths against PROJECT_ROOT, leave absolute paths as-is.`, `Use .env.local for local dev, fall back to .env.`, `All settings are loaded from environment variables or .env file.`, `Convert relative paths to absolute using project root.` (+35 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Community 14`** (1 nodes): `Converts and exports to JSON with bounding box coordinates for text, images, and`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `ElementType` connect `Community 0` to `Community 3`, `Community 5`?**
  _High betweenness centrality (0.168) - this node is a cross-community bridge._
- **Why does `get_settings()` connect `Community 3` to `Community 1`, `Community 4`, `Community 5`?**
  _High betweenness centrality (0.139) - this node is a cross-community bridge._
- **Why does `ClassificationResult` connect `Community 1` to `Community 5`?**
  _High betweenness centrality (0.139) - this node is a cross-community bridge._
- **Are the 16 inferred relationships involving `BBox` (e.g. with `DoclingService` and `_PyMuPDFFallbackDoc`) actually correct?**
  _`BBox` has 16 INFERRED edges - model-reasoned connections that need verification._
- **Are the 16 inferred relationships involving `DocElement` (e.g. with `DoclingService` and `_PyMuPDFFallbackDoc`) actually correct?**
  _`DocElement` has 16 INFERRED edges - model-reasoned connections that need verification._
- **Are the 14 inferred relationships involving `ElementType` (e.g. with `DoclingService` and `_PyMuPDFFallbackDoc`) actually correct?**
  _`ElementType` has 14 INFERRED edges - model-reasoned connections that need verification._
- **Are the 8 inferred relationships involving `get_settings()` (e.g. with `startup()` and `upload_file()`) actually correct?**
  _`get_settings()` has 8 INFERRED edges - model-reasoned connections that need verification._