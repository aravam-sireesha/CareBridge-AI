"""Agent workspace API: propose a plan, approve it, watch it execute, read the history.

POST /agent/runs                    plan only (nothing runs)                      -> run (status awaiting_approval)
POST /agent/runs/{id}/approve       run the plan, streamed as Server-Sent Events  (only the owner; only once)
POST /agent/runs/{id}/reject        discard a plan
GET  /agent/runs, /agent/runs/{id}  history (your own runs; administrators can read all with ?scope=all)
GET  /agent/runs/{id}/report        downloadable Markdown report built from the stored, verified results
GET  /agent/examples                starter goals for the signed-in role
Execution is gated twice: by the owner's explicit approval, and per tool by the existing role checks. Every transition is audited."""
from __future__ import annotations

import logging
import threading
from typing import Iterator

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import models
from ..ai.agent import runner
from ..database import SessionLocal, get_db
from ..dependencies import get_current_user
from ..services import audit
from ..services.ids import parse_id
from ..services.sse import SSE_HEADERS, sse

router = APIRouter(prefix="/agent", tags=["agent"])
logger = logging.getLogger(__name__)
_running: set[int] = set()
_guard = threading.Lock()


def run_id_path(run_id: str = Path(..., description="Numeric id of the run")) -> int:
    return parse_id(run_id, "Run id")


class GoalIn(BaseModel):
    goal: str = Field(min_length=3, max_length=1000)


class ApproveIn(BaseModel):
    create_proposals: bool = False   # lets proposal-creating tools add items to the review queue (administrators only)


def _out(r: models.AgentRun) -> dict:
    status = r.status
    if status == "running" and r.id not in _running:   # the process that was running it is gone (restart / crash)
        status = "failed"
    return {"id": r.id, "goal": r.goal, "status": status, "route": r.route, "plan": r.plan or [], "planned_by": r.planned_by, "steps": r.steps or [],
            "answer": r.answer, "validation": r.validation, "create_proposals": r.create_proposals, "requires_approval": r.requires_approval,
            "duration_ms": r.duration_ms, "error": r.error or ("Interrupted: the server restarted while this run was executing." if status != r.status else None),
            "created_at": r.created_at, "updated_at": r.updated_at}


def _visible(db: Session, user: dict, run_id: int) -> models.AgentRun:
    q = db.query(models.AgentRun).filter(models.AgentRun.id == run_id)
    if user["role"] != "admin":
        q = q.filter(models.AgentRun.user_id == user["id"])
    row = q.first()
    if row is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return row


@router.get("/examples")
def examples(user: dict = Depends(get_current_user)):
    return {"examples": runner.EXAMPLES.get(user["role"], [])}


@router.post("/runs", status_code=201)
def create_run(body: GoalIn, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    proposal = runner.propose(db, user, body.goal)
    plan = proposal["plan"]
    row = models.AgentRun(user_id=user["id"], goal=body.goal.strip(), status="awaiting_approval" if plan else "completed", route=proposal["route"], plan=plan,
                          planned_by=proposal["planned_by"], requires_approval=any(s["requires_approval"] and s["allowed"] for s in plan),
                          answer=None if plan else runner.GREETING, steps=[], validation=None)
    db.add(row)
    db.flush()
    audit.record(db, user, "agent.plan", "agent_run", row.id, {"goal": row.goal[:200], "tools": [s["tool"] for s in plan], "planned_by": row.planned_by})
    db.commit()
    db.refresh(row)
    return _out(row)


@router.get("/runs")
def list_runs(scope: str = Query(default="mine", pattern="^(mine|all)$"), limit: int = Query(default=30, ge=1, le=100), user: dict = Depends(get_current_user),
              db: Session = Depends(get_db)):
    q = db.query(models.AgentRun)
    if not (scope == "all" and user["role"] == "admin"):
        q = q.filter(models.AgentRun.user_id == user["id"])
    rows = q.order_by(models.AgentRun.id.desc()).limit(limit).all()
    return [{k: v for k, v in _out(r).items() if k not in ("steps", "plan", "route", "validation")} | {"tools": [s.get("tool") for s in (r.plan or [])]} for r in rows]


@router.get("/runs/{run_id}")
def get_run(run_id: int = Depends(run_id_path), user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    return _out(_visible(db, user, run_id))


@router.post("/runs/{run_id}/reject")
def reject_run(run_id: int = Depends(run_id_path), user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    changed = (db.query(models.AgentRun).filter(models.AgentRun.id == run_id, models.AgentRun.user_id == user["id"], models.AgentRun.status == "awaiting_approval")
               .update({"status": "rejected"}, synchronize_session=False))
    if not changed:
        raise HTTPException(status_code=409, detail="Only your own plans that are still waiting for approval can be rejected.")
    audit.record(db, user, "agent.rejected", "agent_run", run_id)
    db.commit()
    return _out(_visible(db, user, run_id))


@router.get("/runs/{run_id}/report", response_class=PlainTextResponse)
def run_report(run_id: int = Depends(run_id_path), user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    run = _out(_visible(db, user, run_id))
    if run["status"] not in ("completed", "failed"):
        raise HTTPException(status_code=409, detail="The report is available once the run has finished.")
    return PlainTextResponse(runner.report_markdown(run), media_type="text/markdown", headers={"Content-Disposition": f'attachment; filename="carebridge-agent-run-{run_id}.md"'})


def _stream(user: dict, run_id: int, goal: str, plan: list[dict], create_proposals: bool) -> Iterator[str]:
    db = SessionLocal()   # own session: the request-scoped one is not available for the life of the stream
    finished = False
    try:
        yield sse("run", {"id": run_id, "status": "running", "total_steps": len(plan)})
        result = None
        for event, data in runner.execute(db, user, goal, plan, create_proposals):
            if event == "result":
                result = data
            else:
                yield sse(event, data)
        row = db.get(models.AgentRun, run_id)
        row.status, row.steps, row.answer, row.validation, row.duration_ms = result["status"], result["steps"], result["answer"], result["validation"], result["duration_ms"]
        audit.record(db, user, "agent.completed", "agent_run", run_id, {"status": result["status"], "tools": [s["tool"] for s in result["steps"]],
                     "proposals": len(result["proposals"]), "duration_ms": result["duration_ms"]})
        if result["proposals"]:
            audit.record(db, user, "agent.proposals_created", "agent_run", run_id, {"count": len(result["proposals"]), "types": sorted({p.get("type") for p in result["proposals"]})})
        db.commit()
        finished = True
        yield sse("answer", {"text": result["answer"], "validation": result["validation"], "proposals": result["proposals"], "citations": result["citations"]})
        yield sse("done", {"id": run_id, "status": result["status"], "duration_ms": result["duration_ms"]})
    except GeneratorExit:
        raise
    except Exception:
        db.rollback()
        logger.exception("agent run %s failed", run_id)
        yield sse("error", {"message": "The run stopped because of an unexpected error. Nothing was marked as completed."})
    finally:
        try:
            if not finished:   # failed or the browser disconnected: never leave a run showing "running"
                db.rollback()
                row = db.get(models.AgentRun, run_id)
                if row is not None and row.status == "running":
                    row.status, row.error = "failed", "The run was interrupted before it finished."
                    audit.record(db, user, "agent.failed", "agent_run", run_id)
                    db.commit()
        except Exception:
            db.rollback()
            logger.exception("agent run %s: could not record the failure", run_id)
        finally:
            with _guard:
                _running.discard(run_id)
            db.close()


@router.post("/runs/{run_id}/approve")
def approve_run(body: ApproveIn, run_id: int = Depends(run_id_path), user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.query(models.AgentRun).filter(models.AgentRun.id == run_id, models.AgentRun.user_id == user["id"]).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Run not found")
    create_proposals = bool(body.create_proposals and user["role"] == "admin")
    # compare-and-set: two clicks (or two tabs) cannot both start the same plan
    changed = (db.query(models.AgentRun).filter(models.AgentRun.id == run_id, models.AgentRun.status == "awaiting_approval")
               .update({"status": "running", "create_proposals": create_proposals}, synchronize_session=False))
    if not changed:
        db.rollback()
        raise HTTPException(status_code=409, detail="This plan is not waiting for approval (it may already have run or been rejected).")
    audit.record(db, user, "agent.approved", "agent_run", run_id, {"create_proposals": create_proposals, "tools": [s.get("tool") for s in (row.plan or [])]})
    db.commit()
    with _guard:
        _running.add(run_id)
    return StreamingResponse(_stream(dict(user), run_id, row.goal, list(row.plan or []), create_proposals), media_type="text/event-stream", headers=SSE_HEADERS)
