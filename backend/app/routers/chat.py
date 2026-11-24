"""Chat threads with a streaming assistant (Server-Sent Events).

POST /chat/stream sends events as the answer is produced:
    conversation  {conversation_id, request_id, title}         first byte, before any retrieval
    status        {stage, label}                               only for questions that really search data ("Checking live data and knowledge")
    sources       {knowledge, live, records, focus, ...}       evidence, only for CareBridge questions, sent before the answer text
    token         {t}                                          answer text as it is generated
    done          {message_id, route, mode, model, validation, follow_ups, timings}
    error         {message, code}
Messages are routed first (chat_intent): small talk is answered directly, general questions go straight to the language model, and
CareBridge questions are answered from live records and approved knowledge.
Conversations are private to their owner. A conversation accepts one message at a time, and each user is rate limited."""
from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import deque
from typing import Iterator

from fastapi import APIRouter, Depends, HTTPException, Path, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from .. import models
from ..database import SessionLocal, get_db
from ..dependencies import get_current_user
from ..services import audit, chat_engine, chat_intent, llm, llm_usage
from ..services.ids import parse_id
from ..services.sse import SSE_HEADERS, chunk_text, sse

router = APIRouter(prefix="/chat", tags=["chat"])
logger = logging.getLogger(__name__)

RATE_LIMIT, RATE_WINDOW = 30, 60.0       # messages per user per minute
MAX_CONVERSATIONS = 100
_hits: dict[int, deque] = {}
_inflight: set[tuple[int, int]] = set()
_guard = threading.Lock()


def conversation_id_path(conversation_id: str = Path(...)) -> int:
    return parse_id(conversation_id, "Conversation id")


def message_id_path(message_id: str = Path(...)) -> int:
    return parse_id(message_id, "Message id")


class StreamIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: int | None = None
    regenerate: bool = False   # answer the conversation's last question again instead of adding a new one
    language: str | None = Field(default=None, pattern="^[a-z]{2}$")   # reply language (see chat_engine.LANGUAGES); anything else is ignored


class RenameIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class FeedbackIn(BaseModel):
    value: str | None = Field(default=None, pattern="^(up|down)$")


def reset_limits() -> None:
    with _guard:
        _hits.clear()
        _inflight.clear()


def _rate_limited(user_id: int) -> bool:
    now = time.monotonic()
    with _guard:
        q = _hits.setdefault(user_id, deque())
        while q and now - q[0] > RATE_WINDOW:
            q.popleft()
        if len(q) >= RATE_LIMIT:
            return True
        q.append(now)
        return False


def _own_conversation(db: Session, user: dict, conversation_id: int) -> models.ChatConversation:
    row = db.query(models.ChatConversation).filter(models.ChatConversation.id == conversation_id, models.ChatConversation.user_id == user["id"]).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Conversation not found")   # same answer for "missing" and "someone else's"
    return row


def _message_out(m: models.ChatMessage) -> dict:
    return {"id": m.id, "role": m.role, "content": m.content, "sources": m.sources, "meta": m.meta, "feedback": m.feedback, "created_at": m.created_at}


def _title_from(text: str) -> str:
    t = " ".join(text.split())
    return t if len(t) <= 60 else t[:57].rstrip() + "…"


@router.get("/status")
def chat_status(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    cfg = llm.config()
    total = db.query(func.count(models.KnowledgeBase.id)).scalar() or 0
    return {"llm_configured": cfg is not None, "model": cfg.model if cfg else None, "fast_model": cfg.fast_model if cfg else None,
            "mode": "llm_streaming" if cfg else "retrieval_and_live_analysis", "knowledge_entries": total}


@router.get("/conversations")
def list_conversations(q: str | None = None, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    query = db.query(models.ChatConversation).filter(models.ChatConversation.user_id == user["id"])
    term = (q or "").strip()[:100]
    if term:
        like = "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        in_messages = db.query(models.ChatMessage.id).filter(models.ChatMessage.conversation_id == models.ChatConversation.id, models.ChatMessage.content.ilike(like, escape="\\")).exists()
        query = query.filter(or_(models.ChatConversation.title.ilike(like, escape="\\"), in_messages))
    rows = query.order_by(models.ChatConversation.updated_at.desc(), models.ChatConversation.id.desc()).limit(MAX_CONVERSATIONS).all()
    return [{"id": r.id, "title": r.title, "updated_at": r.updated_at, "created_at": r.created_at} for r in rows]


@router.post("/conversations", status_code=status.HTTP_201_CREATED)
def create_conversation(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    row = models.ChatConversation(user_id=user["id"], title="New chat")
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "title": row.title, "updated_at": row.updated_at, "created_at": row.created_at}


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: int = Depends(conversation_id_path), user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    conv = _own_conversation(db, user, conversation_id)
    msgs = db.query(models.ChatMessage).filter(models.ChatMessage.conversation_id == conv.id).order_by(models.ChatMessage.id).all()
    return {"id": conv.id, "title": conv.title, "messages": [_message_out(m) for m in msgs]}


@router.patch("/conversations/{conversation_id}")
def rename_conversation(body: RenameIn, conversation_id: int = Depends(conversation_id_path), user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    conv = _own_conversation(db, user, conversation_id)
    conv.title = body.title.strip()
    db.commit()
    return {"id": conv.id, "title": conv.title}


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(conversation_id: int = Depends(conversation_id_path), user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    conv = _own_conversation(db, user, conversation_id)
    db.query(models.ChatMessage).filter(models.ChatMessage.conversation_id == conv.id).delete(synchronize_session=False)
    db.delete(conv)
    db.commit()


@router.post("/messages/{message_id}/feedback")
def message_feedback(body: FeedbackIn, message_id: int = Depends(message_id_path), user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    msg = (db.query(models.ChatMessage).join(models.ChatConversation, models.ChatConversation.id == models.ChatMessage.conversation_id)
           .filter(models.ChatMessage.id == message_id, models.ChatConversation.user_id == user["id"], models.ChatMessage.role == "assistant").first())
    if msg is None:
        raise HTTPException(status_code=404, detail="Message not found")
    msg.feedback = body.value
    db.commit()
    return {"id": msg.id, "feedback": msg.feedback}


def _llm_call(db: Session, user: dict, cfg: llm.LLMConfig, messages: list[dict], model: str, *, max_tokens: int, timings: dict, ms, parts: list[str]) -> Iterator[str]:
    """Stream one model answer as SSE token frames and log the request. Raises llm.LLMError if it fails (frames already sent stay sent)."""
    started = time.perf_counter()
    prompt_chars = sum(len(m["content"]) for m in messages)
    error = None
    try:
        for piece in llm.stream_chat(cfg, messages, model=model, max_tokens=max_tokens):
            timings.setdefault("first_token_ms", ms())
            parts.append(piece)
            yield sse("token", {"t": piece})
    except llm.LLMError as exc:
        error = str(exc)
        raise
    finally:
        llm_usage.record(db, user_id=user["id"], kind="chat", model=model, prompt_chars=prompt_chars, completion_chars=sum(len(p) for p in parts),
                         latency_ms=int((time.perf_counter() - started) * 1000), ok=error is None, error=error)


def _record_gap(db: Session, user: dict, question: str, answer: str) -> None:
    """A CareBridge question the knowledge base could not answer goes to the administrators' knowledge-gap list (the existing /assistant/gaps)."""
    try:
        db.add(models.AssistantMessage(user_id=user["id"], organization_id=user.get("organization_id"), question=question, answer=answer, sources=[]))
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("could not record a knowledge gap")


def _generate(user: dict, conversation_id: int | None, question: str, request_id: str, regenerate: bool = False, language: str | None = None) -> Iterator[str]:
    """The stream. Runs in a worker thread (Starlette iterates sync generators off the event loop) with its OWN database session,
    because the request-scoped session may already be closed when the first byte is sent."""
    db = SessionLocal()
    t0 = time.perf_counter()
    ms = lambda: int((time.perf_counter() - t0) * 1000)  # noqa: E731
    timings: dict[str, int] = {}
    key = None
    parts: list[str] = []
    finished = False
    try:
        if conversation_id is None:
            conv = models.ChatConversation(user_id=user["id"], title=_title_from(question))
            db.add(conv)
            db.commit()
            db.refresh(conv)
        else:
            conv = _own_conversation(db, user, conversation_id)
            if conv.title == "New chat":
                conv.title = _title_from(question)
        key = (user["id"], conv.id)
        with _guard:
            busy = key in _inflight
            if not busy:
                _inflight.add(key)
        if busy:   # (yield outside the lock: never hold a lock across a yield)
            key = None
            yield sse("error", {"message": "This conversation is already answering a message. Wait for it to finish.", "code": "busy"})
            return
        yield sse("conversation", {"conversation_id": conv.id, "request_id": request_id, "title": conv.title})   # first byte: before any retrieval

        rows = db.query(models.ChatMessage).filter(models.ChatMessage.conversation_id == conv.id).order_by(models.ChatMessage.id).all()
        if regenerate:   # drop the last answer(s) and answer the last question again
            last_user = next((m for m in reversed(rows) if m.role == "user"), None)
            if last_user is None:
                yield sse("error", {"message": "There is no question to answer again.", "code": "request"})
                return
            for m in rows:
                if m.id > last_user.id:
                    db.delete(m)
            question = last_user.content
            rows = [m for m in rows if m.id < last_user.id]
        else:
            db.add(models.ChatMessage(conversation_id=conv.id, role="user", content=question))
        conv.updated_at = func.now()
        db.commit()
        history = [{"role": m.role, "content": m.content} for m in rows if m.content][-chat_engine.HISTORY_MESSAGES:]
        previous_route = next(((m.meta or {}).get("route") for m in reversed(rows) if m.role == "assistant" and m.meta), None)

        cfg = llm.config()
        route = chat_intent.classify(question, previous_route)
        mode, model_used, validation, notice = None, None, {}, None
        ctx = chat_engine.empty_context(question)
        src = None
        limited = cfg is not None and llm_usage.limit_reached(db)
        if limited:
            cfg, notice = None, "The daily limit for language model requests has been reached, so this answer does not use the model."

        if route == "smalltalk":
            text, mode = chat_intent.smalltalk_reply(question, user["role"], cfg is not None), "smalltalk"
            for piece in chunk_text(text):
                timings.setdefault("first_token_ms", ms())
                parts.append(piece)
                yield sse("token", {"t": piece})

        elif route == "general":
            if cfg is None:
                text, mode = (chat_engine.LIMIT_REACHED if limited else chat_engine.NO_MODEL_GENERAL), "no_model"
                for piece in chunk_text(text):
                    parts.append(piece)
                    yield sse("token", {"t": piece})
            else:
                model_used = llm.choose_model(cfg, question, False)
                try:
                    yield from _llm_call(db, user, cfg, chat_engine.build_general_messages(question, history, language), model_used, max_tokens=1000, timings=timings, ms=ms, parts=parts)
                    mode = "llm_general"
                except llm.LLMError as exc:
                    logger.warning("chat %s: model failed (%s)", request_id, exc)
                    if parts:
                        validation["interrupted"], mode = True, "llm_partial"
                    else:
                        text, mode, notice = str(exc), "model_error", str(exc)
                        for piece in chunk_text("I couldn't get an answer from the language model. " + text):
                            parts.append(piece)
                            yield sse("token", {"t": piece})

        else:   # carebridge
            yield sse("status", {"stage": "searching", "label": "Checking live data and knowledge"})
            ctx = chat_engine.prepare(db, user, question, history)
            timings["retrieval_ms"] = ms()
            src = chat_engine.sources_payload(ctx)
            notice = notice or ctx["notice"]
            yield sse("sources", {**src, "confidence": chat_engine.confidence_payload(ctx), "notice": ctx["notice"]})
            if cfg is not None and chat_engine.has_evidence(ctx):
                model_used = llm.choose_model(cfg, question, ctx["has_live"])
                try:
                    yield from _llm_call(db, user, cfg, chat_engine.build_messages(ctx, history, language), model_used, max_tokens=700, timings=timings, ms=ms, parts=parts)
                    mode = "llm_grounded" if parts else None
                except llm.LLMError as exc:
                    logger.warning("chat %s: model failed (%s)", request_id, exc)
                    if parts:
                        validation["interrupted"], mode = True, "llm_partial"
                    else:
                        notice = f"{exc} This answer uses retrieval and live analysis only."
            if mode is None:   # no model, nothing to ground on, or the model failed before any text
                text, mode = chat_engine.fallback_answer(ctx)
                model_used = None
                for piece in chunk_text(text):
                    timings.setdefault("first_token_ms", ms())
                    parts.append(piece)
                    yield sse("token", {"t": piece})
            if mode in ("no_sources", "low_confidence"):
                _record_gap(db, user, question, "".join(parts))

        answer = "".join(parts)
        if mode == "llm_grounded":
            validation.update(chat_engine.grounding_check(answer, ctx))
        follow_ups = ctx["follow_ups"] if route == "carebridge" else []
        timings["total_ms"] = ms()
        meta = {"route": route, "mode": mode, "model": model_used, "validation": validation, "timings": timings, "request_id": request_id, "notice": notice,
                "follow_ups": follow_ups, "analysis": ctx["analysis"]}
        assistant_row = models.ChatMessage(conversation_id=conv.id, role="assistant", content=answer, sources=src, meta=meta)
        db.add(assistant_row)
        conv.updated_at = func.now()
        db.commit()
        db.refresh(assistant_row)
        finished = True
        logger.info("chat %s ok route=%s mode=%s model=%s first_token_ms=%s total_ms=%s", request_id, route, mode, model_used, timings.get("first_token_ms"), timings["total_ms"])
        yield sse("done", {"message_id": assistant_row.id, "route": route, "mode": mode, "model": model_used, "validation": validation, "follow_ups": follow_ups,
                           "notice": notice, "analysis": ctx["analysis"], "timings": timings})
    except HTTPException as exc:
        yield sse("error", {"message": str(exc.detail), "code": "not_found" if exc.status_code == 404 else "request"})
    except GeneratorExit:   # the browser went away (cancel / navigation): keep the partial answer, then let the generator close
        raise
    except Exception:
        db.rollback()
        logger.exception("chat %s failed", request_id)
        yield sse("error", {"message": "The assistant hit an unexpected error. Please try again.", "code": "server"})
    finally:
        try:
            if parts and not finished and key is not None:   # interrupted mid-answer: store what the user saw, clearly marked
                db.add(models.ChatMessage(conversation_id=key[1], role="assistant", content="".join(parts), meta={"mode": "interrupted", "validation": {"interrupted": True},
                       "request_id": request_id, "timings": {**timings, "total_ms": ms()}}))
                db.commit()
        except Exception:
            db.rollback()
            logger.exception("chat %s: could not save the partial answer", request_id)
        finally:
            if key is not None:
                with _guard:
                    _inflight.discard(key)
            db.close()


@router.post("/stream")
def stream(body: StreamIn, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    question = body.message.strip()
    if not question:
        raise HTTPException(status_code=422, detail="message cannot be empty")
    if body.conversation_id is not None:
        _own_conversation(db, user, body.conversation_id)   # fail with a normal 404 before the stream starts
    elif (db.query(func.count(models.ChatConversation.id)).filter(models.ChatConversation.user_id == user["id"]).scalar() or 0) >= 500:
        raise HTTPException(status_code=409, detail="Too many saved conversations. Delete some to start a new one.")
    if body.regenerate and body.conversation_id is None:
        raise HTTPException(status_code=422, detail="Choose a conversation to answer again.")
    if _rate_limited(user["id"]):
        raise HTTPException(status_code=429, detail="You are sending messages too quickly. Please wait a moment.")
    request_id = uuid.uuid4().hex[:8]
    audit.record_now(db, user, "chat.message", "chat_conversation", body.conversation_id, {"request_id": request_id, "chars": len(question)})
    return StreamingResponse(_generate(dict(user), body.conversation_id, question, request_id, body.regenerate, body.language), media_type="text/event-stream", headers=SSE_HEADERS)
