"""Load the default CareBridge knowledge base (about 57 entries) into the database.

    python scripts/seed_knowledge.py            # also builds dense vectors if sentence-transformers is installed
    python scripts/seed_knowledge.py --no-embed # keyword + n-gram retrieval only
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal  # noqa: E402
from app.services.knowledge_seed import load_defaults  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-embed", action="store_true")
    args = ap.parse_args()
    with SessionLocal() as db:
        print(json.dumps(load_defaults(db, embed=not args.no_embed), indent=2))
