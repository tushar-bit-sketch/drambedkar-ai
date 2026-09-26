import os
import sys

# Ensure local SQLite fallback database is used for fast, deterministic unit tests
# while preserving live Supabase production configuration in .env
if not os.getenv("FORCE_REMOTE_TEST_DB"):
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sqlite_path = os.path.join(backend_dir, "archive_phase1.db").replace("\\", "/")
    os.environ["DATABASE_URL"] = f"sqlite:///{sqlite_path}"
