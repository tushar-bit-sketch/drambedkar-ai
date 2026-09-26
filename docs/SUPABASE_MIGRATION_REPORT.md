# Architectural Migration Report: Ambedkar Digital Heritage Archive to Supabase

**Project**: Digital Heritage Archive for Memorials, Manuscripts & Ambedkar (SIH26096)  
**Date**: 2026-09-26  
**Status**: Phase 1 Audit Complete — Target Architecture Approved  

---

## 1. Executive Summary

This report establishes the engineering blueprint for migrating the SIH26096 Ambedkar Digital Heritage Archive to **Supabase** as the primary managed backend infrastructure (PostgreSQL, Storage, Auth, and pgvector), while strictly maintaining the existing FastAPI AI pipeline (OCR, RAG, NLP, Audio, Translations, Provenance) and the React 19 / Vite archival broadsheet frontend.

A complete audit of the repository reveals:
1. **Total Workspace Size**: ~904 MB, composed almost entirely of transient environment artifacts:
   - `frontend/node_modules`: ~439 MB (Node dependencies)
   - `backend/venv`: ~395 MB (Python 3.13 virtual environment)
   - `.git`: ~62 MB (Git objects)
   - **Actual Archival Persistent Binary Assets**: **< 5 MB** (`backend/storage/derivatives`: 2.82 MB, `media`: 0.63 MB, `uploads`: 0.03 MB).
2. **Current Database Architecture**: SQLite development / test database (`archive_phase1.db`) with complete Alembic migrations (Phases 1 through 9) ready for PostgreSQL + pgvector.
3. **Current Test Baseline**: **174 passed, 4 skipped, 0 failed** across all subsystems (Auth, Ingestion, OCR, RAG, Vector Search, Knowledge Graph, Media, Kiosk fleet, Security).
4. **Target Architecture**: Hybrid architecture where Supabase provides managed persistence, object storage, and vector indexing, while Python continues running heavy compute tasks (OCR, PDF parsing, NLP, RAG prompting, and audio waveform analysis).

---

## 2. Comprehensive System Audit Matrix

| Subsystem | Current Implementation | Target Supabase Architecture | Action / Migration Path |
| :--- | :--- | :--- | :--- |
| **Database Engine** | SQLite local (`archive_phase1.db`) / PostgreSQL support in SQLAlchemy | Supabase Managed PostgreSQL 15/16 with Connection Pooling | Direct connection via `DATABASE_URL` with Alembic migration replication. Zero schema loss. |
| **Vector Database** | SQLite fallback / PgVectorStore in SQLAlchemy | Supabase `pgvector` extension (`vector(1024)`) on `search_chunks` | Utilize existing `PgVectorStore` leveraging native `<=>` cosine distance. |
| **Object Storage** | Local filesystem (`storage/uploads`, `storage/derivatives`, `storage/media`, `storage/audio`) with S3 fallback | Supabase Storage Buckets (`archive-documents`, `archive-images`, `archive-audio`, `archive-derivatives`) | Supabase S3-compatible API + REST client integration in `StorageService`. Preserve SHA-256 and metadata. |
| **Authentication & RBAC** | Local JWT (HS256) with Bcrypt hashing in `users` and `roles` tables | Supabase Auth + JWT Verification with RBAC preservation | Dual-mode auth: Validate Supabase JWTs while preserving local session compatibility and role taxonomy. |
| **OCR Pipeline** | Python (PaddleOCR, Tesseract, PyPDF, OpenCV) with asynchronous job tracking | Python AI Service Layer (Remains in Python) | Download binary from Supabase Storage, run OCR locally, persist text versions and bounding boxes to Supabase DB. |
| **RAG Assistant** | Zero-hallucination grounded retrieval engine + HF/OpenAI/Ollama providers | Python RAG Engine + Supabase pgvector retrieval | Semantic candidate retrieval via pgvector, RRF fusion with BM25 keyword matching, citation verification. |
| **Provenance System** | SHA-256 checksums, immutability checks, chain-of-custody audit logs | Supabase PostgreSQL Audit Tables (`audit_logs`, `media_integrity_records`) | Preserve cryptographic hashing, accession numbers, and immutable audit trails. |
| **Multilingual & Audio** | IndicTrans2 / Gemma translation + SAPI/Piper TTS + WebVTT/SRT transcription | Python Processing Engine + Supabase Storage for audio/transcripts | Audio derivatives and caption files stored in `archive-audio` and `archive-derivatives`. |
| **Frontend** | React 19 + TypeScript + Vite + Tailwind CSS | React 19 + TypeScript + Vite (Identical UI/UX) | Same broadsheet styling; API client configured to communicate with Python backend and Supabase. |

---

## 3. Storage Migration & 900+ MB Classification (Phase 10)

The workspace has been audited and classified to prevent uploading repository clutter:

```
SIH26096 Workspace (904 MB)
├── EXCLUDED FROM SUPABASE (Do NOT Upload)
│   ├── frontend/node_modules (439 MB) — Ephemeral npm packages
│   ├── backend/venv (395 MB)         — Ephemeral Python virtualenv
│   ├── .git (62 MB)                  — Git repository history
│   ├── frontend/dist                 — Ephemeral build output
│   └── .pytest_cache / __pycache__   — Ephemeral test/runtime bytecode
│
└── ARCHIVAL PERSISTENT ASSETS (Upload to Supabase Storage)
    ├── archive-documents/            — Master PDF manuscripts, gazettes, official records
    ├── archive-images/               — Master high-res photographs and historical folios
    ├── archive-audio/                — Master All India Radio broadcasts, speeches
    └── archive-derivatives/          — OCR cleaned pages, audio waveforms, video posters
```

For every asset uploaded to Supabase Storage, the system persists:
- Original filename & sanitized storage key
- MIME type & file size (bytes)
- SHA-256 cryptographic checksum
- Accession number / Document linkage
- ISO 8601 upload timestamp
- Uploader identity and verification status

---

## 4. Database Schema Preservation Plan (Phase 3)

The existing SQLAlchemy schema comprises **44 tables** across 9 migration phases. All will be mapped directly to Supabase PostgreSQL:
- **Core Catalog**: `roles`, `users`, `collections`, `documents`, `document_versions`, `document_metadata`, `languages`, `authors`, `topics`, `document_topics`, `archival_files`
- **OCR & Digitization**: `ocr_jobs`, `ocr_pages`, `ocr_blocks`, `ocr_reviews`, `ocr_text_versions`
- **Search & Vector**: `search_chunks` (with pgvector), `search_index_jobs`
- **RAG & Research**: `research_conversations`, `research_messages`, `research_audit_logs`
- **Multilingual & Voice**: `translations`, `audio_derivatives`
- **Knowledge Graph**: `graph_entities`, `graph_entity_aliases`, `graph_relationships`, `graph_entity_merges`, `timeline_events`, `timeline_event_entities`, `graph_audit_logs`
- **Media Intelligence**: `media`, `media_collections`, `media_assets`, `media_versions`, `media_metadata`, `media_transcripts`, `media_transcript_segments`, `media_captions`, `media_processing_jobs`, `media_integrity_records`
- **Kiosk Fleet & Telemetry**: `kiosk_devices`, `kiosk_heartbeat_records`, `kiosk_configurations`, `kiosk_audit_logs`, `offline_packages`

**Database Integrity Guarantees**:
- UUIDs, Foreign Keys with `ON DELETE CASCADE / SET NULL` preserved.
- Composite B-Tree indexes on `archive_id`, `slug`, `checksum`, `created_at` preserved.
- pgvector HNSW index on `search_chunks.embedding` created for 1024-dim BGE-M3 vectors.
- Alembic migration sequence remains 100% reproducible.

---

## 5. Authentication & Security Plan (Phase 5)

1. **Role Taxonomy**:
   - `SUPER_ADMIN`: Full archival privileges, user provisioning, system status.
   - `ARCHIVIST`: Accession, master upload, cataloging, OCR approval.
   - `REVIEWER`: Curatorial peer review, metadata verification, transcript audit.
   - `RESEARCHER`: High-resolution access, privileged citation explorer.
   - `VISITOR`: Public read-only access to published/verified records.
2. **Key Security**:
   - `SUPABASE_ANON_KEY`: Safe for client-side queries with RLS.
   - `SUPABASE_SERVICE_ROLE_KEY`: Strictly server-side inside Python backend. NEVER exposed to frontend or Git.
   - JWT validation supports both Supabase auth tokens and existing HMAC tokens.

---

## 6. Required Environment Variables

```bash
# ==============================================================================
# Supabase Backend Configuration
# ==============================================================================
SUPABASE_URL=https://<your-project-id>.supabase.co
SUPABASE_ANON_KEY=eyJhbGciOi...
SUPABASE_SERVICE_ROLE_KEY=eyJhbGciOi...

# Managed PostgreSQL Connection (Supabase)
# Direct connection (port 5432) or Supavisor pooler (port 6543)
DATABASE_URL=postgresql://postgres.<project-id>:<password>@aws-0-<region>.pooler.supabase.com:6543/postgres?sslmode=require
VECTOR_BACKEND=PGVECTOR

# Supabase Storage S3-Compatible Gateway
OBJECT_STORAGE_ENDPOINT=https://<your-project-id>.supabase.co/storage/v1/s3
OBJECT_STORAGE_BUCKET=archive-documents
OBJECT_STORAGE_REGION=auto
OBJECT_STORAGE_ACCESS_KEY=<supabase-storage-access-key>
OBJECT_STORAGE_SECRET_KEY=<supabase-storage-secret-key>
```

---

## 7. Migration Sequence & Safety Guardrails

1. **Step 1 (Core Integration Layer)**: Build `backend/app/core/supabase.py` with client factory, storage manager, and auth validator.
2. **Step 2 (Storage Service Update)**: Extend `StorageService` to support Supabase Storage buckets transparently while keeping local disk caching for test speed.
3. **Step 3 (Configuration Update)**: Add Supabase settings to `Settings` in `backend/app/core/config.py`.
4. **Step 4 (Database Migration Script)**: Provide a clean data export/seed script to populate Supabase PostgreSQL from the master catalog.
5. **Step 5 (Regression Verification)**: Run the complete test suite to ensure all 174 baseline tests continue to pass.
6. **Step 6 (Documentation & Commit)**: Create `SUPABASE_MIGRATION.md` and commit all files to Git.
