"""Web Push (VAPID) sending, with the safety rules in one place.

* SSRF defence: a subscription's endpoint is a URL chosen by the CLIENT and later POSTed to by THIS SERVER. It is therefore accepted only
  if it is https, on port 443, without credentials, and on a known push-service host (Google FCM, Mozilla, Apple, Microsoft). An internal
  address, a metadata endpoint or any other host is refused when subscribing AND again at send time.
* Minimal payloads: the push carries a short title, a generic body and a same-site link, never a need's details, names, places or
  anything about a child. (The payload is encrypted to the device, but a lock screen may show it.)
* Honest status: `accepted` means the push service took the message (HTTP 2xx). It does not mean the device showed it.
* Configuration (environment only): VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY, VAPID_SUBJECT (mailto: or https: contact). Optional
  PUSH_ALLOWED_HOSTS: extra comma-separated host suffixes. Keys: see MAP_AND_GPS_SETUP / API_INTEGRATION_GUIDE.
LIVE SENDING IS UNTESTED here (no VAPID keys, no browser). Tests use a fake sender.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from typing import Callable, Mapping, Optional
from urllib.parse import urlsplit

from .notify_rules import safe_link

logger = logging.getLogger(__name__)

DEFAULT_HOST_SUFFIXES = ("fcm.googleapis.com", "updates.push.services.mozilla.com", "push.apple.com", "notify.windows.com")
MAX_ENDPOINT = 1000
FAILURES_BEFORE_DROP = 5
MAX_PAYLOAD_BYTES = 3500                     # push services accept ~4 KB after encryption
_B64URL = re.compile(r"^[A-Za-z0-9_\-]+={0,2}$")
GENERIC_BODY = "Open CareBridge for details."


class SubscriptionError(ValueError):
    pass


class PushHttpError(Exception):
    def __init__(self, status: int):
        super().__init__(f"push service answered {status}")
        self.status = status


def allowed_suffixes(env: Mapping[str, str]) -> tuple[str, ...]:
    extra = tuple(x.strip().lower().lstrip(".") for x in str(env.get("PUSH_ALLOWED_HOSTS", "")).split(",") if x.strip())
    return DEFAULT_HOST_SUFFIXES + extra


def host_allowed(endpoint: object, env: Mapping[str, str]) -> bool:
    if not isinstance(endpoint, str) or not endpoint or len(endpoint) > MAX_ENDPOINT or any(ord(c) < 33 for c in endpoint):
        return False
    try:
        parts = urlsplit(endpoint)
        host, port = (parts.hostname or "").lower(), parts.port
    except ValueError:
        return False
    if parts.scheme != "https" or parts.username or parts.password or port not in (None, 443) or not host:
        return False
    return any(host == suf or host.endswith("." + suf) for suf in allowed_suffixes(env))


def endpoint_hash(endpoint: str) -> str:
    return hashlib.sha256(endpoint.encode("utf-8")).hexdigest()


def validate_subscription(data: object, env: Mapping[str, str]) -> tuple[str, str, str]:
    """(endpoint, p256dh, auth) from the browser's PushSubscription.toJSON(), or SubscriptionError."""
    if not isinstance(data, dict):
        raise SubscriptionError("That is not a push subscription.")
    endpoint, keys = data.get("endpoint"), data.get("keys")
    if not host_allowed(endpoint, env):
        raise SubscriptionError("That notification service is not supported.")
    if not isinstance(keys, dict):
        raise SubscriptionError("The subscription has no keys.")
    p256dh, auth = keys.get("p256dh"), keys.get("auth")
    for value, lo, hi, label in ((p256dh, 80, 100, "key"), (auth, 20, 30, "secret")):
        if not isinstance(value, str) or not (lo <= len(value) <= hi) or not _B64URL.match(value):
            raise SubscriptionError(f"The subscription {label} is not valid.")
    return endpoint, p256dh, auth


def vapid_enabled(env: Mapping[str, str]) -> bool:
    subject = (env.get("VAPID_SUBJECT") or "").strip()
    return bool((env.get("VAPID_PUBLIC_KEY") or "").strip() and (env.get("VAPID_PRIVATE_KEY") or "").strip() and subject.startswith(("mailto:", "https:")))


def build_payload(kind: str, title: Optional[str], link: Optional[str]) -> str:
    body = {"title": (" ".join(str(title or "CareBridge").split()))[:80] or "CareBridge", "body": GENERIC_BODY,
            "url": safe_link(link) or "/notifications", "kind": str(kind)[:20], "tag": f"cb-{str(kind)[:20]}"}
    out = json.dumps(body, separators=(",", ":"))      # never sliced: a cut-off JSON document would be unreadable. The field caps above keep it far below the limit
    assert len(out) <= MAX_PAYLOAD_BYTES, "payload field limits no longer guarantee the size bound"
    return out


@dataclass(frozen=True)
class SendResult:
    status: str          # accepted | gone | retry | failed | not_configured | refused
    code: str = ""


def _default_sender(info: dict, data: str, private_key: str, claims: dict, ttl: int) -> int:
    from pywebpush import WebPushException, webpush          # lazy: not needed (or installed) for anything but live sending

    try:
        res = webpush(subscription_info=info, data=data, vapid_private_key=private_key, vapid_claims=claims, ttl=ttl, timeout=10)
        return int(getattr(res, "status_code", 201))
    except WebPushException as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status is None:
            raise OSError("push service unreachable") from None
        raise PushHttpError(int(status)) from None


def send(subscription: Mapping[str, str], payload: str, env: Mapping[str, str], sender: Optional[Callable] = None, ttl: int = 3600) -> SendResult:
    """Send one push. Never raises. `subscription` needs endpoint, p256dh, auth."""
    if not vapid_enabled(env):
        return SendResult("not_configured")
    if not host_allowed(subscription.get("endpoint"), env):
        return SendResult("refused", "host_not_allowed")        # defence in depth: re-checked even for stored rows
    info = {"endpoint": subscription["endpoint"], "keys": {"p256dh": subscription["p256dh"], "auth": subscription["auth"]}}
    try:
        status = (sender or _default_sender)(info, payload, env["VAPID_PRIVATE_KEY"].strip(), {"sub": env["VAPID_SUBJECT"].strip()}, ttl)
    except PushHttpError as exc:
        status = exc.status
    except Exception as exc:                                       # network failure, library missing, bad key: class name only (no URLs/keys in logs)
        logger.warning("Web Push send failed (%s)", type(exc).__name__)
        return SendResult("retry", type(exc).__name__[:40])
    if 200 <= status < 300:
        return SendResult("accepted", str(status))
    if status in (404, 410):
        return SendResult("gone", str(status))                      # the browser unsubscribed or the subscription expired
    if status == 429 or status >= 500:
        return SendResult("retry", str(status))
    logger.warning("Web Push refused with HTTP %s (check the VAPID keys and subject)", status)
    return SendResult("failed", str(status))


def summarize(results: list[SendResult]) -> tuple[str, int, Optional[str]]:
    """(notification status, accepted count, error code) for one notification across all of a person's devices."""
    if not results:
        return "no_subscription", 0, None
    accepted = sum(1 for r in results if r.status == "accepted")
    if accepted:
        return "accepted_by_provider", accepted, None
    live = [r for r in results if r.status != "gone"]
    if not live:
        return "no_subscription", 0, "gone"
    return "failed", 0, (live[0].code or live[0].status)[:40]


def should_retry(results: list[SendResult]) -> bool:
    """Nothing was accepted and at least one device answered with a temporary problem: trying again later may succeed."""
    return bool(results) and not any(r.status == "accepted" for r in results) and any(r.status == "retry" for r in results)


def next_failure_count(current: int, result: SendResult) -> tuple[int, bool]:
    """(new consecutive-failure count, drop this device?). A 404/410 drops it at once; repeated failures drop it eventually."""
    if result.status == "gone":
        return current, True
    if result.status == "accepted":
        return 0, False
    if result.status in ("not_configured", "refused"):
        return current, result.status == "refused"
    count = current + 1
    return count, count >= FAILURES_BEFORE_DROP
