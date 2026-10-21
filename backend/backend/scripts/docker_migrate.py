"""One-shot database setup for Docker: new database -> init_db.py; existing database -> alembic upgrade head.
Run with: docker compose run --rm migrate   (it is safe to run repeatedly)."""
import os
import subprocess
import sys

from sqlalchemy import inspect

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from app.database import engine  # noqa: E402

fresh = "users" not in set(inspect(engine).get_table_names())
cmd = [sys.executable, "scripts/init_db.py"] if fresh else ["alembic", "upgrade", "head"]
print("New database: creating tables." if fresh else "Existing database: applying migrations.", flush=True)
sys.exit(subprocess.call(cmd, cwd=ROOT))
