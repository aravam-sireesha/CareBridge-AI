"""Server-Sent Events helpers (pure functions: no web framework needed, so they are unit-testable on their own)."""
from __future__ import annotations

import json
import re
from typing import Any, Iterator

# no-transform stops proxies from compressing (and therefore buffering) the stream; X-Accel-Buffering disables nginx buffering.
SSE_HEADERS = {"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no", "Connection": "keep-alive"}


def sse(event: str, data: Any) -> str:
    """One SSE frame. `data` is JSON on a single line, so newlines inside text can never break the framing."""
    return f"event: {event}\ndata: {json.dumps(data, default=str, ensure_ascii=False)}\n\n"


def comment(text: str = "keep-alive") -> str:
    """A comment frame: ignored by clients, keeps idle connections open through proxies."""
    return f": {text}\n\n"


def chunk_text(text: str, words: int = 3) -> Iterator[str]:
    """Split finished text into small pieces (whitespace preserved) so the client can append them as they arrive."""
    pieces = re.findall(r"\S+\s*|\s+", text or "")
    for i in range(0, len(pieces), max(1, words)):
        yield "".join(pieces[i:i + words])
