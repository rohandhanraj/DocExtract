# DocExtract Pipeline — Task Tracker

## Batch 1: Foundation (state, data layer, docker)
- [x] 1. `backend/app/state.py` — PipelineState TypedDict
- [x] 2. `backend/app/data/__init__.py` — Package init
- [x] 3. `backend/app/data/sql_db.py` — Postgres CRUD
- [ ] 4. `backend/app/data/s3_store.py` — MinIO S3 CRUD
- [ ] 5. `backend/app/data/mlflow_tracker.py` — MLflow tracing module
- [x] 6. `backend/app/services/crypto_service.py` — AES-256-GCM
- [ ] 7. `docker-compose.yml` — Add MLflow service

## Batch 2: SubGraph Nodes
- [ ] 8. `backend/app/nodes/ingest_subgraph.py` — Ingest subgraph
- [ ] 9. `backend/app/nodes/analysis_subgraph.py` — Analysis subgraph
- [ ] 10. `backend/app/nodes/extraction_subgraph.py` — Extraction subgraph

## Batch 3: Wiring & Config
- [ ] 11. `backend/app/new_graph.py` — Parent graph + run_pipeline
- [ ] 12. `backend/app/config.py` — Add new settings
- [ ] 13. `backend/app/main.py` — New API endpoints
- [ ] 14. `backend/requirements.txt` + `.env.local` — Dependencies + env
