"""WhatsApp Business Cloud API (Meta) adapter: PREPARED AND DISABLED.

Off unless WHATSAPP_ENABLED=true AND WHATSAPP_PHONE_NUMBER_ID and WHATSAPP_ACCESS_TOKEN are set. Even then:
* TEMPLATE-ONLY. Business-initiated WhatsApp messages must use a template Meta has approved. The caller picks a PURPOSE
  (delivery_update, donation_confirmation, need_notice); the template NAME comes from the environment, never from the caller, and free
  text is never sent. OTP codes are not supported: WhatsApp's policies for authentication messages are separate and not enabled here.
* CONSENT. The caller (jobs/handlers.py) only sends to someone who switched WhatsApp on for themselves and has a verified phone.
* HONEST STATUS. "accepted" = Meta accepted the request. Delivery/read receipts arrive by webhook, which is NOT implemented, so nothing
  here says "delivered".
Needs before live use: a verified Meta Business account, a registered number, approved templates (names + parameter counts must match the
env settings), and a test against the live API. None of that exists yet; tests use a fake transport.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Mapping, Optional

from . import maps_http
from .sms import normalize_phone

PURPOSES = {"delivery_update": "WHATSAPP_TEMPLATE_DELIVERY_UPDATE", "donation_confirmation": "WHATSAPP_TEMPLATE_DONATION_CONFIRMATION", "need_notice": "WHATSAPP_TEMPLATE_NEED_NOTICE"}
MAX_PARAMS, MAX_PARAM_LEN = 5, 60
_TEMPLATE = re.compile(r"^[a-z0-9_]{1,512}$")
PERMANENT_META_CODES = {131030, 131026, 132000, 132001, 132005, 132007, 132012, 131009, 100, 33}     # not opted in / unreachable / template or parameter mismatch
CONFIG_META_CODES = {190, 10, 200, 368, 131031}                                                       # token invalid, permission, account locked


@dataclass(frozen=True)
class WhatsAppResult:
    status: str     # accepted | not_configured | invalid | retry | failed
    code: str = ""


def enabled(env: Mapping[str, str]) -> bool:
    return (str(env.get("WHATSAPP_ENABLED", "")).strip().lower() == "true" and bool((env.get("WHATSAPP_PHONE_NUMBER_ID") or "").strip())
            and bool((env.get("WHATSAPP_ACCESS_TOKEN") or "").strip()))


def template_for(purpose: str, env: Mapping[str, str]) -> Optional[str]:
    name = (env.get(PURPOSES.get(purpose, ""), "") or "").strip()
    return name if _TEMPLATE.match(name) else None


def clean_params(params: object) -> Optional[list[str]]:
    """Template parameters: short single-line text only (WhatsApp rejects newlines/tabs and overlong values)."""
    if not isinstance(params, (list, tuple)) or len(params) > MAX_PARAMS:
        return None
    out = []
    for p in params:
        text = " ".join(str(p).split())[:MAX_PARAM_LEN]
        if not text:
            return None                                   # an empty parameter makes Meta reject the whole message
        out.append(text)
    return out


def build_payload(to_e164: str, template: str, params: list[str], language: str = "en") -> dict:
    return {"messaging_product": "whatsapp", "to": to_e164.lstrip("+"), "type": "template",
            "template": {"name": template, "language": {"code": language},
                         "components": [{"type": "body", "parameters": [{"type": "text", "text": p} for p in params]}] if params else []}}


def send_template(to: str, purpose: str, params: object, env: Mapping[str, str], transport: Optional[Callable] = None, language: str = "en") -> WhatsAppResult:
    if not enabled(env):
        return WhatsAppResult("not_configured")
    phone = normalize_phone(to)
    template = template_for(purpose, env)
    values = clean_params(params)
    if phone is None or template is None or values is None:
        return WhatsAppResult("invalid", "bad_input" if template else "no_template")
    url = f"https://graph.facebook.com/{(env.get('WHATSAPP_API_VERSION') or 'v21.0').strip()}/{env['WHATSAPP_PHONE_NUMBER_ID'].strip()}/messages"
    headers = {"Authorization": f"Bearer {env['WHATSAPP_ACCESS_TOKEN'].strip()}", "Content-Type": "application/json"}
    try:
        status, data = (transport or maps_http.request)("POST", url, headers=headers, json=build_payload(phone, template, values, language), timeout=8.0)
    except maps_http.MapsError:
        return WhatsAppResult("retry", "unreachable")
    if 200 <= status < 300 and isinstance(data, dict) and data.get("messages"):
        return WhatsAppResult("accepted", str(status))
    err = (data.get("error") if isinstance(data, dict) else None) or {}
    meta = err.get("code") if isinstance(err.get("code"), int) else None
    if status == 429 or status >= 500 or meta in (4, 80007, 130429, 131048, 131056):      # throttled / spam rate limit / pair rate limit
        return WhatsAppResult("retry", str(meta or status))
    if meta in CONFIG_META_CODES:
        return WhatsAppResult("failed", f"config_{meta}")
    return WhatsAppResult("failed", str(meta or status))
