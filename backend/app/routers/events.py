"""GET /events/stream: authenticated Server-Sent Events for the signed-in user.

* Auth is the normal `Authorization: Bearer` header (the web client reads the stream with fetch, so it can send it). A token in
  the URL is deliberately NOT accepted: URLs end up in logs.
* The database session used to authenticate is closed immediately. A stream can stay open for hours and must not pin a pooled
  connection; instead the token is re-validated every REVALIDATE_SECONDS, so a sign-out, password change or deactivation ends
  the stream within a minute.
* Each connection only ever receives events whose audience includes that user (services/events.py), never anything else.
* Heartbeats keep proxies from closing an idle stream; Last-Event-ID replays what a reconnecting client missed.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.security.utils import get_authorization_scheme_param
from starlette.background import BackgroundTask

from ..database import SessionLocal
from ..dependencies import authenticate_token, require_admin
from ..services import events as live, redis_client

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/events", tags=["events"])

HEARTBEAT_SECONDS = 15
REVALIDATE_SECONDS = 60
MAX_STREAMS_PER_USER = 5          # per worker process: a runaway client or a hostile script cannot exhaust connections

_open: dict[int, int] = {}
_open_lock = threading.Lock()


def _bearer(request: Request) -> str:
    scheme, token = get_authorization_scheme_param(request.headers.get("authorization"))
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Not authenticated", headers={"WWW-Authenticate": "Bearer"})
    return token


def _validate(token: str) -> dict:
    db = SessionLocal()
    try:
        return authenticate_token(token, db)
    finally:
        db.close()


def _still_valid(token: str) -> bool:
    try:
        _validate(token)
        return True
    except HTTPException:
        return False
    except Exception:
        logger.exception("Could not re-validate an event stream; keeping it open")
        return True                                              # a database blip must not disconnect everyone


class _Slot:
    """A claim on one of the user's connection slots. release() is idempotent, so it is safe to call from both the generator's
    `finally` and the response's background task (a client that vanishes before streaming starts would otherwise leak a slot)."""

    def __init__(self, user_id: int):
        self.user_id, self.done = user_id, False

    def release(self) -> None:
        with _open_lock:
            if self.done:
                return
            self.done = True
            left = _open.get(self.user_id, 1) - 1
            if left <= 0:
                _open.pop(self.user_id, None)
            else:
                _open[self.user_id] = left


def _take_slot(user_id: int) -> Optional[_Slot]:
    with _open_lock:
        if _open.get(user_id, 0) >= MAX_STREAMS_PER_USER:
            return None
        _open[user_id] = _open.get(user_id, 0) + 1
    return _Slot(user_id)


@router.get("/stream")
async def stream(request: Request):
    token = _bearer(request)
    user = await asyncio.to_thread(_validate, token)
    slot = _take_slot(user["id"])
    if slot is None:
        raise HTTPException(status_code=429, detail="Too many open live connections for this account. Close another tab and retry.", headers={"Retry-After": "10"})
    last_id: Optional[str] = request.headers.get("last-event-id")

    async def generate():
        sub = live.hub.subscribe(user, asyncio.get_running_loop())    # subscribe BEFORE replay so nothing falls in the gap (duplicates are dropped by id)
        try:
            yield "retry: 3000\n\n"
            missed, resync = await asyncio.to_thread(live.replay_since, last_id, user)
            yield live.Event("0-0", "hello", {"server_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "replayed": len(missed)}, live.Audience()).frame()
            for event in missed:
                yield event.frame()
            if resync:
                yield live.Event("0-0", "system.resync", {"reason": "gap"}, live.Audience()).frame()
            checked = time.monotonic()
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(sub.queue.get(), timeout=HEARTBEAT_SECONDS)
                    yield event.frame()
                except asyncio.TimeoutError:
                    yield live.heartbeat_frame()
                if time.monotonic() - checked >= REVALIDATE_SECONDS:
                    checked = time.monotonic()
                    if not await asyncio.to_thread(_still_valid, token):
                        break                                         # signed out / deactivated / password changed
        finally:
            live.hub.unsubscribe(sub)
            slot.release()

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
                             background=BackgroundTask(slot.release))


@router.get("/status")
def status(admin: dict = Depends(require_admin)):
    """Operators: how many live connections this worker holds and whether Redis fan-out is active."""
    return {"connections_on_this_worker": live.hub.count(), "redis": redis_client.status()}
