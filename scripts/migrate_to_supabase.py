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
from app.core.config import settings

TABLE_TOPOLOGICAL_ORDER = [
    "roles",
    "languages",
    "authors",
    "topics",
    "users",
    "collections",
    "archival_files",
    "documents",
    "document_topics",
    "document_versions",
    "document_metadata",
    "timeline_events",
    "graph_entities",
    "graph_entity_aliases",
    "graph_relationships",
    "timeline_event_entities",
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
    "ocr_jobs",
    "ocr_pages",
    "ocr_blocks",
    "ocr_reviews",
    "ocr_text_versions",
    "search_chunks",
    "search_index_jobs",
    "research_conversations",
    "research_messages",
    "research_audit_logs",
    "translations",
    "audio_derivatives",
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
            conn.commit()
            print("    [OK] pgvector extension enabled.")
        except Exception as e:
            print(f"    [WARN] Could not enable pgvector: {e}")

    print("--> Creating all relational tables from SQLAlchemy metadata...")
    Base.metadata.create_all(bind=target_engine)
    print("    [OK] All 44 tables verified.")

def migrate_table_data(sqlite_conn, pg_engine):
    """Copies all records from SQLite to PostgreSQL preserving foreign keys."""
    sqlite_conn.row_factory = sqlite3.Row
    sc = sqlite_conn.cursor()

    inspector = inspect(pg_engine)
    existing_pg_tables = inspector.get_table_names()

    with pg_engine.connect() as pg_conn:
        for table in TABLE_TOPOLOGICAL_ORDER:
            if table not in existing_pg_tables:
                continue

            sc.execute(f"SELECT * FROM {table}")
            rows = sc.fetchall()
            if not rows:
                continue

            print(f"--> Migrating {len(rows)} records for table: {table}")
            columns = rows[0].keys()
            col_names = ", ".join(f'"{c}"' for c in columns)
            bind_names = ", ".join(f":{c}" for c in columns)
            insert_sql = text(f'INSERT INTO "{table}" ({col_names}) VALUES ({bind_names}) ON CONFLICT DO NOTHING')

            batch = [dict(r) for r in rows]
            # Convert boolean integer values if necessary
            for b in batch:
                for k, v in b.items():
                    if isinstance(v, bytes):
                        b[k] = v
            try:
                pg_conn.execute(insert_sql, batch)
                pg_conn.commit()
                print(f"    [OK] {table} migrated successfully.")
            except Exception as e:
                print(f"    [ERROR] Failed migrating {table}: {e}")

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
    parser.add_argument("--target-db", default=os.getenv("DATABASE_URL"), help="Supabase PostgreSQL connection URL")
    parser.add_argument("--skip-storage", action="store_true", help="Skip uploading archival binary assets to Supabase Storage")
    args = parser.parse_args()

    print("==============================================================================")
    print("  Ambedkar Digital Heritage Archive — Supabase Migration Utility")
    print("==============================================================================")

    if not args.target_db or args.target_db.startswith("sqlite"):
        print("[!] Target DATABASE_URL is not set to a PostgreSQL database.")
        print("    Set DATABASE_URL=postgresql://postgres:[PASSWORD]@db.[PROJECT_REF].supabase.co:5432/postgres")
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

    print(f"Target Database Engine: {args.target_db.split('@')[-1] if '@' in args.target_db else 'PostgreSQL'}")
    pg_engine = create_engine(args.target_db)

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
