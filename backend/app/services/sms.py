"""SMS delivery boundary. Nothing is sent unless a real provider is configured, and "sent" is reported only after the provider accepted it.

Configure with environment variables (never in code):
    SMS_PROVIDER=twilio
    TWILIO_ACCOUNT_SID=...   TWILIO_AUTH_TOKEN=...   TWILIO_FROM=+15551234567
  or, for India (DLT-compliant, template based):
    SMS_PROVIDER=msg91
    MSG91_AUTH_KEY=...   MSG91_TEMPLATE_ID=...   (the template/flow id from the MSG91 dashboard)
    SMS_SENDER_ID=...    DLT_ENTITY_ID=...   DLT_TEMPLATE_ID=...   (registered on a DLT portal; required before any +91 message is sent)
Without them `provider_from_env()` returns None and callers must say "SMS is not configured", never pretend. Phone numbers, codes and
credentials are never logged and never appear in a provider object's repr.

Used by phone verification at sign-up (routers/phone_verification.py). It is not yet used for account recovery.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable, Mapping, Optional

logger = logging.getLogger("carebridge.sms")
Transport = Callable[[str, bytes, Mapping[str, str]], int]       # (url, form body, headers) -> HTTP status; raises on network failure


def normalize_phone(raw: object, default_country_code: str = "") -> Optional[str]:
    """Any reasonable human input -> E.164 ("+919876543210"), or None. A bare number needs `default_country_code` ("91")."""
    text = str(raw or "").strip()
    if not text or len(text) > 30 or re.search(r"[^\d\s()+\-.]", text):
        return None
    digits = re.sub(r"\D", "", text)
    if text.startswith("+") or text.startswith("00"):
        digits = digits[2:] if text.startswith("00") else digits
    elif default_country_code:
        digits = default_country_code.lstrip("+") + digits.lstrip("0")
    else:
        return None
    return "+" + digits if 8 <= len(digits) <= 15 and digits[0] != "0" else None


def is_valid_mobile(e164: object) -> bool:
    """A plausible mobile number in E.164 form. Indian numbers are checked more strictly: +91 then ten digits starting 6-9."""
    if not isinstance(e164, str) or normalize_phone(e164) != e164:
        return False
    if e164.startswith("+91"):
        return re.fullmatch(r"\+91[6-9]\d{9}", e164) is not None
    return True


def mask(phone: str) -> str:
    return phone[:3] + "*" * max(0, len(phone) - 5) + phone[-2:] if phone and len(phone) > 6 else "***"


def _urllib_transport(url: str, body: bytes, headers: Mapping[str, str]) -> int:
    req = urllib.request.Request(url, data=body, headers=dict(headers), method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:               # raises HTTPError (a URLError) for 4xx/5xx
        return resp.status


def _urllib_transport_with_body(url: str, body: bytes, headers: Mapping[str, str]) -> tuple[int, str]:
    req = urllib.request.Request(url, data=body, headers=dict(headers), method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status, resp.read(4000).decode("utf-8", "replace")


@dataclass(frozen=True)
class SmsResult:
    ok: bool
    mode: str


class TwilioProvider:
    mode = "twilio"

    def __init__(self, sid: str, token: str, sender: str, transport: Optional[Transport] = None):
        self._sid, self._token, self._sender, self._transport = sid, token, sender, transport or _urllib_transport

    def __repr__(self) -> str:                                          # never expose the credentials
        return "TwilioProvider(configured)"

    def send_otp(self, to: str, code: str, ttl_minutes: int) -> SmsResult:
        return self.send(to, f"Your CareBridge code is {code}. It expires in {ttl_minutes} minutes. Do not share it.")

    def send(self, to: str, text: str) -> SmsResult:
        if normalize_phone(to) != to:
            return SmsResult(False, self.mode)
        url = f"https://api.twilio.com/2010-04-01/Accounts/{urllib.parse.quote(self._sid)}/Messages.json"
        auth = base64.b64encode(f"{self._sid}:{self._token}".encode()).decode()
        body = urllib.parse.urlencode({"To": to, "From": self._sender, "Body": text}).encode()
        try:
            status = self._transport(url, body, {"Authorization": f"Basic {auth}", "Content-Type": "application/x-www-form-urlencoded"})
        except Exception as exc:                                         # network failure or an HTTP error status
            logger.warning("SMS delivery failed (%s)", type(exc).__name__)    # no number, no text, no credentials
            return SmsResult(False, self.mode)
        return SmsResult(200 <= status < 300, self.mode)


class Msg91Provider:
    """MSG91 template ("flow") API. The message text is the DLT-registered template that lives on MSG91; only VAR1 (the code) and
    VAR2 (minutes) are sent. In India nothing is sent unless the sender id and the DLT entity and template ids are configured."""
    mode = "msg91"
    URL = "https://control.msg91.com/api/v5/flow/"

    def __init__(self, auth_key: str, template_id: str, sender_id: str = "", dlt_entity_id: str = "", dlt_template_id: str = "",
                 transport: Optional[Transport] = None):
        self._key, self._template = auth_key, template_id
        self._sender, self._entity, self._dlt_template = sender_id, dlt_entity_id, dlt_template_id
        self._transport = transport or _urllib_transport_with_body

    def __repr__(self) -> str:
        return "Msg91Provider(configured)"

    @property
    def india_ready(self) -> bool:
        return bool(self._sender and self._entity and self._dlt_template)

    def send_otp(self, to: str, code: str, ttl_minutes: int) -> SmsResult:
        if not is_valid_mobile(to):
            return SmsResult(False, self.mode)
        if to.startswith("+91") and not self.india_ready:
            logger.warning("SMS not sent: SMS_SENDER_ID, DLT_ENTITY_ID and DLT_TEMPLATE_ID are required for Indian numbers")
            return SmsResult(False, self.mode)
        payload = {"flow_id": self._template, "recipients": [{"mobiles": to.lstrip("+"), "VAR1": code, "VAR2": str(ttl_minutes)}]}
        if self._sender:
            payload["sender"] = self._sender
        headers = {"authkey": self._key, "Content-Type": "application/json", "accept": "application/json"}
        try:
            out = self._transport(self.URL, json.dumps(payload).encode(), headers)
        except Exception as exc:
            logger.warning("SMS delivery failed (%s)", type(exc).__name__)
            return SmsResult(False, self.mode)
        status, text = out if isinstance(out, tuple) else (out, None)
        ok = 200 <= status < 300
        if ok and text is not None:                                      # MSG91 can answer HTTP 200 with {"type": "error"}
            try:
                ok = str(json.loads(text).get("type", "")).lower() == "success"
            except (ValueError, AttributeError):
                ok = False
        if not ok:
            logger.warning("SMS provider did not accept the message")
        return SmsResult(ok, self.mode)


def provider_from_env(env: Mapping[str, str] | None = None, transport: Optional[Transport] = None):
    """The configured provider, or None when SMS is not (fully) configured."""
    env = os.environ if env is None else env
    name = (env.get("SMS_PROVIDER") or "").strip().lower()
    get = lambda k: (env.get(k) or "").strip()                         # noqa: E731
    if name == "twilio":
        sid, token, sender = get("TWILIO_ACCOUNT_SID"), get("TWILIO_AUTH_TOKEN"), (get("TWILIO_FROM") or get("TWILIO_PHONE_NUMBER"))   # TWILIO_PHONE_NUMBER is the provider's own name for it
        if not (sid and token and normalize_phone(sender)):
            return None                                                  # half-configured is not configured
        return TwilioProvider(sid, token, normalize_phone(sender), transport)
    if name == "msg91":
        if not (get("MSG91_AUTH_KEY") and get("MSG91_TEMPLATE_ID")):
            return None
        return Msg91Provider(get("MSG91_AUTH_KEY"), get("MSG91_TEMPLATE_ID"), get("SMS_SENDER_ID"), get("DLT_ENTITY_ID"), get("DLT_TEMPLATE_ID"), transport)
    return None


# Development/test only: "sent" codes land here and nowhere else (never the log, never an API).
OUTBOX: list[tuple[str, str]] = []
_NON_PRODUCTION = {"development", "dev", "local", "test", "testing"}


def delivery_mode(env: Mapping[str, str] | None = None) -> str:
    """"twilio" | "msg91" | "outbox" | "console" | "none". outbox/console are refused unless APP_ENV is development/dev/local/test."""
    env = os.environ if env is None else env
    requested = (env.get("SMS_DELIVERY") or "").strip().lower()
    if requested in ("outbox", "console") and (env.get("APP_ENV") or "production").strip().lower() in _NON_PRODUCTION:
        return requested
    provider = provider_from_env(env)
    return provider.mode if provider else "none"


def verification_required(env: Mapping[str, str] | None = None) -> bool:
    """Must NEW self-registered accounts verify their mobile number? Only when REQUIRE_PHONE_VERIFICATION is on AND a code can
    really be delivered; otherwise requiring it would lock every new user out."""
    env = os.environ if env is None else env
    wanted = str(env.get("REQUIRE_PHONE_VERIFICATION", "false")).strip().lower() in ("1", "true", "yes", "on")
    return wanted and delivery_mode(env) != "none"


def send_code(to: str, code: str, ttl_minutes: int, env: Mapping[str, str] | None = None, transport: Optional[Transport] = None) -> SmsResult:
    env = os.environ if env is None else env
    dev = delivery_mode(env)
    if dev == "outbox":
        OUTBOX.append((to, code))
        return SmsResult(True, dev)
    if dev == "console":
        print(f"[DEV ONLY] SMS code for {mask(to)}: {code}", flush=True)
        return SmsResult(True, dev)
    provider = provider_from_env(env, transport)
    if provider is None:
        return SmsResult(False, "none")
    return provider.send_otp(to, code, ttl_minutes)
