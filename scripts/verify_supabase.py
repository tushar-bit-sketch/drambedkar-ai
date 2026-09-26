import os
import psycopg2
from dotenv import load_dotenv

load_dotenv("backend/.env")
db_url = os.getenv("DATABASE_URL")
if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

conn = psycopg2.connect(db_url)
cur = conn.cursor()

cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name")
tables = [r[0] for r in cur.fetchall()]
print(f"Total provisioned public tables: {len(tables)}")

total_records = 0
for t in tables:
    try:
        cur.execute(f'SELECT count(*) FROM "{t}"')
        cnt = cur.fetchone()[0]
        if cnt > 0:
            print(f"  {t}: {cnt} rows")
            total_records += cnt
    except Exception as e:
        print(f"  {t}: ERROR ({e})")
        conn.rollback()

print(f"\nTotal records across all tables: {total_records}")
conn.close()
