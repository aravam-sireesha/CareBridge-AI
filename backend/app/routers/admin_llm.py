"""Administrator view of the language-model connection. Credentials come from the server environment only:
this API reports whether a key is set (masked to its last four characters), never the key itself, and nothing here can change it.
To rotate a key: update the environment variable (or secret manager entry) and restart the backend, then press "Test connection"."""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import require_admin
from ..services import audit, embeddings, llm, llm_usage

router = APIRouter(prefix="/admin/llm", tags=["admin-llm"])


@router.get("/status")
def status(admin: dict = Depends(require_admin), db: Session = Depends(get_db)):
    cfg = llm.config()
    return {
        "configured": cfg is not None,
        "provider_host": llm.host_of(cfg.base_url) if cfg else None,
        "model": cfg.model if cfg else None,
        "fast_model": cfg.fast_model if cfg else None,
        "api_key": llm.mask_key(cfg.api_key) if cfg else "",
        "key_required": bool(cfg and cfg.api_key != "local"),
        "timeout_seconds": cfg.timeout if cfg else None,
        "max_retries": llm.max_retries(),
        "daily_request_limit": llm.daily_limit() or None,
        "embedding_model": f"{embeddings.MODEL_NAME} (runs locally, no API key)",
        "usage": llm_usage.summary(db),
        "cost_note": "Estimated cost is not shown: it needs per-token prices and usage counts the provider does not always return. Request counts, failures and latency are real.",
    }


@router.post("/test")
def test_connection(admin: dict = Depends(require_admin), db: Session = Depends(get_db)):
    """Send one tiny request to the configured model and report the real outcome."""
    cfg = llm.config()
    if cfg is None:
        return {"ok": False, "message": "No language model is configured. Set LLM_API_KEY (or LLM_BASE_URL for a local server) and restart the backend."}
    started = time.perf_counter()
    try:
        text = llm.complete(cfg, [{"role": "user", "content": "Reply with the single word: ok"}], model=cfg.model, max_tokens=8)
        ok, error = True, None
    except llm.LLMError as exc:
        text, ok, error = "", False, str(exc)
    latency = int((time.perf_counter() - started) * 1000)
    llm_usage.record(db, user_id=admin["id"], kind="test", model=cfg.model, prompt_chars=40, completion_chars=len(text), latency_ms=latency, ok=ok, error=error)
    audit.record_now(db, admin, "llm.test", "llm", None, {"ok": ok, "model": cfg.model, "latency_ms": latency})
    return {"ok": ok, "model": cfg.model, "latency_ms": latency, "message": "The model answered." if ok else error}
