"""Run:  python scripts/check_schema.py

Prints whether the backend can reach PostgreSQL and whether every table/column the code
expects really exists in the live database. If anything is missing it tells you the fix.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from app.diagnostics import health_report  # noqa: E402


def main() -> None:
    report = health_report()
    print(json.dumps(report, indent=2, default=str))
    schema = report.get("schema") or {}
    if not report["database"].get("connected"):
        print("\nX  Cannot connect to the database. Check DATABASE_URL in backend/.env")
        raise SystemExit(1)
    if not report["secret_key_configured"]:
        print("\nX  SECRET_KEY is missing in backend/.env - login cannot issue tokens")
    if schema.get("ok"):
        print("\nOK  Database reachable and schema matches the code (alembic:", schema.get("alembic_version"), ")")
    else:
        print("\nX  Schema drift detected ->", schema.get("fix"))
        raise SystemExit(2)


if __name__ == "__main__":
    main()
