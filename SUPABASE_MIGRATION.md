# Supabase Production Architecture & Migration Guide

**Project**: Dr. B. R. Ambedkar Digital Heritage Archive (SIH26096)  
**Target Infrastructure**: Supabase Managed Backend (PostgreSQL, Storage, Auth, pgvector) + Python AI Service + React 19 Broadsheet SPA

---

## 1. Architecture Topology

```
┌────────────────────────────────────────────────────────────────────────┐
│                   CLIENT BROWSERS & MEMORIAL KIOSKS                    │
│               https://frontend-kappa-six-80.vercel.app                 │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    │ HTTPS API Calls (Bearer Token)
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                      FASTAPI AI BACKEND SERVICE                        │
│  - OCR Pipeline (PaddleOCR, Tesseract, OpenCV Preprocessing)           │
│  - RAG Orchestrator & Citation Validator (Zero-Hallucination)          │
│  - Multilingual Engine (IndicTrans2, Gemma Fallback)                   │
│  - Audio Intelligence & Waveform Analyzer                              │
│  - OAIS Provenance & SHA-256 Chain of Custody                          │
└───────────────────┬────────────────────────────────┬───────────────────┘
                    │                                │
     SQLAlchemy /   │                                │ Supabase REST /
     PostgreSQL     ▼                                ▼ S3 Gateway
┌───────────────────────────────────────┐  ┌─────────────────────────────┐
│          SUPABASE POSTGRESQL          │  │      SUPABASE STORAGE       │
│  - 44 Relational Tables               │  │  - archive-documents        │
│  - pgvector (1024-dim BGE-M3)         │  │  - archive-images           │
│  - Row Level Security (RLS)           │  │  - archive-audio            │
│  - Connection Pooler (Port 6543/5432) │  │  - archive-derivatives      │
│  - Supabase Auth (JWT & RBAC claims)  │  │  - S3 / Public CDN URLs     │
└───────────────────────────────────────┘  └─────────────────────────────┘
```

---

## 2. Supabase Project Setup (Step-by-Step)

### Step 1: Create a Supabase Project
1. Log in to [database.new](https://database.new) or [supabase.com](https://supabase.com).
2. Click **New project**, select your organization, name it `ambedkar-digital-heritage`, set a database password, and choose your preferred region (e.g. `ap-south-1` for India / Mumbai).

### Step 2: Enable Database Extensions
Open **SQL Editor** in Supabase and run:
```sql
-- Enable vector extension for BGE-M3 semantic retrieval
CREATE EXTENSION IF NOT EXISTS vector;

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Enable pg_trgm for fast fuzzy keyword search
CREATE EXTENSION IF NOT EXISTS pg_trgm;
```

### Step 3: Create Storage Buckets
In the Supabase Dashboard, navigate to **Storage** > **New bucket**:
1. `archive-documents`: **Public** (or private with signed URLs for restricted folios)
2. `archive-images`: **Public**
3. `archive-audio`: **Public**
4. `archive-derivatives`: **Public**

Alternatively, run the automated provisioning script:
```bash
python scripts/migrate_to_supabase.py --skip-storage
```

### Step 4: Configure Storage Security Policies (RLS)
Under **Storage** > **Policies**, apply the following SQL policies:

```sql
-- Allow public read access to verified archival assets
CREATE POLICY "Public Read Access"
ON storage.objects FOR SELECT
USING (bucket_id IN ('archive-documents', 'archive-images', 'archive-audio', 'archive-derivatives'));

-- Allow authenticated archival staff to upload
CREATE POLICY "Staff Upload Access"
ON storage.objects FOR INSERT
TO authenticated
WITH CHECK (bucket_id IN ('archive-documents', 'archive-images', 'archive-audio', 'archive-derivatives'));

-- Allow service_role complete master vault authority
CREATE POLICY "Service Role Master Access"
ON storage.objects FOR ALL
TO service_role
USING (true)
WITH CHECK (true);
```

---

## 3. Database Migration Execution

To migrate the schema and all 56 documents, timeline events, and entities to Supabase PostgreSQL:

```bash
# 1. Set target Supabase connection string
export DATABASE_URL="postgresql://postgres.[PROJECT_REF]:[PASSWORD]@aws-0-[REGION].pooler.supabase.com:6543/postgres?sslmode=require"
export SUPABASE_URL="https://[PROJECT_REF].supabase.co"
export SUPABASE_SERVICE_ROLE_KEY="eyJhbGciOi..."

# 2. Run automated migration engine
python scripts/migrate_to_supabase.py
```

This utility automatically:
1. Verifies the `vector` extension.
2. Creates all 44 tables in SQLAlchemy topological order.
3. Transfers catalog folios, Dublin Core metadata, and audit trails.
4. Uploads local archival master assets to their respective Supabase Storage buckets.

---

## 4. Authentication & RBAC Mapping

The platform uses a unified 5-tier role taxonomy across Supabase Auth and the FastAPI backend:

| Institutional Role | Access Level | Capabilities |
| :--- | :--- | :--- |
| **`SUPER_ADMIN`** | Institutional Director | Full administrative privileges, user management, audit logs, system diagnostics. |
| **`ARCHIVIST`** | Senior Heritage Curator | Master accession, OCR trigger, transcript review, metadata editing. |
| **`REVIEWER`** | Peer Review Panel | Verification approvals, provenance validation, caption reviews. |
| **`RESEARCHER`** | Academic Scholar | High-resolution manuscript reading, citation export, deep search. |
| **`VISITOR`** | Public Citizen | Read-only search, timeline browsing, verified records, kiosk exploration. |

When users authenticate via Supabase Auth (email/password or SSO), their `user_metadata.role` or `app_metadata.role` is verified and bound by `get_current_user_optional` in `backend/app/api/v1/endpoints/auth.py`.

---

## 5. RAG & Vector Search with pgvector

- **Dense Embeddings**: BAAI/bge-m3 (1024 dimensions).
- **Distance Operator**: Native cosine distance (`<=>`).
- **Hybrid Retrieval**: RRF (Reciprocal Rank Fusion) combining PostgreSQL full-text keyword search (`to_tsvector`) with semantic vector ranking.
- **Index**:
```sql
CREATE INDEX IF NOT EXISTS idx_search_chunks_embedding_hnsw 
ON search_chunks USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);
```

---

## 6. OCR & Heavy Processing Architecture

Heavy AI workloads remain strictly in the Python processing service:
1. **Document Upload** ➔ Uploaded to Supabase bucket `archive-documents`.
2. **Preprocessing** ➔ Python worker streams file, runs OpenCV deskewing, noise reduction, and contrast enhancement.
3. **OCR Engine** ➔ PaddleOCR / Tesseract generates text versions and bounding boxes.
4. **Ingestion** ➔ Extracted text is stored in `ocr_text_versions` and chunked into `search_chunks`.
5. **Embedding** ➔ Dense vectors are generated and indexed directly in Supabase `search_chunks.embedding`.

---

## 7. Environment Variables Reference

```bash
# Database
DATABASE_URL=postgresql://postgres.[PROJECT_REF]:[PASSWORD]@aws-0-[REGION].pooler.supabase.com:6543/postgres?sslmode=require
VECTOR_BACKEND=PGVECTOR

# Supabase
SUPABASE_URL=https://[PROJECT_REF].supabase.co
SUPABASE_ANON_KEY=eyJhbGciOi...
SUPABASE_SERVICE_ROLE_KEY=eyJhbGciOi...
SUPABASE_JWT_SECRET=your-supabase-jwt-secret

# Archival Buckets
SUPABASE_BUCKET_DOCUMENTS=archive-documents
SUPABASE_BUCKET_IMAGES=archive-images
SUPABASE_BUCKET_AUDIO=archive-audio
SUPABASE_BUCKET_DERIVATIVES=archive-derivatives

# LLM Grounded RAG
LLM_PROVIDER=huggingface
HF_BASE_URL=https://router.huggingface.co/v1
HF_MODEL=meta-llama/Llama-3.1-8B-Instruct
HF_TOKEN=hf_...
```
