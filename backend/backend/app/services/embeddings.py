from sqlalchemy.orm import Session

from ..models import KnowledgeBase

MODEL_NAME = "all-MiniLM-L6-v2"
_model = None


def get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer(MODEL_NAME)
    return _model


def embed_text(text: str) -> list[float]:
    return get_model().encode(text).tolist()


def embed_missing_entries(db: Session) -> int:
    """Embed and persist every knowledge-base row that has no vector yet."""
    rows = db.query(KnowledgeBase).filter(KnowledgeBase.embedding.is_(None)).all()
    for row in rows:
        text = f"{row.title or ''}. {row.content or ''}"
        row.embedding = embed_text(text)
        row.embedding_model = MODEL_NAME
    if rows:
        db.commit()
    return len(rows)