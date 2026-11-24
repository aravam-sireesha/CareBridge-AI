"""Error monitoring (Sentry) that cannot leak what this platform exists to protect.

Off unless SENTRY_DSN is set. When on:
* `send_default_pii=False`, request bodies are never attached, and every event passes through `scrub_event` first.
* scrub_event removes by KEY NAME (passwords, tokens, OTPs, authorization/cookie headers, phone/email, addresses, children's details,
  and every kind of GPS coordinate) and by VALUE PATTERN (e-mail addresses, JWTs, bearer tokens, phone numbers, coordinate pairs),
  recursively through the exception text, stack-frame variables, breadcrumbs, request, extra and tags. Users are reduced to an id.
Failing safe: if scrubbing itself raises, the event is DROPPED, never sent unscrubbed.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)
REDACTED = "[Filtered]"
MAX_DEPTH = 12

SENSITIVE_KEYS = re.compile(
    r"pass(word|wd)?|secret|token|otp|code_hash|authorization|cookie|set-cookie|api[-_]?key|private|credential|signature|csrf|session|"
    r"phone|mobile|e164|email|address|street|"
    r"lat(itude)?|lng|lon(gitude)?|coord|location|position|geo|gps|heading|speed|accuracy|"
    r"child|children|guardian|beneficiar|dob|birth|aadhaar|aadhar|pan_?number|national_?id|ssn", re.I)
_PATTERNS = (
    (re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"), "[email]"),
    (re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]*"), "[jwt]"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-~+/=]{8,}"), "Bearer [token]"),
    (re.compile(r"(?<![\d.])[-+]?\d{1,3}\.\d{4,}\s*[,;/ ]\s*[-+]?\d{1,3}\.\d{4,}(?![\d])"), "[coordinates]"),   # "17.385044, 78.486671"
    (re.compile(r"(?<!\w)\+?\d[\d\s\-().]{8,}\d(?!\w)"), "[number]"),                                          # phone-like digit runs
)


def scrub_string(value: str) -> str:
    for pattern, replacement in _PATTERNS:
        value = pattern.sub(replacement, value)
    return value


def scrub(value: Any, depth: int = 0) -> Any:
    """Return a scrubbed COPY of any JSON-like structure."""
    if depth > MAX_DEPTH:
        return REDACTED
    if isinstance(value, dict):
        return {k: (REDACTED if isinstance(k, str) and SENSITIVE_KEYS.search(k) else scrub(v, depth + 1)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [scrub(v, depth + 1) for v in value]
    if isinstance(value, str):
        return scrub_string(value)
    return value


def scrub_event(event: dict, hint: Optional[dict] = None) -> Optional[dict]:
    """Sentry before_send. Returns the scrubbed event, or None (drop) if anything goes wrong."""
    try:
        clean = scrub(event)
        clean["user"] = {"id": str(event["user"]["id"])} if isinstance(event.get("user"), dict) and event["user"].get("id") is not None else {}
        req = clean.get("request")
        if isinstance(req, dict):
            req.pop("data", None); req.pop("cookies", None); req.pop("query_string", None)
            req["headers"] = {k: v for k, v in (req.get("headers") or {}).items() if k.lower() in ("user-agent", "content-type", "accept", "host")}
        clean.pop("server_name", None)
        return clean
    except Exception:
        logger.exception("Dropping an error event because it could not be scrubbed")
        return None


def scrub_breadcrumb(crumb: dict, hint: Optional[dict] = None) -> Optional[dict]:
    try:
        if crumb.get("category") in ("httplib", "httpx", "urllib3", "requests"):
            data = dict(crumb.get("data") or {}); data.pop("url", None); crumb = {**crumb, "data": data}   # outbound URLs can carry keys/addresses
        return scrub(crumb)
    except Exception:
        return None


def init(component: str = "api", env: Optional[dict] = None) -> bool:
    env = os.environ if env is None else env
    dsn = (env.get("SENTRY_DSN") or "").strip()
    if not dsn:
        return False
    try:
        import sentry_sdk
        rate = float(env.get("SENTRY_TRACES_SAMPLE_RATE") or 0)
        sentry_sdk.init(dsn=dsn, environment=env.get("SENTRY_ENVIRONMENT") or "production", release=env.get("APP_RELEASE") or None,
                        traces_sample_rate=max(0.0, min(1.0, rate)), send_default_pii=False, max_request_body_size="never",
                        before_send=scrub_event, before_breadcrumb=scrub_breadcrumb, include_local_variables=False)
        sentry_sdk.set_tag("component", component)
        logger.info("Error monitoring enabled (%s)", component)
        return True
    except Exception as exc:                          # missing package, bad DSN: the app must still start
        logger.warning("Error monitoring could not start (%s)", type(exc).__name__)
        return False


def capture_current() -> None:
    try:
        import sentry_sdk
        sentry_sdk.capture_exception()
    except Exception:
        pass
