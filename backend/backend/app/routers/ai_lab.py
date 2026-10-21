"""AI Lab API: the agent, advanced RAG answers, model status and training, forecasts, anomalies, optimisation and data quality."""
import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import models
from ..ai import data_quality
from ..ai.agent import orchestrator
from ..ai.agent.tools import REGISTRY, AllocIn, MatchIn, t_optimize_alloc, t_optimize_match
from ..ai.ml import anomaly_ml, forecast_models, need_model
from ..ai.rag import pipeline
from ..database import get_db
from ..dependencies import get_current_user
from ..services import audit
from .administration import active_admin

router = APIRouter(tags=["ai-lab"])
REPORT = Path("reports/ai/metrics.json")


class AskIn(BaseModel):
    question: str = Field(min_length=2, max_length=1000)
    create_proposals: bool = False


class RepairIn(BaseModel):
    fixes: list[str] = Field(min_length=1, max_length=5)


# ----------------------------------------------------------------------------- agent and advanced RAG (every signed-in role; tools are role gated)
@router.get("/agent/tools")
def agent_tools(user: dict = Depends(get_current_user)):
    return [t.spec() for t in REGISTRY.values() if user["role"] == "admin" or not t.admin_only]


@router.post("/agent/run")
def agent_run(body: AskIn, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    return orchestrator.run_agent(db, body.question, user, create_proposals=body.create_proposals)


@router.post("/assistant/answer")
def advanced_answer(body: AskIn, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """Evidence-based answer with citations (adaptive routing, query decomposition, hybrid + graph retrieval, corrective RAG, self-checks)."""
    try:
        from ..services.embeddings import embed_text
    except Exception:  # pragma: no cover
        embed_text = None
    return pipeline.answer_question(db, body.question, user, embed=embed_text)


# ----------------------------------------------------------------------------- administrator-only AI Lab
@router.get("/admin/ai/data-quality")
def ai_data_quality(admin: dict = Depends(active_admin), db: Session = Depends(get_db)):
    return data_quality.check(db)


@router.post("/admin/ai/data-quality/repair")
def ai_repair(body: RepairIn, admin: dict = Depends(active_admin), db: Session = Depends(get_db)):
    try:
        changed = data_quality.repair(db, body.fixes)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    audit.record_now(db, admin, "data.repaired", detail=changed)
    return {"changed": changed, "report": data_quality.check(db)}


@router.get("/admin/ai/models")
def ai_models(admin: dict = Depends(active_admin), db: Session = Depends(get_db)):
    model, meta = need_model.load()
    from ..ai.ml.dataset import training_frame
    frame = training_frame(db)
    return {"problem": "Will a need be fulfilled within 14 days of being posted?", "trained": model is not None, "meta": meta, "real_labelled_needs": len(frame),
            "min_rows": need_model.MIN_REAL_ROWS, "min_per_class": need_model.MIN_PER_CLASS,
            "note": "The baseline (urgency prior) is used until there is enough real history." if model is None else "A trained model is in use."}


@router.post("/admin/ai/models/train")
def ai_train(admin: dict = Depends(active_admin), db: Session = Depends(get_db)):
    out = need_model.train_from_db(db)
    audit.record_now(db, admin, "ai.model_train", detail={"trained": out["trained"], "rows": out["rows"]})
    return out


@router.get("/admin/ai/predict/{need_id}")
def ai_predict(need_id: int, admin: dict = Depends(active_admin), db: Session = Depends(get_db)):
    need = db.get(models.Need, need_id)
    if need is None:
        raise HTTPException(status_code=404, detail="Need not found")
    return need_model.predict(db, need)


@router.get("/admin/ai/forecast")
def ai_forecast(admin: dict = Depends(active_admin), db: Session = Depends(get_db)):
    out = []
    for cat, series in forecast_models.category_series(db).items():
        f = forecast_models.forecast_series(series)
        out.append({"category": cat, "history": series, **f})
    return sorted(out, key=lambda i: -i["forecast"])


@router.get("/admin/ai/anomalies")
def ai_anomalies(admin: dict = Depends(active_admin), db: Session = Depends(get_db)):
    scored = anomaly_ml.isolation_scores(anomaly_ml.donation_frame(db))
    top = scored.sort_values("anomaly_score", ascending=False).head(10)
    return {"donations": [{"donation_id": int(r.donation_id), "donor_id": int(r.donor_id), "amount": float(r.amount), "anomaly_score": float(r.anomaly_score), "reasons": r.reasons}
                          for r in top.itertuples() if r.anomaly_score > 0], "needs": anomaly_ml.cluster_needs(db)}


@router.get("/admin/ai/segments")
def ai_segments(admin: dict = Depends(active_admin), db: Session = Depends(get_db)):
    return anomaly_ml.donor_segments(db)


@router.post("/admin/ai/optimize/allocation")
def ai_optimize_allocation(body: AllocIn, admin: dict = Depends(active_admin), db: Session = Depends(get_db)):
    out = t_optimize_alloc(db, admin, body)
    audit.record(db, admin, "ai.optimize_allocation", detail={"fairness": body.fairness, "proposals": len(out["proposals_created"])})
    db.commit()
    return {**out, "requires_approval": True}


@router.post("/admin/ai/optimize/matching")
def ai_optimize_matching(body: MatchIn, admin: dict = Depends(active_admin), db: Session = Depends(get_db)):
    out = t_optimize_match(db, admin, body)
    audit.record(db, admin, "ai.optimize_matching", detail={"proposals": len(out["proposals_created"])})
    db.commit()
    return {**out, "requires_approval": True}


@router.get("/admin/ai/report")
def ai_report(admin: dict = Depends(active_admin)):
    """The last benchmark produced by scripts/run_ai_pipeline.py (synthetic benchmarks are labelled as such)."""
    if not REPORT.exists():
        return {"available": False, "hint": "Run: python scripts/run_ai_pipeline.py"}
    return {"available": True, **json.loads(REPORT.read_text())}
