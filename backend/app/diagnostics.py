"""Checks that answer "is the backend really talking to the database?"."""
import os

from sqlalchemy import func, inspect, text

from . import models
from .database import Base, engine


def schema_report() -> dict:
    """Compare the live database with the SQLAlchemy models and list any drift."""
    inspector = inspect(engine)
    live_tables = set(inspector.get_table_names())
    missing_tables, missing_columns = [], {}
    for table in Base.metadata.sorted_tables:
        if table.name not in live_tables:
            missing_tables.append(table.name)
            continue
        live_columns = {col["name"] for col in inspector.get_columns(table.name)}
        absent = [col.name for col in table.columns if col.name not in live_columns]
        if absent:
            missing_columns[table.name] = absent

    alembic_version = None
    if "alembic_version" in live_tables:
        with engine.connect() as conn:
            alembic_version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    return {
        "ok": not missing_tables and not missing_columns,
        "missing_tables": missing_tables,
        "missing_columns": missing_columns,
        "alembic_version": alembic_version,
        "fix": None
        if not missing_tables and not missing_columns
        else "Run `alembic upgrade head` from the backend folder, then restart uvicorn.",
    }


def health_report(app_state=None) -> dict:
    report = {
        "database": {"connected": False},
        "secret_key_configured": bool((os.getenv("SECRET_KEY") or "").strip()),
        "models": {},
        "assistant": {},
    }
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        report["database"] = {"connected": True, "dialect": engine.dialect.name}
    except Exception as exc:  # pragma: no cover - depends on the live DB
        report["database"] = {"connected": False, "error": f"{type(exc).__name__}: {exc}"[:300]}
        return report

    report["schema"] = schema_report()
    if app_state is not None:
        report["models"] = {
            "career_recommender": getattr(app_state, "career_recommender", None) is not None,
            "fraud_detector": getattr(app_state, "fraud_detector", None) is not None,
        }

    from .database import SessionLocal

    db = SessionLocal()
    try:
        counts = {}
        for label, model in (
            ("users", models.User),
            ("organizations", models.Organization),
            ("children", models.Child),
            ("needs", models.Need),
            ("donors", models.Donor),
            ("volunteers", models.Volunteer),
            ("donations", models.Donation),
            ("matches", models.Match),
            ("knowledge_base", models.KnowledgeBase),
        ):
            try:
                counts[label] = db.query(func.count(model.id)).scalar() or 0
            except Exception as exc:
                db.rollback()
                counts[label] = f"error: {type(exc).__name__}"
        report["row_counts"] = counts
        try:
            embedded = (
                db.query(func.count(models.KnowledgeBase.id))
                .filter(models.KnowledgeBase.embedding.isnot(None))
                .scalar()
                or 0
            )
            report["assistant"] = {
                "knowledge_entries": counts.get("knowledge_base"),
                "embedded_entries": embedded,
                "mode": "grounded_generation" if os.getenv("OPENAI_API_KEY") else "retrieval_only",
            }
        except Exception as exc:
            db.rollback()
            report["assistant"] = {"error": f"{type(exc).__name__}"}
    finally:
        db.close()
    return report
