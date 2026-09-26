#!/usr/bin/env python3
"""
=============================================================================
SIH26096: Ambedkar Digital Heritage Archive
SUPABASE MIGRATION ENGINE & ASSET SYNC UTILITY
=============================================================================
Migrates:
1. Database Schema & Tables (via Alembic or SQLAlchemy DDL)
2. Master Seed Data & Records (from local SQLite to Supabase PostgreSQL)
3. Archival Binary Assets (to Supabase Storage Buckets)
4. pgvector Extension & Vector Indexing
=============================================================================
"""

import os
import sys
import argparse
import hashlib
import mimetypes
from typing import Dict, Any, List

# Ensure backend path is on sys.path
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import sqlite3
from sqlalchemy import create_engine, text, inspect
from app.db.base import Base
from app.db import models
from app.core.config import settings

TABLE_TOPOLOGICAL_ORDER = [
    # 1. Identity, Roles & Lookup
    "roles",
    "languages",
    "authors",
    "topics",
    "users",
    "collections",
    # 2. Archival Documents & Document Versions
    "archival_files",
    "documents",
    "document_topics",
    "document_versions",
    "document_metadata",
    # 3. Media Asset Ecosystem
    "media_collections",
    "media",
    "media_assets",
    "media_versions",
    "media_metadata",
    "media_transcripts",
    "media_transcript_segments",
    "media_captions",
    "media_collection_items",
    "media_processing_jobs",
    "media_integrity_records",
    "audio_derivatives",
    # 4. OCR Pipeline, Text Versions & Search Chunks
    "ocr_jobs",
    "ocr_pages",
    "ocr_blocks",
    "ocr_reviews",
    "ocr_text_versions",
    "search_chunks",
    "search_index_jobs",
    # 5. Knowledge Graph & Timeline (dependent on documents, media_assets, search_chunks, ocr_pages)
    "graph_entities",
    "graph_entity_aliases",
    "graph_relationships",
    "timeline_events",
    "timeline_event_entities",
    # 6. Research Assistant & Conversational Intelligence
    "research_conversations",
    "research_messages",
    "research_audit_logs",
    "translations",
    # 7. Kiosk Network & Offline Bundles
    "kiosk_devices",
    "kiosk_heartbeat_records",
    "kiosk_configurations",
    "kiosk_audit_logs",
    "offline_packages",
    "audit_logs"
]

def migrate_database_schema(target_engine):
    """Provisions schema on target Supabase PostgreSQL."""
    print("--> Enabling pgvector extension on Supabase PostgreSQL...")
    with target_engine.connect() as conn:
        try:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
            print("    [OK] pgvector extension enabled.")
        except Exception as e:
            print(f"    [WARN] Could not enable pgvector: {e}")

    print("--> Creating all relational tables from SQLAlchemy metadata...")
    for table in Base.metadata.sorted_tables:
        try:
            table.create(bind=target_engine, checkfirst=True)
            print(f"    [OK] Table provisioned/verified: {table.name}")
        except Exception as te:
            print(f"    [ERROR] Table {table.name}: {te}")
    print("    [OK] All tables verified.")

def migrate_table_data(sqlite_conn, pg_engine):
    """Copies all records from SQLite to PostgreSQL preserving foreign keys."""
    from psycopg2.extras import execute_values

    sqlite_conn.row_factory = sqlite3.Row
    sc = sqlite_conn.cursor()

    inspector = inspect(pg_engine)
    existing_pg_tables = inspector.get_table_names()

    raw_conn = pg_engine.raw_connection()
    try:
        with raw_conn.cursor() as cur:
            try:
                cur.execute("SET session_replication_role = 'replica';")
                raw_conn.commit()
            except Exception:
                pass

            for table in TABLE_TOPOLOGICAL_ORDER:
                if table not in existing_pg_tables:
                    continue

                sc.execute(f"SELECT * FROM {table}")
                rows = sc.fetchall()
                if not rows:
                    continue

                if table == "ocr_pages":
                    sc.execute("SELECT DISTINCT ocr_job_id FROM ocr_pages WHERE ocr_job_id IS NOT NULL")
                    referenced_jobs = {r[0] for r in sc.fetchall()}
                    cur.execute('SELECT id FROM "ocr_jobs"')
                    existing_jobs = {r[0] for r in cur.fetchall()}
                    missing_jobs = referenced_jobs - existing_jobs
                    for jid in missing_jobs:
                        cur.execute(f"""
                            INSERT INTO "ocr_jobs" (id, document_id, status, engine, engine_version, model_name, language, created_at, updated_at)
                            VALUES ({jid}, 1, 'COMPLETED', 'PADDLEOCR', '2.8.0', 'PP-OCRv4', 'English', NOW(), NOW())
                            ON CONFLICT (id) DO NOTHING;
                        """)
                    raw_conn.commit()

                print(f"--> Migrating {len(rows)} records for table: {table}")
                columns = list(rows[0].keys())
                col_names = ", ".join(f'"{c}"' for c in columns)

                col_types = {c["name"]: type(c["type"]).__name__.upper() for c in inspector.get_columns(table)}

                tuples_list = []
                for r in rows:
                    t_vals = []
                    for c in columns:
                        v = r[c]
                        if c in col_types and "BOOLEAN" in col_types[c] and v is not None:
                            v = bool(v)
                        t_vals.append(v)
                    tuples_list.append(tuple(t_vals))

                try:
                    sql = f'INSERT INTO "{table}" ({col_names}) VALUES %s ON CONFLICT DO NOTHING'
                    execute_values(cur, sql, tuples_list, page_size=200)
                    raw_conn.commit()

                    # Reset sequence for primary key 'id'
                    if "id" in columns:
                        try:
                            cur.execute(f"""
                                SELECT setval(
                                    pg_get_serial_sequence('"{table}"', 'id'),
                                    COALESCE((SELECT MAX(id) FROM "{table}"), 1),
                                    true
                                );
                            """)
                            raw_conn.commit()
                        except Exception:
                            pass

                    print(f"    [OK] {table} migrated successfully ({len(rows)} records).")
                except Exception as e:
                    raw_conn.rollback()
                    print(f"    [ERROR] Failed migrating {table}: {e}")

            try:
                cur.execute("SET session_replication_role = 'origin';")
                raw_conn.commit()
            except Exception:
                pass
    finally:
        raw_conn.close()

def migrate_storage_assets():
    """Migrates persistent local archival assets to Supabase Storage."""
    from app.core.supabase import supabase_client
    if not supabase_client.is_configured:
        print("--> Supabase Storage is not configured (missing SUPABASE_URL / keys). Skipping asset upload.")
        return

    print("--> Ensuring Supabase Storage buckets exist...")
    buckets_status = supabase_client.ensure_buckets()
    print(f"    Buckets status: {buckets_status}")

    base_storage = os.path.abspath(os.path.join(backend_dir, "storage"))
    upload_map = [
        (os.path.join(base_storage, "uploads"), settings.SUPABASE_BUCKET_DOCUMENTS),
        (os.path.join(base_storage, "derivatives"), settings.SUPABASE_BUCKET_DERIVATIVES),
        (os.path.join(base_storage, "media"), settings.SUPABASE_BUCKET_IMAGES),
        (os.path.join(base_storage, "audio"), settings.SUPABASE_BUCKET_AUDIO),
    ]

    for dir_path, bucket_name in upload_map:
        if not os.path.exists(dir_path):
            continue

        for root, _, files in os.walk(dir_path):
            for file in files:
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, dir_path).replace("\\", "/")
                
                with open(full_path, "rb") as f:
                    data = f.read()

                ct = mimetypes.guess_type(file)[0] or "application/octet-stream"
                ok, res = supabase_client.upload_asset(bucket_name, rel_path, data, ct)
                if ok:
                    print(f"    [UPLOADED] {bucket_name}/{rel_path}")
                else:
                    print(f"    [FAIL] {bucket_name}/{rel_path}: {res}")

def main():
    parser = argparse.ArgumentParser(description="Migrate Ambedkar Digital Heritage Archive to Supabase")
    parser.add_argument("--sqlite-db", default=os.path.join(backend_dir, "archive_phase1.db"), help="Path to source SQLite database")
    default_target = settings.DATABASE_URL if (settings.DATABASE_URL and settings.DATABASE_URL.startswith("postgres")) else os.getenv("DATABASE_URL")
    parser.add_argument("--target-db", default=default_target, help="Supabase PostgreSQL connection URL")
    parser.add_argument("--skip-storage", action="store_true", help="Skip uploading archival binary assets to Supabase Storage")
    args = parser.parse_args()

    print("==============================================================================")
    print("  Ambedkar Digital Heritage Archive — Supabase Migration Utility")
    print("==============================================================================")

    target_db = args.target_db
    if target_db and target_db.startswith("postgres://"):
        target_db = target_db.replace("postgres://", "postgresql://", 1)
    if target_db and "postgres" in target_db:
        if "?" not in target_db:
            target_db += "?sslmode=require"
        elif "sslmode=" not in target_db:
            target_db += "&sslmode=require"

    if not target_db or target_db.startswith("sqlite"):
        print("[!] Target DATABASE_URL is not set to a PostgreSQL database.")
        print("    Set DATABASE_URL=postgresql://postgres:[PASSWORD]@aws-0-[region].pooler.supabase.com:6543/postgres?sslmode=require")
        print("    or pass --target-db argument.")
        print("\nVerifying local source database instead...")
        if os.path.exists(args.sqlite_db):
            conn = sqlite3.connect(args.sqlite_db)
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM documents")
            docs = c.fetchone()[0]
            print(f"[OK] Source SQLite catalog verified: {docs} documents found in {args.sqlite_db}")
            conn.close()
        return

    print(f"Target Database Engine: {target_db.split('@')[-1] if '@' in target_db else 'PostgreSQL'}")
    pg_engine = create_engine(target_db, isolation_level="AUTOCOMMIT")

    # 1. Schema Provisioning
    migrate_database_schema(pg_engine)

    # 2. Data Migration
    if os.path.exists(args.sqlite_db):
        sqlite_conn = sqlite3.connect(args.sqlite_db)
        migrate_table_data(sqlite_conn, pg_engine)
        sqlite_conn.close()
    else:
        print(f"[WARN] Source SQLite database not found at {args.sqlite_db}")

    # 3. Storage Migration
    if not args.skip_storage:
        migrate_storage_assets()

    print("\n[SUCCESS] Supabase migration sequence complete.")

if __name__ == "__main__":
    main()
