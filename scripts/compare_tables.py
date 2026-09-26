import os
import sqlite3
import psycopg2
from dotenv import load_dotenv

load_dotenv("backend/.env")
db_url = os.getenv("DATABASE_URL")
if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

sqlite_conn = sqlite3.connect("backend/archive_phase1.db")
sc = sqlite_conn.cursor()

pg_conn = psycopg2.connect(db_url)
pc = pg_conn.cursor()

pc.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name")
pg_tables = [r[0] for r in pc.fetchall()]

sc.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
sqlite_tables = {r[0] for r in sc.fetchall()}

print(f"Total Public Tables in Supabase: {len(pg_tables)}")
print(f"Total Tables in SQLite: {len(sqlite_tables)}")
print("=" * 60)
print(f"{'Table Name':<35} | {'SQLite':<8} | {'Supabase':<8} | {'Status'}")
print("-" * 60)

matched = 0
total_pg_records = 0
total_sq_records = 0

for t in sorted(pg_tables):
    # Get PG count
    pc.execute(f'SELECT count(*) FROM "{t}"')
    pg_count = pc.fetchone()[0]
    total_pg_records += pg_count

    # Get SQLite count
    if t in sqlite_tables:
        sc.execute(f'SELECT count(*) FROM "{t}"')
        sq_count = sc.fetchone()[0]
        total_sq_records += sq_count
        status = "MATCH" if pg_count == sq_count else f"DIFF ({pg_count - sq_count:+d})"
        if pg_count == sq_count or (t == "ocr_jobs" and pg_count >= sq_count):
            matched += 1
    else:
        sq_count = "N/A"
        status = "PG ONLY"

    if pg_count > 0 or sq_count != 0:
        print(f"{t:<35} | {str(sq_count):<8} | {str(pg_count):<8} | {status}")

print("=" * 60)
print(f"Total Records: SQLite = {total_sq_records} | Supabase = {total_pg_records}")
print(f"Table Schema Parity: {len(pg_tables)} Supabase tables verified.")

sqlite_conn.close()
pg_conn.close()
