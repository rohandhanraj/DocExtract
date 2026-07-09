"""PostgreSQL CRUD for users, user_docs, and extraction_templates.

Uses ``asyncpg`` for async operations.  All functions accept an optional
``pool`` parameter; when omitted they create a short-lived connection
from the configured URI (fine for setup scripts, but production code
should pass the shared pool from ``app.main``).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

import asyncpg

from app.config import get_settings

logger = logging.getLogger(__name__)

# ── Pool management ───────────────────────────────────────────────────

_pool: Optional[asyncpg.Pool] = None


async def get_pool() -> asyncpg.Pool:
    """Return (and lazily create) the module-level connection pool."""
    global _pool
    if _pool is None:
        settings = get_settings()
        _pool = await asyncpg.create_pool(settings.postgres_uri, min_size=2, max_size=10)
        logger.info("asyncpg pool created → %s", settings.postgres_uri.split("@")[-1])
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


# ── Table setup & seed ────────────────────────────────────────────────

async def setup_tables(pool: asyncpg.Pool | None = None) -> None:
    """Create tables if they don't exist and seed extraction templates."""
    p = pool or await get_pool()
    async with p.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id     TEXT PRIMARY KEY,
                name        TEXT NOT NULL,
                email       TEXT,
                decrypt_key TEXT NOT NULL,
                created_at  TIMESTAMPTZ DEFAULT now(),
                updated_at  TIMESTAMPTZ DEFAULT now()
            );
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_docs (
                thread_id                 TEXT PRIMARY KEY,
                user_id                   TEXT NOT NULL REFERENCES users(user_id),
                filename                  TEXT NOT NULL,
                raw_s3_key                TEXT,
                classification_label      TEXT,
                classification_confidence REAL,
                extracted_fields          JSONB,
                status                    TEXT DEFAULT 'pending',
                created_at                TIMESTAMPTZ DEFAULT now(),
                updated_at                TIMESTAMPTZ DEFAULT now()
            );
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS extraction_templates (
                classification_label TEXT PRIMARY KEY,
                prompt_template      TEXT NOT NULL,
                extraction_schema    JSONB NOT NULL,
                created_at           TIMESTAMPTZ DEFAULT now()
            );
        """)
        logger.info("Database tables created / verified")

        # Seed templates
        await _seed_extraction_templates(conn)


async def _seed_extraction_templates(conn: asyncpg.Connection) -> None:
    """Insert default extraction templates if table is empty."""
    count = await conn.fetchval("SELECT count(*) FROM extraction_templates")
    if count > 0:
        logger.info("Extraction templates already seeded (%d rows)", count)
        return

    for label, tmpl in _DEFAULT_TEMPLATES.items():
        await conn.execute(
            """INSERT INTO extraction_templates (classification_label, prompt_template, extraction_schema)
               VALUES ($1, $2, $3) ON CONFLICT DO NOTHING""",
            label,
            tmpl["prompt_template"],
            json.dumps(tmpl["extraction_schema"]),
        )
    logger.info("Seeded %d extraction templates", len(_DEFAULT_TEMPLATES))


# ── CRUD: users ───────────────────────────────────────────────────────

async def get_user(user_id: str, pool: asyncpg.Pool | None = None) -> dict | None:
    p = pool or await get_pool()
    row = await p.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
    return dict(row) if row else None


async def create_user(
    user_id: str, name: str, decrypt_key: str, email: str = "",
    pool: asyncpg.Pool | None = None,
) -> dict:
    p = pool or await get_pool()
    await p.execute(
        """INSERT INTO users (user_id, name, email, decrypt_key)
           VALUES ($1, $2, $3, $4) ON CONFLICT (user_id) DO NOTHING""",
        user_id, name, email, decrypt_key,
    )
    return {"user_id": user_id, "name": name, "email": email}


# ── CRUD: user_docs ───────────────────────────────────────────────────

async def create_user_doc(
    thread_id: str, user_id: str, filename: str, raw_s3_key: str = "",
    pool: asyncpg.Pool | None = None,
) -> dict:
    p = pool or await get_pool()
    await p.execute(
        """INSERT INTO user_docs (thread_id, user_id, filename, raw_s3_key, status)
           VALUES ($1, $2, $3, $4, 'pending')
           ON CONFLICT (thread_id) DO UPDATE SET status = 'pending', updated_at = now()""",
        thread_id, user_id, filename, raw_s3_key,
    )
    return {"thread_id": thread_id, "user_id": user_id, "filename": filename}


async def get_user_doc(thread_id: str, pool: asyncpg.Pool | None = None) -> dict | None:
    p = pool or await get_pool()
    row = await p.fetchrow("SELECT * FROM user_docs WHERE thread_id = $1", thread_id)
    return dict(row) if row else None


async def update_doc_classification(
    thread_id: str, label: str, confidence: float,
    pool: asyncpg.Pool | None = None,
) -> None:
    p = pool or await get_pool()
    await p.execute(
        """UPDATE user_docs
           SET classification_label = $2, classification_confidence = $3, updated_at = now()
           WHERE thread_id = $1""",
        thread_id, label, confidence,
    )


async def update_doc_extracted_fields(
    thread_id: str, fields: dict, pool: asyncpg.Pool | None = None,
) -> None:
    p = pool or await get_pool()
    await p.execute(
        """UPDATE user_docs
           SET extracted_fields = $2, status = 'extracted', updated_at = now()
           WHERE thread_id = $1""",
        thread_id, json.dumps(fields),
    )


async def update_doc_status(
    thread_id: str, status: str, pool: asyncpg.Pool | None = None,
) -> None:
    p = pool or await get_pool()
    await p.execute(
        "UPDATE user_docs SET status = $2, updated_at = now() WHERE thread_id = $1",
        thread_id, status,
    )


# ── CRUD: extraction_templates ────────────────────────────────────────

async def get_extraction_template(
    classification_label: str, pool: asyncpg.Pool | None = None,
) -> dict | None:
    p = pool or await get_pool()
    row = await p.fetchrow(
        "SELECT * FROM extraction_templates WHERE classification_label = $1",
        classification_label,
    )
    if row is None:
        return None
    result = dict(row)
    if isinstance(result.get("extraction_schema"), str):
        result["extraction_schema"] = json.loads(result["extraction_schema"])
    return result


# ── Default extraction templates ──────────────────────────────────────

_DEFAULT_TEMPLATES: dict[str, dict[str, Any]] = {
    "business_license": {
        "prompt_template": (
            "You are an expert document data extractor. This is a business license document.\n"
            "Extract all key fields listed in the schema below. For each field provide the value "
            "exactly as it appears in the document. If a field is not present, set its value to null.\n\n"
            "Schema fields: {schema_fields}\n\n"
            "Document text:\n---\n{document_text}\n---\n\n"
            "Respond ONLY with valid JSON matching the schema. No markdown, no explanation."
        ),
        "extraction_schema": {
            "type": "object",
            "properties": {
                "business_name": {"type": "string"},
                "license_number": {"type": "string"},
                "license_type": {"type": "string"},
                "issue_date": {"type": "string"},
                "expiry_date": {"type": "string"},
                "issuing_authority": {"type": "string"},
                "address": {"type": "string"},
                "status": {"type": "string"},
            },
            "required": ["business_name", "license_number"],
        },
    },
    "bank_statement": {
        "prompt_template": (
            "You are an expert document data extractor. This is a bank statement.\n"
            "Extract all key fields listed in the schema below.\n\n"
            "Schema fields: {schema_fields}\n\n"
            "Document text:\n---\n{document_text}\n---\n\n"
            "Respond ONLY with valid JSON matching the schema."
        ),
        "extraction_schema": {
            "type": "object",
            "properties": {
                "account_holder": {"type": "string"},
                "account_number": {"type": "string"},
                "routing_number": {"type": "string"},
                "bank_name": {"type": "string"},
                "statement_period_start": {"type": "string"},
                "statement_period_end": {"type": "string"},
                "opening_balance": {"type": "number"},
                "closing_balance": {"type": "number"},
                "total_deposits": {"type": "number"},
                "total_withdrawals": {"type": "number"},
            },
            "required": ["account_holder", "account_number", "bank_name"],
        },
    },
    "tax_document": {
        "prompt_template": (
            "You are an expert document data extractor. This is a tax document.\n"
            "Extract all key fields listed in the schema below.\n\n"
            "Schema fields: {schema_fields}\n\n"
            "Document text:\n---\n{document_text}\n---\n\n"
            "Respond ONLY with valid JSON matching the schema."
        ),
        "extraction_schema": {
            "type": "object",
            "properties": {
                "taxpayer_name": {"type": "string"},
                "tax_id": {"type": "string"},
                "tax_year": {"type": "string"},
                "filing_status": {"type": "string"},
                "total_income": {"type": "number"},
                "taxable_income": {"type": "number"},
                "total_tax": {"type": "number"},
                "refund_due": {"type": "number"},
                "form_type": {"type": "string"},
            },
            "required": ["taxpayer_name", "tax_id", "tax_year"],
        },
    },
    "permit": {
        "prompt_template": (
            "You are an expert document data extractor. This is a permit document.\n"
            "Extract all key fields listed in the schema below.\n\n"
            "Schema fields: {schema_fields}\n\n"
            "Document text:\n---\n{document_text}\n---\n\n"
            "Respond ONLY with valid JSON matching the schema."
        ),
        "extraction_schema": {
            "type": "object",
            "properties": {
                "permit_number": {"type": "string"},
                "permit_type": {"type": "string"},
                "holder_name": {"type": "string"},
                "issue_date": {"type": "string"},
                "expiry_date": {"type": "string"},
                "issuing_authority": {"type": "string"},
                "property_address": {"type": "string"},
                "conditions": {"type": "string"},
            },
            "required": ["permit_number", "holder_name"],
        },
    },
    "invoice": {
        "prompt_template": (
            "You are an expert document data extractor. This is an invoice.\n"
            "Extract all key fields listed in the schema below.\n\n"
            "Schema fields: {schema_fields}\n\n"
            "Document text:\n---\n{document_text}\n---\n\n"
            "Respond ONLY with valid JSON matching the schema."
        ),
        "extraction_schema": {
            "type": "object",
            "properties": {
                "invoice_number": {"type": "string"},
                "vendor_name": {"type": "string"},
                "bill_to": {"type": "string"},
                "invoice_date": {"type": "string"},
                "due_date": {"type": "string"},
                "line_items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "description": {"type": "string"},
                            "quantity": {"type": "number"},
                            "unit_price": {"type": "number"},
                            "amount": {"type": "number"},
                        },
                    },
                },
                "subtotal": {"type": "number"},
                "tax_amount": {"type": "number"},
                "total": {"type": "number"},
                "payment_terms": {"type": "string"},
            },
            "required": ["invoice_number", "vendor_name", "total"],
        },
    },
    "contract": {
        "prompt_template": (
            "You are an expert document data extractor. This is a contract.\n"
            "Extract all key fields listed in the schema below.\n\n"
            "Schema fields: {schema_fields}\n\n"
            "Document text:\n---\n{document_text}\n---\n\n"
            "Respond ONLY with valid JSON matching the schema."
        ),
        "extraction_schema": {
            "type": "object",
            "properties": {
                "contract_title": {"type": "string"},
                "parties": {"type": "array", "items": {"type": "string"}},
                "effective_date": {"type": "string"},
                "termination_date": {"type": "string"},
                "contract_value": {"type": "number"},
                "key_terms": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["contract_title", "parties"],
        },
    },
    "receipt": {
        "prompt_template": (
            "You are an expert document data extractor. This is a receipt.\n"
            "Extract all key fields listed in the schema below.\n\n"
            "Schema fields: {schema_fields}\n\n"
            "Document text:\n---\n{document_text}\n---\n\n"
            "Respond ONLY with valid JSON matching the schema."
        ),
        "extraction_schema": {
            "type": "object",
            "properties": {
                "merchant_name": {"type": "string"},
                "receipt_number": {"type": "string"},
                "date": {"type": "string"},
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "description": {"type": "string"},
                            "quantity": {"type": "number"},
                            "price": {"type": "number"},
                        },
                    },
                },
                "subtotal": {"type": "number"},
                "tax_amount": {"type": "number"},
                "total": {"type": "number"},
                "payment_method": {"type": "string"},
            },
            "required": ["merchant_name", "total"],
        },
    },
    "form": {
        "prompt_template": (
            "You are an expert document data extractor. This is a form document.\n"
            "Extract all key fields listed in the schema below.\n\n"
            "Schema fields: {schema_fields}\n\n"
            "Document text:\n---\n{document_text}\n---\n\n"
            "Respond ONLY with valid JSON matching the schema."
        ),
        "extraction_schema": {
            "type": "object",
            "properties": {
                "form_title": {"type": "string"},
                "form_number": {"type": "string"},
                "submitted_by": {"type": "string"},
                "submission_date": {"type": "string"},
                "fields": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "field_name": {"type": "string"},
                            "field_value": {"type": "string"},
                        },
                    },
                },
            },
            "required": ["form_title"],
        },
    },
    "other": {
        "prompt_template": (
            "You are an expert document data extractor. Analyze this document and "
            "extract any identifiable fields.\n\n"
            "Document text:\n---\n{document_text}\n---\n\n"
            "Respond ONLY with valid JSON matching the schema."
        ),
        "extraction_schema": {
            "type": "object",
            "properties": {
                "detected_text": {"type": "string"},
                "detected_fields": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "field_name": {"type": "string"},
                            "field_value": {"type": "string"},
                        },
                    },
                },
            },
        },
    },
}
