# DocExtract 3-SubGraph Pipeline — Implementation Plan v4

> **For Antigravity:** REQUIRED SUB-SKILL: Load executing-plans to implement this plan task-by-task.

**Goal:** Refactor flat 5-node pipeline into 3 composable subgraphs with PostgresSaver checkpointing, MinIO storage, AES-256-GCM decryption, MLflow per-node tracing, and interrupt/resume at subgraph boundaries.

**Architecture:** Parent `StateGraph` → 3 compiled subgraphs → `AsyncPostgresSaver` checkpointer → MinIO artifacts → MLflow tracing. `thread_id` is the universal primary key.

**Tech Stack:** LangGraph, `langgraph-checkpoint-postgres`, asyncpg, boto3, pycryptodome, mlflow, FastAPI SSE

---

## Infrastructure

| Service | Host | Port | Status |
|---------|------|------|--------|
| PostgreSQL | localhost | 5432 | ✅ Running |
| MinIO | localhost | 9000/9001 | ✅ Running |
| VLM (Jan.ai) | localhost | 1337 | ✅ Running |
| MLflow | localhost | 5001 | 🆕 To start |

MLflow server backed by Postgres (same instance, separate DB `mlflow`):
```bash
mlflow server --host 0.0.0.0 --port 5001 \
  --backend-store-uri postgresql://postgres:08d148...@localhost:5432/mlflow \
  --default-artifact-root s3://mlflow-artifacts
```

---

## MLflow Observability Module

### [NEW] `backend/app/data/mlflow_tracker.py`

Dedicated module for all MLflow tracing operations — imported by node functions wherever LLM calls, OCR processing, or S3 I/O occur.

**Initialization** (called once at startup):
```python
import mlflow
from mlflow.entities import SpanType

def init_mlflow(tracking_uri: str, experiment_name: str = "DocExtract"):
    mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_experiment(experiment_name)
    mlflow.langchain.autolog()  # Auto-traces all LangChain VLM calls
```

**Per-node tracing decorator** (wraps node functions):
```python
def trace_node(node_name: str, subgraph: str):
    """Decorator to trace a LangGraph node with custom attributes."""
    def decorator(func):
        @mlflow.trace(name=node_name, span_type=SpanType.CHAIN)
        def wrapper(state: dict) -> dict:
            span = mlflow.get_current_active_span()
            span.set_attributes({
                "subgraph": subgraph,
                "thread_id": state.get("thread_id", ""),
                "node": node_name,
            })
            start = time.time()
            result = func(state)
            latency = time.time() - start
            span.set_attributes({"latency_seconds": latency})
            return result
        return wrapper
    return decorator
```

**LLM call tracker** (wraps VLM invocations for token usage):
```python
def trace_llm_call(model_name: str, call_type: str):
    """Context manager that logs LLM token usage, model name, latency."""
    def decorator(func):
        @mlflow.trace(name=f"llm_{call_type}", span_type=SpanType.LLM)
        async def wrapper(*args, **kwargs):
            span = mlflow.get_current_active_span()
            span.set_attributes({"model_name": model_name, "call_type": call_type})
            result = await func(*args, **kwargs)
            # Extract token usage from LangChain response metadata
            if hasattr(result, 'usage_metadata'):
                usage = result.usage_metadata
                span.set_attributes({
                    "prompt_tokens": usage.get("input_tokens", 0),
                    "completion_tokens": usage.get("output_tokens", 0),
                    "total_tokens": usage.get("total_tokens", 0),
                })
            return result
        return wrapper
    return decorator
```

**Metric logging helpers:**
```python
def log_node_metrics(node_name: str, metrics: dict):
    """Log custom metrics for a node (e.g., pages_processed, fields_extracted)."""
    with mlflow.start_span(name=f"{node_name}_metrics") as span:
        span.set_attributes(metrics)

def log_pipeline_summary(thread_id: str, summary: dict):
    """Log final pipeline summary as a run."""
    with mlflow.start_run(run_name=f"pipeline_{thread_id}", tags={"thread_id": thread_id}):
        for k, v in summary.items():
            if isinstance(v, (int, float)):
                mlflow.log_metric(k, v)
            else:
                mlflow.log_param(k, str(v))
```

### What gets traced per node:

| Node | Trace Type | Metrics Logged |
|------|-----------|----------------|
| `download_files` | CHAIN | files_count, total_bytes, latency |
| `decrypt_files` | CHAIN | files_decrypted, latency |
| `render_pages` | CHAIN | pages_rendered, total_pixels, latency |
| `ocr_parse` | CHAIN | pages_parsed, markdown_chars, json_elements, latency |
| `persist_ingest` | CHAIN | refs_stored, latency |
| `fetch_markdown` | CHAIN | pages_fetched, total_chars, latency |
| `classify_document` | LLM | model_name, prompt_tokens, completion_tokens, confidence, latency |
| `update_classification_db` | CHAIN | label, latency |
| `decide_proceed` | CHAIN | should_proceed, decision_reason, latency |
| `persist_analysis` | CHAIN | latency |
| `detect_pages` | CHAIN | pages_selected, latency |
| `select_template` | CHAIN | template_label, fields_count, latency |
| `batch_extract` | LLM | model_name, prompt_tokens, completion_tokens, pages_processed, fields_extracted, latency |
| `verify_fields` | CHAIN | total_fields, valid_fields, rejected_fields, latency |
| `persist_extraction` | CHAIN | fields_persisted, latency |

---

## Encryption: AES-256-GCM

File format: `[12-byte nonce][16-byte auth tag][...ciphertext...]`
Key: 32-byte hex-encoded in `users.decrypt_key`

---

## Database Schema

### `users`
```sql
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY, name TEXT, email TEXT,
    decrypt_key TEXT NOT NULL, created_at TIMESTAMPTZ DEFAULT now()
);
```

### `user_docs` (thread_id = PK)
```sql
CREATE TABLE IF NOT EXISTS user_docs (
    thread_id TEXT PRIMARY KEY, user_id TEXT REFERENCES users(user_id),
    filename TEXT, raw_s3_key TEXT, classification_label TEXT,
    classification_confidence REAL, extracted_fields JSONB,
    status TEXT DEFAULT 'pending', created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);
```

### `extraction_templates` (pre-seeded, 9 doc types, no region-specific refs)
```sql
CREATE TABLE IF NOT EXISTS extraction_templates (
    classification_label TEXT PRIMARY KEY, prompt_template TEXT NOT NULL,
    extraction_schema JSONB NOT NULL, created_at TIMESTAMPTZ DEFAULT now()
);
```

---

## MinIO Structure

```
docextract/{user_id}/raw/{filename}
docextract/{user_id}/{thread_id}/high_res_images/{stem}/{page}.jpeg
docextract/{user_id}/{thread_id}/high_res_base64/{stem}/{page}.txt
docextract/{user_id}/{thread_id}/markdown_text/{stem}/{page}.md
docextract/{user_id}/{thread_id}/json_extracted/{stem}/{page}.json
```

---

## SubGraph Summary

**SubGraph 1: Ingest** — `download → decrypt → render → ocr_parse → persist_ingest(interrupt)`
**SubGraph 2: Analysis** — `fetch_markdown → classify → update_db → decide → persist_analysis(interrupt)`
**SubGraph 3: Extraction** — `detect_pages → select_template → batch_extract → verify → persist_extraction(interrupt)`

Conditional edge after Analysis: `should_proceed=True → Extraction`, `False → END`

---

## File Creation Order

| # | File | Type | Purpose |
|---|------|------|---------|
| 1 | `backend/app/state.py` | NEW | PipelineState TypedDict |
| 2 | `backend/app/data/__init__.py` | NEW | Data layer package |
| 3 | `backend/app/data/sql_db.py` | NEW | Postgres CRUD |
| 4 | `backend/app/data/s3_store.py` | NEW | MinIO S3 CRUD |
| 5 | `backend/app/data/mlflow_tracker.py` | NEW | MLflow tracing module |
| 6 | `backend/app/services/crypto_service.py` | NEW | AES-256-GCM |
| 7 | `backend/app/nodes/ingest_subgraph.py` | NEW | 5 traced nodes + builder |
| 8 | `backend/app/nodes/analysis_subgraph.py` | NEW | 5 traced nodes + builder |
| 9 | `backend/app/nodes/extraction_subgraph.py` | NEW | 5 traced nodes + builder |
| 10 | `backend/app/new_graph.py` | OVERWRITE | Parent graph + run_pipeline |
| 11 | `backend/app/config.py` | MODIFY | Add postgres/s3/mlflow config |
| 12 | `backend/app/main.py` | MODIFY | New endpoints + mlflow init |
| 13 | `backend/requirements.txt` | MODIFY | Add deps |
| 14 | `.env.local` | MODIFY | Add connection strings |

---

## Config Additions

```python
# config.py additions
postgres_uri: str = "postgresql://postgres:08d148...@localhost:5432/postgres"
s3_endpoint: str = "http://localhost:9000"
s3_bucket: str = "docextract"
s3_access_key: str = "admin"
s3_secret_key: str = "3a6eb7..."
mlflow_tracking_uri: str = "http://localhost:5001"
mlflow_experiment: str = "DocExtract"
```

## Requirements Additions
```
langgraph-checkpoint-postgres
asyncpg
psycopg[binary,pool]
boto3
pycryptodome
mlflow>=2.15
```

---

## Verification Plan

```bash
# 1. Start MLflow server (if not running)
mlflow server --port 5001 \
  --backend-store-uri postgresql://postgres:...@localhost:5432/mlflow &

# 2. Import checks
cd backend && python -c "from app.data.mlflow_tracker import init_mlflow; print('OK')"
cd backend && python -c "from app.state import PipelineState; print('OK')"

# 3. DB + S3 setup
cd backend && python -c "
import asyncio; from app.data.sql_db import setup_tables
asyncio.run(setup_tables())
"

# 4. Graph compilation
cd backend && python -c "
import asyncio; from app.new_graph import create_pipeline; from app.config import get_settings
asyncio.run(create_pipeline(get_settings().postgres_uri))
print('Graph OK')
"

# 5. MLflow UI verify traces
# Open http://localhost:5001 → DocExtract experiment → verify spans appear

# 6. FastAPI startup
cd backend && timeout 10 uvicorn app.main:app --port 8099 2>&1 | head -20
```
