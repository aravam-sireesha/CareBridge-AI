"""Start the API with a lightweight offline embedder, for automated end-to-end tests only.

The real assistant uses the sentence-transformers model. This launcher swaps in a tiny
hash-based embedder so tests do not need to download the model.
    python scripts/run_test_server.py 8765
"""
import hashlib
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import uvicorn  # noqa: E402

from app.routers import assistant as assistant_router  # noqa: E402
from app.services import embeddings, rag  # noqa: E402


def fake_embed(text: str) -> list[float]:
    vec = [0.0] * 128
    for word in text.lower().split():
        word = word.strip(".,:;!?'\"()")
        vec[int(hashlib.md5(word.encode()).hexdigest(), 16) % 128] += 1.0
    return vec


embeddings.embed_text = fake_embed
rag.embed_text = fake_embed
assistant_router.embed_text = fake_embed

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=int(sys.argv[1]) if len(sys.argv) > 1 else 8765)
