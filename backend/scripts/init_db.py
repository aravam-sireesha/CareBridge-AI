"""Create every table for a brand-new database and mark it as up to date for Alembic.

Use this on a NEW machine / empty database only:
    python scripts/init_db.py
    python scripts/create_admin.py            # first administrator
Existing databases should keep using `alembic upgrade head`, then `python scripts/check_schema.py`.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import inspect  # noqa: E402

from app import models  # noqa: E402,F401  (registers every table on Base.metadata)
from app.database import Base, engine  # noqa: E402


def main() -> None:
    existing = set(inspect(engine).get_table_names())
    app_tables = {t.name for t in Base.metadata.sorted_tables}
    if existing & app_tables:
        raise SystemExit(
            "This database already has CareBridge tables. Use `alembic upgrade head` instead of init_db.py."
        )
    Base.metadata.create_all(engine)
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    cfg = Config(os.path.join(root, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(root, "alembic"))
    command.stamp(cfg, "head")
    print(f"Created {len(app_tables)} tables and stamped Alembic at head.")


if __name__ == "__main__":
    main()
