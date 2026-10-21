import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from app.database import SessionLocal
from app.services.embeddings import embed_missing_entries


def main() -> None:
    db = SessionLocal()
    try:
        count = embed_missing_entries(db)
        print(f"Embedded {count} knowledge_base entries")
    finally:
        db.close()


if __name__ == "__main__":
    main()