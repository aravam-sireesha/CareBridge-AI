"""Measure how fast the assistant answers: the old blocking endpoint versus the new streaming one.

    python scripts/bench_chat.py --email you@example.org --password "..." [--base http://127.0.0.1:8000] [--runs 5]

For each question it records, per endpoint:
  /assistant/ask   total time until the whole answer arrived (the user sees nothing before that)
  /chat/stream     time to the first byte, time to the first answer text ("first words"), and total time
and prints p50 / p95 over the runs. Run it before and after changes, on the same machine and data, and keep the output.
Streaming improves how soon the user sees text; it does not shorten the total generation time. Both are reported separately."""
from __future__ import annotations

import argparse
import json
import statistics
import time

import httpx

QUESTIONS = {
    "simple conversational": "What is the volunteer background check policy?",
    "needs live data": "Which needs are most urgent right now?",
    "follow-up": "Which donors fit them best?",
}


def pct(values: list[float], p: float) -> float:
    if not values:
        return float("nan")
    values = sorted(values)
    return values[min(len(values) - 1, int(round(p * (len(values) - 1))))]


def time_ask(client: httpx.Client, q: str) -> float:
    t0 = time.perf_counter()
    r = client.post("/assistant/ask", json={"question": q})
    r.raise_for_status()
    return (time.perf_counter() - t0) * 1000


def time_stream(client: httpx.Client, q: str) -> dict:
    t0 = time.perf_counter()
    first_byte = first_text = None
    mode = None
    with client.stream("POST", "/chat/stream", json={"message": q}) as r:
        r.raise_for_status()
        event = None
        for line in r.iter_lines():
            if first_byte is None:
                first_byte = (time.perf_counter() - t0) * 1000
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                if event == "token" and first_text is None:
                    first_text = (time.perf_counter() - t0) * 1000
                if event == "done":
                    mode = json.loads(line[5:]).get("mode")
    return {"first_byte": first_byte, "first_text": first_text, "total": (time.perf_counter() - t0) * 1000, "mode": mode}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--email", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--runs", type=int, default=5)
    a = ap.parse_args()
    with httpx.Client(base_url=a.base, timeout=120) as c:
        r = c.post("/auth/login", json={"email": a.email, "password": a.password})
        r.raise_for_status()
        c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
        print(f"{'question':24} {'endpoint':14} {'first byte':>12} {'first words':>12} {'total p50':>10} {'total p95':>10}   (ms, {a.runs} runs)")
        for name, q in QUESTIONS.items():
            ask = [time_ask(c, q) for _ in range(a.runs)]
            st = [time_stream(c, q) for _ in range(a.runs)]
            print(f"{name:24} {'/assistant/ask':14} {'-':>12} {'-':>12} {statistics.median(ask):10.0f} {pct(ask, .95):10.0f}")
            fb, ft, tt = ([s[k] for s in st if s[k] is not None] for k in ("first_byte", "first_text", "total"))
            print(f"{'':24} {'/chat/stream':14} {statistics.median(fb):12.0f} {statistics.median(ft):12.0f} {statistics.median(tt):10.0f} {pct(tt, .95):10.0f}   mode={st[-1]['mode']}")


if __name__ == "__main__":
    main()
