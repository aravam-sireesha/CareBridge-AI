"""AI help for the need form. It only returns SUGGESTIONS: nothing is saved, and the normal need endpoint still validates what the person submits."""
from __future__ import annotations

import logging
import threading
import time
from collections import deque

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..dependencies import get_current_user
from ..services import llm, llm_usage, need_assist

router = APIRouter(prefix="/need-assist", tags=["need-assist"])
logger = logging.getLogger(__name__)
_hits: dict[int, deque] = {}
_guard = threading.Lock()
LIMIT, WINDOW = 15, 60.0


class AssistIn(BaseModel):
    text: str = Field(min_length=10, max_length=2000)


def _limited(user_id: int) -> bool:
    now = time.monotonic()
    with _guard:
        q = _hits.setdefault(user_id, deque())
        while q and now - q[0] > WINDOW:
            q.popleft()
        if len(q) >= LIMIT:
            return True
        q.append(now)
        return False


@router.post("")
def suggest(body: AssistIn, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    if user["role"] not in ("admin", "organization"):
        raise HTTPException(status_code=403, detail="Only administrators and organizations can use the need assistant.")
    if _limited(user["id"]):
        raise HTTPException(status_code=429, detail="Please wait a moment before asking for more suggestions.")
    q = db.query(models.Need.category).distinct()
    if user["role"] == "organization" and user.get("organization_id"):
        q = q.filter(models.Need.org_id == user["organization_id"])
    known = [c for (c,) in q.limit(50).all() if c]
    result = need_assist.rule_suggestions(body.text, known)
    source, notice = "rules", "No language model is connected, so these suggestions come from simple keyword rules."
    cfg = llm.config()
    if cfg is not None and llm_usage.limit_reached(db):
        notice = "The daily limit for language model requests has been reached, so these suggestions come from simple keyword rules."
    elif cfg is not None:
        messages = [{"role": "system", "content": need_assist.SYSTEM_PROMPT}, {"role": "user", "content": need_assist.user_prompt(body.text, known)}]
        started = time.perf_counter()
        error, raw = None, ""
        try:
            raw = "".join(llm.stream_chat(cfg, messages, model=cfg.fast_model, max_tokens=450, temperature=0.1))
        except llm.LLMError as exc:
            error = str(exc)
        llm_usage.record(db, user_id=user["id"], kind="chat", model=cfg.fast_model, prompt_chars=sum(len(m["content"]) for m in messages), completion_chars=len(raw),
                         latency_ms=int((time.perf_counter() - started) * 1000), ok=error is None, error=error)
        parsed = need_assist.parse_model_json(raw) if error is None else None
        if parsed:
            for key in ("category", "urgency", "title", "description"):
                if parsed.get(key):
                    result[key] = parsed[key]
            result["missing"] = parsed["missing"] or result["missing"]
            source, notice = "model", None
        else:
            notice = (f"{error} " if error else "The language model's reply could not be used. ") + "These suggestions come from simple keyword rules."
    return {"suggestions": result, "source": source, "notice": notice}
