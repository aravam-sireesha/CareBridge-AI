"""Event bus: audience filtering, payload allow-lists, duplicate/overflow handling, replay, Redis mode and Redis failure."""
import asyncio
import json
import time

import pytest

from app.services import events as ev
from app.services import redis_client

ORG = {"id": 1, "role": "organization", "organization_id": 10, "donor_id": None, "volunteer_id": None}
OTHER_ORG = {"id": 2, "role": "organization", "organization_id": 11, "donor_id": None, "volunteer_id": None}
DONOR = {"id": 3, "role": "donor", "organization_id": None, "donor_id": 20, "volunteer_id": None}
VOL = {"id": 4, "role": "volunteer", "organization_id": None, "donor_id": None, "volunteer_id": 30}
ADMIN = {"id": 5, "role": "admin", "organization_id": None, "donor_id": None, "volunteer_id": None}
DELIVERY = ev.audience(orgs=[10], donors=[20], volunteers=[30], roles=["admin"])


@pytest.fixture
def clean():
    ev.reset_for_tests()
    redis_client.reset_for_tests()


# ---------------------------------------------------------------- payload allow-lists
def test_sanitize_drops_everything_not_on_the_allow_list():
    out = ev.sanitize("delivery.status", {"task_id": 7, "status": "in_transit", "label": "On the way",
                                          "address": "12 Hidden Lane", "phone": "+91999", "child_name": "X", "notes": {"a": 1}})
    assert out == {"task_id": 7, "status": "in_transit", "label": "On the way"}


def test_sanitize_unknown_type_is_an_error_not_a_pass_through():
    with pytest.raises(ValueError):
        ev.sanitize("made.up", {"x": 1})


def test_sanitize_drops_nested_values_and_truncates_long_strings():
    out = ev.sanitize("notification", {"id": 1, "title": "t" * 1000, "kind": ["a"], "link": {"x": 1}})
    assert out == {"id": 1, "title": "t" * 300}


def test_location_event_cannot_carry_unrounded_extras():
    out = ev.sanitize("delivery.location", {"task_id": 1, "latitude": 17.3851, "longitude": 78.4867, "accuracy_m": 8.0,
                                            "recorded_at": "2026-11-05T10:00:00", "status": "in_transit",
                                            "volunteer_id": 30, "heading": 90, "speed": 4.2, "phone": "x"})
    assert set(out) == {"task_id", "latitude", "longitude", "accuracy_m", "recorded_at", "status"}


# ---------------------------------------------------------------- audiences
def test_audience_matches_by_user_role_and_linked_entity():
    assert DELIVERY.allows(ORG) and DELIVERY.allows(DONOR) and DELIVERY.allows(VOL) and DELIVERY.allows(ADMIN)
    assert not DELIVERY.allows(OTHER_ORG)                       # another organization sees nothing about this delivery


def test_none_ids_never_match_a_principal_without_that_link():
    aud = ev.audience(volunteers=[None], donors=[None])           # a delivery with no volunteer yet
    assert aud.is_empty()
    assert not aud.allows(ORG) and not aud.allows(DONOR)


def test_user_targeted_audience_is_exact():
    aud = ev.audience(users=[3])
    assert aud.allows(DONOR) and not aud.allows(VOL) and not aud.allows(ADMIN)


def test_empty_audience_publishes_nothing(clean):
    assert ev.publish("notification", {"id": 1}, ev.audience()) is None


def test_frame_never_contains_the_audience_and_round_trips():
    e = ev.Event("1-0", "delivery.status", {"task_id": 2, "status": "picked_up"}, DELIVERY)
    frame = e.frame()
    assert "aud" not in frame and "30" not in frame.split("data:")[1] and frame.startswith("id: 1-0\nevent: delivery.status\n")
    back = ev.Event.from_json(e.to_json())
    assert back.audience == DELIVERY and back.payload == e.payload


# ---------------------------------------------------------------- local hub
def _run(coro):
    return asyncio.run(coro)


async def settle(cond, timeout=3.0):
    """Wait (bounded) until `cond()` holds. Delivery to a subscriber crosses call_soon_threadsafe, so tests must not assume a fixed delay."""
    start = time.monotonic()
    while not cond():
        if time.monotonic() - start > timeout:
            return False
        await asyncio.sleep(0.005)
    return True


async def quiet(seconds=0.05):
    """A short window for 'nothing else should arrive' checks (the positive waits above use settle())."""
    await asyncio.sleep(seconds)


def test_publish_reaches_only_authorised_subscribers(clean):
    async def scenario():
        loop = asyncio.get_running_loop()
        subs = {n: ev.hub.subscribe(p, loop) for n, p in (("org", ORG), ("other", OTHER_ORG), ("donor", DONOR), ("vol", VOL), ("admin", ADMIN))}
        ev.publish("delivery.status", {"task_id": 1, "status": "in_transit"}, DELIVERY)
        assert await settle(lambda: sum(s.queue.qsize() for s in subs.values()) >= 4)
        await quiet()                                                 # then make sure nobody else (the other organization) also received it
        return {n: s.queue.qsize() for n, s in subs.items()}
    assert _run(scenario()) == {"org": 1, "other": 0, "donor": 1, "vol": 1, "admin": 1}


def test_same_event_id_is_delivered_once_per_connection(clean):
    async def scenario():
        sub = ev.hub.subscribe(ORG, asyncio.get_running_loop())
        e = ev.Event("5-0", "delivery.status", {"task_id": 1}, DELIVERY)
        ev.hub.dispatch(e)
        ev.hub.dispatch(e)                                        # e.g. replay overlapping the live feed
        assert await settle(lambda: sub.queue.qsize() >= 1)
        await quiet()
        return sub.queue.qsize()
    assert _run(scenario()) == 1


def test_slow_consumer_gets_a_resync_instead_of_blocking_the_server(clean):
    async def scenario():
        sub = ev.hub.subscribe(ORG, asyncio.get_running_loop())
        for i in range(ev.QUEUE_SIZE + 5):
            ev.hub.dispatch(ev.Event(f"{i + 1}-0", "delivery.status", {"task_id": i}, DELIVERY))
        assert await settle(lambda: any(e.type == "system.resync" for e in list(sub.queue._queue)))
        await quiet()
        items = []
        while not sub.queue.empty():
            items.append(sub.queue.get_nowait())
        return items
    items = _run(scenario())
    assert any(i.type == "system.resync" for i in items) and len(items) <= ev.QUEUE_SIZE


def test_unsubscribed_connection_receives_nothing_and_is_removed(clean):
    async def scenario():
        sub = ev.hub.subscribe(ORG, asyncio.get_running_loop())
        ev.hub.unsubscribe(sub)
        ev.publish("delivery.status", {"task_id": 1}, DELIVERY)
        await quiet()                                                 # a negative check: nothing may arrive
        return sub.queue.qsize(), ev.hub.count()
    assert _run(scenario()) == (0, 0)


# ---------------------------------------------------------------- replay (no Redis)
def test_replay_returns_only_missed_events_the_client_may_see(clean):
    a = ev.publish("delivery.status", {"task_id": 1}, DELIVERY)
    b = ev.publish("delivery.status", {"task_id": 2}, ev.audience(orgs=[11]))     # someone else's delivery
    c = ev.publish("delivery.status", {"task_id": 3}, DELIVERY)
    missed, resync = ev.replay_since(a.id, ORG)
    assert [m.id for m in missed] == [c.id] and not resync       # b is filtered out, a is not repeated


def test_replay_with_garbage_last_event_id_asks_for_resync_and_none_means_live(clean):
    assert ev.replay_since("not-an-id; DROP", ORG) == ([], True)
    assert ev.replay_since(None, ORG) == ([], False)


def test_local_ids_are_strictly_increasing(clean):
    ids = [ev.publish("delivery.status", {"task_id": i}, DELIVERY).id for i in range(50)]
    parsed = [ev.parse_event_id(i) for i in ids]
    assert parsed == sorted(parsed) and len(set(parsed)) == 50


# ---------------------------------------------------------------- Redis mode (fake client)
class FakeRedis:
    def __init__(self):
        self.stream, self.published, self.fail = [], [], False

    def xadd(self, key, fields, maxlen=None, approximate=True):
        if self.fail:
            raise ConnectionError("down")
        rid = f"{1000 + len(self.stream)}-0"
        self.stream.append((rid, fields))
        return rid

    def publish(self, channel, data):
        self.published.append((channel, data))

    def xrange(self, key, min="-", max="+", count=None):
        if self.fail:
            raise ConnectionError("down")
        after = min.lstrip("(")
        key_of = lambda r: tuple(int(x) for x in r.split("-"))  # noqa: E731
        return [(r, f) for r, f in self.stream if key_of(r) > key_of(after)][:count]


def test_redis_mode_writes_stream_and_channel_with_the_stream_id(clean, monkeypatch):
    r = FakeRedis()
    monkeypatch.setattr(redis_client, "get_sync", lambda: r)
    e = ev.publish("delivery.status", {"task_id": 9, "status": "delivered"}, DELIVERY)
    assert e.id == "1000-0" and len(r.stream) == 1
    chan, data = r.published[0]
    assert chan == ev.CHANNEL and json.loads(data)["id"] == "1000-0"


def test_redis_replay_filters_by_audience(clean, monkeypatch):
    r = FakeRedis()
    monkeypatch.setattr(redis_client, "get_sync", lambda: r)
    first = ev.publish("delivery.status", {"task_id": 1}, DELIVERY)
    ev.publish("delivery.status", {"task_id": 2}, ev.audience(orgs=[11]))
    third = ev.publish("delivery.status", {"task_id": 3}, DELIVERY)
    missed, resync = ev.replay_since(first.id, ORG)
    assert [m.id for m in missed] == [third.id] and not resync


def test_redis_failure_falls_back_to_local_delivery_and_never_raises(clean, monkeypatch):
    r = FakeRedis()
    r.fail = True
    marked = []
    monkeypatch.setattr(redis_client, "get_sync", lambda: r)
    monkeypatch.setattr(redis_client, "mark_failed", lambda exc: marked.append(exc))
    async def scenario():
        sub = ev.hub.subscribe(ORG, asyncio.get_running_loop())
        e = ev.publish("delivery.status", {"task_id": 1}, DELIVERY)
        assert await settle(lambda: sub.queue.qsize() >= 1)
        await quiet()
        return e, sub.queue.qsize()
    e, n = _run(scenario())
    assert e is not None and n == 1 and marked


def test_replay_when_redis_errors_asks_the_client_to_resync(clean, monkeypatch):
    r = FakeRedis()
    r.fail = True
    monkeypatch.setattr(redis_client, "get_sync", lambda: r)
    monkeypatch.setattr(redis_client, "mark_failed", lambda exc: None)
    assert ev.replay_since("1000-0", ORG) == ([], True)


# ---------------------------------------------------------------- after-commit semantics (no SQLAlchemy needed)
class FakeSession:
    def __init__(self):
        self.info = {}


def test_pending_events_publish_on_commit_and_vanish_on_rollback(clean):
    committed, rolled_back = FakeSession(), FakeSession()
    for s in (committed, rolled_back):
        s.info["cb_pending_events"] = [("delivery.status", {"task_id": 1}, DELIVERY)]
    ev._drop_pending(rolled_back)
    ev._flush_pending(rolled_back)                                # nothing left to publish
    assert len(ev._ring) == 0
    ev._flush_pending(committed)
    assert len(ev._ring) == 1 and "cb_pending_events" not in committed.info
