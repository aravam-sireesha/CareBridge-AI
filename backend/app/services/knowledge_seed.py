"""Load (or refresh) the default CareBridge knowledge base. Safe to run repeatedly."""
from sqlalchemy.orm import Session

from ..knowledge.default_kb import ENTRIES, with_keywords
from ..models import KnowledgeBase
from . import embeddings


def load_defaults(db: Session, embed: bool = True) -> dict:
    existing = {e.title: e for e in db.query(KnowledgeBase).filter(KnowledgeBase.organization_id.is_(None)).all()}
    added = updated = 0
    for title, source, content in ENTRIES:
        stored = with_keywords(title, content)
        row = existing.get(title)
        if row is None:
            db.add(KnowledgeBase(title=title, content=stored, source=source, organization_id=None))
            added += 1
        elif row.content != stored or row.source != source:
            row.content, row.source, row.embedding, row.embedding_model = stored, source, None, None
            updated += 1
    db.commit()
    embedded, dense_error = 0, None
    if embed:
        try:
            embedded = embeddings.embed_missing_entries(db)
        except Exception as exc:  # no sentence-transformers / no model files: keyword + n-gram retrieval still works
            db.rollback()
            dense_error = str(exc)[:200]
    total_embedded = db.query(KnowledgeBase).filter(KnowledgeBase.embedding.isnot(None)).count()
    return {"added": added, "updated": updated, "total": len(ENTRIES), "embedded_now": embedded,
            "embedded_total": total_embedded, "dense_available": total_embedded > 0, "dense_error": dense_error}
