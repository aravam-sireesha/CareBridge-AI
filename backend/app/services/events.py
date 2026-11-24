"""Real-time event infrastructure (Server-Sent Events). Server -> client only; clients act through normal HTTP endpoints.

Design rules that matter for a child-welfare platform:

1. **Events are hints, not records.** A payload carries ids, a status and (for live delivery position) a position rounded to
   ~11 m. Anything more is fetched through the normal authorised endpoints. Every event type has an ALLOW-LIST of payload
   fields; anything else is dropped before the event exists, so a careless caller cannot leak an address, phone or name.
2. **Every event names its audience** (users, roles, organizations, donors, volunteers). An event with an empty audience
   reaches nobody; there is no "broadcast to all".
3. **Redis when available, process memory when not.** With REDIS_URL set, events are written to a capped Redis stream (so a
   reconnecting client can replay what it missed using Last-Event-ID) and published on a channel that every worker process
   listens to, which is what makes several workers/containers behave as one. Without Redis a single process works the same
   way, with a small in-memory replay buffer.
4. **Publishing never breaks the request that triggered it.** `publish()` swallows and logs its own failures, and
   `publish_after_commit()` holds events until the database transaction really committed (a rolled-back action emits nothing).

Pure Python except where Redis/SQLAlchemy objects are passed in, so it is unit-tested without a web framework.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional

from . import redis_client

logger = logging.getLogger(__name__)

STREAM_KEY = "cb:events:stream"
CHANNEL = "cb:events:live"
STREAM_MAXLEN = 5000
REPLAY_LIMIT = 200
MEMORY_RING = 500
QUEUE_SIZE = 100
_ID_RE = re.compile(r"^\d{1,16}-\d{1,10}$")

# event type -> the ONLY payload fields it may carry
SCHEMAS: dict[str, frozenset] = {
    "hello": frozenset({"server_time", "replayed"}),
    "system.resync": frozenset({"reason"}),
    "notification": frozenset({"id", "kind", "title", "link"}),
    "delivery.status": frozenset({"task_id", "status", "label"}),
    "delivery.location": frozenset({"task_id", "latitude", "longitude", "accuracy_m", "recorded_at", "status"}),
    "delivery.tracking": frozenset({"task_id", "state"}),           # state: started | paused | resumed | stopped | stale
    "need.decision": frozenset({"need_id", "status"}),
    "donation.committed": frozenset({"need_id", "task_id"}),
    "risk.alert": frozenset({"task_id", "kind", "severity"}),
}
_MAX_STR = 300
CONTROL_TYPES = frozenset({"hello", "system.resync"})


# --------------------------------------------------------------------------- audience
@dataclass(frozen=True)
class Audience:
    user_ids: frozenset = frozenset()
    roles: frozenset = frozenset()
    org_ids: frozenset = frozenset()
    donor_ids: frozenset = frozenset()
    volunteer_ids: frozenset = frozenset()

    def allows(self, principal: dict) -> bool:
        """principal: the current-user dict ({id, role, organization_id, donor_id, volunteer_id, ...})."""
        if principal.get("id") in self.user_ids:
            return True
        if principal.get("role") in self.roles:
            return True
        for attr, bucket in (("organization_id", self.org_ids), ("donor_id", self.donor_ids), ("volunteer_id", self.volunteer_ids)):
            value = principal.get(attr)
            if value is not None and value in bucket:
                return True
        return False

    def is_empty(self) -> bool:
        return not (self.user_ids or self.roles or self.org_ids or self.donor_ids or self.volunteer_ids)

    def to_dict(self) -> dict:
        return {k: sorted(v) for k, v in (("u", self.user_ids), ("r", self.roles), ("o", self.org_ids), ("d", self.donor_ids), ("v", self.volunteer_ids))}

    @classmethod
    def from_dict(cls, d: dict) -> "Audience":
        return cls(frozenset(d.get("u", ())), frozenset(d.get("r", ())), frozenset(d.get("o", ())), frozenset(d.get("d", ())), frozenset(d.get("v", ())))


def audience(*, users: Iterable = (), roles: Iterable = (), orgs: Iterable = (), donors: Iterable = (), volunteers: Iterable = ()) -> Audience:
    """Convenience builder that drops None ids (a delivery without a volunteer yet must not match 'volunteer None')."""
    clean = lambda it: frozenset(x for x in it if x is not None)  # noqa: E731
    return Audience(clean(users), clean(roles), clean(orgs), clean(donors), clean(volunteers))


# --------------------------------------------------------------------------- event
@dataclass
class Event:
    id: str
    type: str
    payload: dict
    audience: Audience
    ts: float = field(default_factory=time.time)

    def to_json(self) -> str:
        return json.dumps({"id": self.id, "type": self.type, "payload": self.payload, "aud": self.audience.to_dict(), "ts": self.ts}, separators=(",", ":"))

    @classmethod
    def from_json(cls, raw: str, event_id: Optional[str] = None) -> "Event":
        d = json.loads(raw)
        return cls(event_id or d["id"], d["type"], d["payload"], Audience.from_dict(d["aud"]), d["ts"])

    def frame(self) -> str:
        """The SSE text frame sent to a client. The audience is never included. Control frames (hello, resync) carry NO `id:`
        line: an id there would become the browser's Last-Event-ID and corrupt the next replay."""
        data = json.dumps({"id": self.id, "type": self.type, "payload": self.payload, "ts": self.ts}, separators=(",", ":"))
        id_line = "" if self.type in CONTROL_TYPES else f"id: {self.id}\n"
        return f"{id_line}event: {self.type}\ndata: {data}\n\n"


def sanitize(event_type: str, payload: dict) -> dict:
    if event_type not in SCHEMAS:
        raise ValueError(f"Unknown event type: {event_type}")
    allowed, clean = SCHEMAS[event_type], {}
    for key, value in (payload or {}).items():
        if key not in allowed:
            continue                                            # not on the allow-list: dropped, not sent
        if isinstance(value, bool) or value is None or isinstance(value, (int, float)):
            clean[key] = value
        elif isinstance(value, str):
            clean[key] = value[:_MAX_STR]
        # anything else (lists, dicts, objects) is dropped: payloads are flat and small by design
    return clean


def heartbeat_frame() -> str:
    return ": ping\n\n"


def parse_event_id(value: Optional[str]) -> Optional[tuple[int, int]]:
    if not value or not _ID_RE.match(value):
        return None
    a, b = value.split("-")
    return int(a), int(b)


# --------------------------------------------------------------------------- local hub
class Subscriber:
    """One connected client. Created on the event loop that serves it; dispatch may arrive from any thread."""

    def __init__(self, principal: dict, loop: asyncio.AbstractEventLoop):
        self.principal, self.loop = principal, loop
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_SIZE)
        self._seen: deque = deque(maxlen=500)
        self._seen_set: set = set()
        self.closed = False

    def offer(self, event: Event) -> None:
        if self.closed:
            return
        try:
            self.loop.call_soon_threadsafe(self._put, event)
        except RuntimeError:                                    # the loop is gone: the connection is dead
            self.closed = True

    def _put(self, event: Event) -> None:
        if event.id in self._seen_set:                          # duplicate protection (replay + live overlap, double publish)
            return
        if len(self._seen) == self._seen.maxlen:
            self._seen_set.discard(self._seen[0])
        self._seen.append(event.id)
        self._seen_set.add(event.id)
        try:
            self.queue.put_nowait(event)
        except asyncio.QueueFull:                               # a client that cannot keep up must re-sync, never block the server
            while not self.queue.empty():
                self.queue.get_nowait()
            self.queue.put_nowait(Event("0-0", "system.resync", {"reason": "slow_consumer"}, Audience()))


class Hub:
    def __init__(self):
        self._subs: set[Subscriber] = set()
        self._lock = threading.Lock()

    def subscribe(self, principal: dict, loop: asyncio.AbstractEventLoop) -> Subscriber:
        sub = Subscriber(principal, loop)
        with self._lock:
            self._subs.add(sub)
        return sub

    def unsubscribe(self, sub: Subscriber) -> None:
        sub.closed = True
        with self._lock:
            self._subs.discard(sub)

    def count(self) -> int:
        with self._lock:
            return len(self._subs)

    def dispatch(self, event: Event) -> int:
        with self._lock:
            subs = list(self._subs)
        delivered = 0
        for sub in subs:
            if event.audience.allows(sub.principal):
                sub.offer(event)
                delivered += 1
        return delivered


hub = Hub()


# --------------------------------------------------------------------------- local ids + replay ring (no-Redis mode)
_id_lock = threading.Lock()
_last = [0, 0]
_ring: deque = deque(maxlen=MEMORY_RING)


def _next_local_id() -> str:
    with _id_lock:
        ms = int(time.time() * 1000)
        if ms > _last[0]:
            _last[0], _last[1] = ms, 0
        else:
            _last[1] += 1
        return f"{_last[0]}-{_last[1]}"


def reset_for_tests() -> None:
    with _id_lock:
        _last[0] = _last[1] = 0
        _ring.clear()
    hub._subs.clear()


# --------------------------------------------------------------------------- publish
def publish(event_type: str, payload: dict, aud: Audience) -> Optional[Event]:
    """Create and distribute an event. Never raises: a failed notification must not undo or fail the business action."""
    try:
        if aud.is_empty():
            return None
        clean = sanitize(event_type, payload)
        client = redis_client.get_sync()
        if client is not None:
            try:
                draft = Event("", event_type, clean, aud)       # the stream assigns the id; the stored copy's id field is ignored on replay
                ev = Event(client.xadd(STREAM_KEY, {"data": draft.to_json()}, maxlen=STREAM_MAXLEN, approximate=True),
                           event_type, clean, aud, draft.ts)
                client.publish(CHANNEL, ev.to_json())
                return ev                                       # local subscribers get it through the channel listener
            except Exception as exc:
                redis_client.mark_failed(exc)                   # fall through to process-local delivery
        ev = Event(_next_local_id(), event_type, clean, aud)
        _ring.append(ev)
        hub.dispatch(ev)
        return ev
    except Exception:
        logger.exception("Could not publish event %s", event_type)
        return None


def _ensure_listeners(db: Any) -> None:
    from sqlalchemy import event as sa_event

    if not db.info.get("cb_event_listeners"):
        sa_event.listen(db, "after_commit", _flush_pending)
        sa_event.listen(db, "after_rollback", _drop_pending)
        db.info["cb_event_listeners"] = True


def publish_after_commit(db: Any, event_type: str, payload: dict, aud: Audience) -> None:
    """Hold the event until `db` has really committed; discard it on rollback."""
    db.info.setdefault("cb_pending_events", []).append((event_type, payload, aud))
    _ensure_listeners(db)


def call_after_commit(db: Any, fn: Callable, *args: Any) -> None:
    """Run `fn(*args)` only after `db` has really committed (and never on rollback). Used to hand work to a background worker
    that will read the rows this transaction just wrote. A failing callback is logged, never raised into the request."""
    db.info.setdefault("cb_pending_calls", []).append((fn, args))
    _ensure_listeners(db)


def _flush_pending(session) -> None:
    for event_type, payload, aud in session.info.pop("cb_pending_events", []):
        publish(event_type, payload, aud)
    for fn, args in session.info.pop("cb_pending_calls", []):
        try:
            fn(*args)
        except Exception:
            logger.exception("An after-commit callback failed")


def _drop_pending(session) -> None:
    session.info.pop("cb_pending_events", None)
    session.info.pop("cb_pending_calls", None)


# --------------------------------------------------------------------------- replay
def replay_since(last_id: Optional[str], principal: dict) -> tuple[list[Event], bool]:
    """(events the client missed that it may see, needs_resync). A client with no/invalid Last-Event-ID simply starts live."""
    if last_id is None:
        return [], False
    cursor = parse_event_id(last_id)
    if cursor is None:
        return [], True
    client = redis_client.get_sync()
    if client is not None:
        try:
            rows = client.xrange(STREAM_KEY, min=f"({last_id}", max="+", count=REPLAY_LIMIT)
            events = [Event.from_json(fields["data"], event_id=rid) for rid, fields in rows]
            return [e for e in events if e.audience.allows(principal)], len(rows) >= REPLAY_LIMIT
        except Exception as exc:
            redis_client.mark_failed(exc)
            return [], True
    snapshot = list(_ring)
    if snapshot and parse_event_id(snapshot[0].id) > cursor and len(snapshot) == _ring.maxlen:
        return [], True                                         # the gap is older than what we kept
    return [e for e in snapshot if parse_event_id(e.id) > cursor and e.audience.allows(principal)], False


# --------------------------------------------------------------------------- redis fan-out (one task per worker process)
async def run_redis_fanout(stop: asyncio.Event) -> None:
    """Listen on the Redis channel and hand each event to this process's connected clients. Reconnects with backoff."""
    delay = 1.0
    while not stop.is_set():
        client = None
        try:
            client = redis_client.make_async()
            pubsub = client.pubsub()
            await pubsub.subscribe(CHANNEL)
            delay = 1.0
            logger.info("Event fan-out listening on Redis")
            while not stop.is_set():
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if msg and msg.get("type") == "message":
                    try:
                        hub.dispatch(Event.from_json(msg["data"]))
                    except Exception:
                        logger.exception("Dropped an unreadable event from Redis")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Event fan-out lost Redis (%s); retrying in %.0fs", type(exc).__name__, delay)
            await asyncio.sleep(delay)
            delay = min(30.0, delay * 2)
        finally:
            if client is not None:
                try:
                    await client.aclose()
                except Exception:
                    pass
