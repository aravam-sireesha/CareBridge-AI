import logging
import os
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, require_admin
from app import models, schemas
from app.services import audit, embeddings
from app.services.embeddings import embed_text
from app.services import knowledge_seed, live_assistant, live_retrieval, rag, rag_hybrid

router = APIRouter(prefix="/assistant", tags=["assistant"])
logger = logging.getLogger(__name__)


MIN_KB_SCORE_WITH_LIVE = 0.3
LOW_CONFIDENCE_MESSAGE = (
    "I am not confident that the knowledge base answers this question, so I will not guess. The closest passages are "
    "listed below. Try rephrasing with specific words from the topic, or ask an administrator to add guidance on it."
)


def _retrieve_safely(db: Session, question: str, user: dict, organization_id, has_live: bool):
    """Knowledge-base retrieval. If the embedding model is down but live data can answer, carry on."""
    try:
        return rag.retrieve(
            db,
            question,
            top_k=3,
            organization_id=organization_id,
            global_only=user["role"] != "admin" and (
                user["role"] != "organization" or organization_id is None
            ),
        ), None
    except Exception as exc:  # embedding model missing / cannot load
        logger.exception("Assistant retrieval failed")
        if has_live:
            return [], "Policy search is unavailable right now; this answer uses live database data only."
        raise HTTPException(
            status_code=503,
            detail="The embedding model is unavailable on the server (sentence-transformers). "
            "Check the backend terminal for details.",
        ) from exc


@router.post("/ask")
def ask(
    body: schemas.AssistantAsk,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not body.question or not body.question.strip():
        raise HTTPException(422, "question cannot be empty")

    question = body.question.strip()
    organization_id = user.get("organization_id")
    live_allowed = user["role"] != "volunteer"

    # 1) understand the question: intents, organizations / donors / categories it names, follow-ups
    effective = question
    follow_up_of = None
    entities = live_retrieval.detect_entities(db, user, question) if live_allowed else {"organizations": [], "donors": [], "categories": []}
    intents = live_assistant.classify(question) if live_allowed else []
    if live_allowed and not intents:
        previous = live_retrieval.resolve_follow_up(db, user, question)
        if previous:
            follow_up_of, effective = previous, f"{previous} {question}"
            entities = live_retrieval.detect_entities(db, user, effective)
            intents = live_assistant.classify(effective)
    if live_retrieval.has_entities(entities) and not intents:
        intents = ["health", "selection"]
        if entities["donors"] and not entities["organizations"] and not entities["categories"]:
            intents = ["selection"]
    if entities["donors"]:
        intents = sorted(set(intents) | {"selection"})

    # 2) live analysis + live record retrieval (both scoped to the asker's role)
    analysis = live_assistant.build_analysis(db, user, intents, focus=entities) if intents else None
    has_analysis = bool(analysis and live_assistant.has_content(analysis))
    records = live_retrieval.retrieve_records(db, user, effective) if live_allowed else []
    if not has_analysis:
        records = [r for r in records if r["score"] >= 0.3]  # stand-alone record answers need a clear match
    has_live = has_analysis or bool(records)

    # 3) policy knowledge base
    results, notice = _retrieve_safely(db, effective, user, organization_id, has_live)
    if has_live:
        results = [r for r in results if r["score"] >= MIN_KB_SCORE_WITH_LIVE]

    # 4) answer
    live_context = None
    if has_analysis:
        live_context = live_assistant.live_context_text(analysis)
    elif records:
        live_context = live_assistant.compose_records_answer(records)
    if live_context and has_analysis and records:
        live_context += "\nLIVE RECORDS: " + " | ".join(r["content"] for r in records[:4])
    kb_answerable = bool(results and results[0].get("answerable", True))
    if live_context:
        answer, answer_mode = rag.generate_grounded_answer(question, results, live_context)
    elif results and not kb_answerable:
        # abstain instead of guessing: show the closest passages and say the match is weak
        answer, answer_mode = LOW_CONFIDENCE_MESSAGE, "low_confidence"
    else:  # unchanged call for policy-only questions
        answer, answer_mode = rag.generate_grounded_answer(question, results)
    if notice:
        answer = f"{answer}\n\n{notice}"

    live_sources = analysis["sources"] if has_analysis else []
    history = models.AssistantMessage(
        user_id=user["id"],
        organization_id=organization_id,
        question=question,
        answer=answer,
        sources=results + [{**s, "id": None, "score": 1.0, "live": True} for s in live_sources] + records,
    )
    db.add(history)
    db.commit()
    db.refresh(history)

    return {
        "conversation_id": history.id,
        "question": body.question,
        "answer": answer,
        "matches": results,
        "confidence": ({"value": results[0].get("confidence", results[0]["score"]), "label": results[0].get("label"),
                        "answerable": kb_answerable, "threshold": rag_hybrid.threshold()} if results else None),
        "records": records,
        "live_sources": live_sources,
        "analysis": analysis if has_analysis else None,
        "follow_ups": live_assistant.follow_ups(analysis) if has_analysis else [],
        "focus": live_retrieval.focus_names(entities),
        "follow_up_of": follow_up_of,
        "answer_mode": answer_mode,
        "note": "Suggestions only. Review the cited source material and use administrator judgment.",
    }


@router.get("/insights")
def insights(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """Real-time, role-scoped analysis for the assistant's live panel. Recomputed on every call."""
    if user["role"] == "volunteer":
        raise HTTPException(status_code=403, detail="Live insights are not available for volunteer accounts")
    return live_assistant.build_analysis(db, user, ["health", "selection", "snapshot"])


@router.get("/status")
def assistant_status(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    total = db.query(func.count(models.KnowledgeBase.id)).scalar() or 0
    embedded = (
        db.query(func.count(models.KnowledgeBase.id)).filter(models.KnowledgeBase.embedding.isnot(None)).scalar() or 0
    )
    return {
        "knowledge_entries": total,
        "embedded_entries": embedded,
        "needs_indexing": max(total - embedded, 0),
        "guide_entries_available": len(knowledge_seed.ENTRIES),
        "guide_entries_loaded": db.query(func.count(models.KnowledgeBase.id)).filter(
            models.KnowledgeBase.organization_id.is_(None), models.KnowledgeBase.title.in_([e[0] for e in knowledge_seed.ENTRIES])).scalar() or 0,
        "dense_vectors": embedded > 0,
        "mode": "grounded_generation" if os.getenv("OPENAI_API_KEY") else "retrieval_only",
    }


@router.post("/reindex")
def reindex(admin: dict = Depends(require_admin), db: Session = Depends(get_db)):
    """Embed every knowledge-base row that was added without a vector (e.g. by SQL)."""
    try:
        count = embeddings.embed_missing_entries(db)
    except Exception as exc:
        db.rollback()
        logger.exception("Knowledge reindex failed")
        raise HTTPException(status_code=503, detail="The embedding model is unavailable on the server") from exc
    return {"embedded": count}


@router.get("/history")
def history(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    query = db.query(models.AssistantMessage)
    if user["role"] == "admin":
        pass
    elif user.get("organization_id") is not None:
        query = query.filter(models.AssistantMessage.organization_id == user["organization_id"])
    else:
        query = query.filter(models.AssistantMessage.user_id == user["id"])
    rows = query.order_by(models.AssistantMessage.created_at.desc()).limit(50).all()
    return [
        {
            "id": row.id,
            "question": row.question,
            "answer": row.answer,
            "matches": row.sources,
            "created_at": row.created_at,
        }
        for row in rows
    ]


@router.get("/knowledge", response_model=List[schemas.KnowledgeEntryOut])
def list_knowledge(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    query = db.query(models.KnowledgeBase)
    if user["role"] != "admin":
        organization_id = user.get("organization_id")
        if organization_id is None:
            raise HTTPException(status_code=403, detail="Knowledge base access requires an organization")
        query = query.filter(
            (models.KnowledgeBase.organization_id.is_(None))
            | (models.KnowledgeBase.organization_id == organization_id)
        )
    out = []
    for e in query.order_by(models.KnowledgeBase.updated_at.desc()).all():
        item = schemas.KnowledgeEntryOut.model_validate(e)
        item.content = rag_hybrid.split_hidden(e.content)[0]   # retrieval-only phrasings stay hidden
        out.append(item)
    return out


@router.post("/knowledge/seed-defaults")
def seed_default_knowledge(admin: dict = Depends(require_admin), db: Session = Depends(get_db)):
    """Load or refresh the built-in CareBridge guide (idempotent). Builds dense vectors too when the model is available."""
    result = knowledge_seed.load_defaults(db)
    audit.record_now(db, admin, "knowledge.defaults_loaded", detail={k: v for k, v in result.items() if k != "dense_error"})
    return result


@router.get("/gaps")
def knowledge_gaps(limit: int = Query(default=30, ge=1, le=100), admin: dict = Depends(require_admin), db: Session = Depends(get_db)):
    """Questions the assistant could not answer confidently: the to-do list for improving the knowledge base."""
    gaps: dict[str, dict] = {}
    for row in db.query(models.AssistantMessage).order_by(models.AssistantMessage.id.desc()).limit(500).all():
        sources = row.sources or []
        if any(s.get("live") for s in sources):
            continue  # answered from live data
        best = max((s.get("score") or 0 for s in sources), default=0.0)
        if best >= rag_hybrid.threshold():
            continue
        key = " ".join((row.question or "").lower().split())
        g = gaps.setdefault(key, {"question": row.question, "times": 0, "best_confidence": 0.0, "last_asked": row.created_at})
        g["times"] += 1
        g["best_confidence"] = round(max(g["best_confidence"], float(best)), 3)
    return sorted(gaps.values(), key=lambda g: (-g["times"], g["best_confidence"]))[:limit]


@router.post("/knowledge", response_model=schemas.KnowledgeEntryOut, status_code=status.HTTP_201_CREATED)
def create_knowledge(
    body: schemas.KnowledgeEntryCreate,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user["role"] not in ("admin", "organization"):
        raise HTTPException(status_code=403, detail="Only organizations and administrators can add knowledge")
    entry = models.KnowledgeBase(
        title=body.title,
        content=body.content,
        source=body.source,
        organization_id=user.get("organization_id"),
    )
    try:
        entry.embedding = embed_text(f"{entry.title}. {entry.content}")
        entry.embedding_model = "all-MiniLM-L6-v2"
    except Exception:  # no vector model: the entry is still found by keyword and n-gram retrieval
        logger.warning("Knowledge entry saved without a vector (embedding model unavailable)")
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry