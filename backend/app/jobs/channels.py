"""The outbound-channel jobs (push, e-mail, SMS). Dependencies are imported lazily or injected, so this module has no database imports and
is unit-tested directly. jobs/handlers.py registers these under their job names."""
from __future__ import annotations

from ..services import mailer, sms
from .jobqueue import JobContext, PermanentError, RetryableError


def push_deliver(payload: dict, ctx: JobContext, deliver=None) -> None:
    if deliver is None:
        from ..services import push_dispatch
        deliver = push_dispatch.deliver
    if deliver(int(payload["event_id"]), final=ctx.is_final) == "retry":
        raise RetryableError("push_service_busy")


def email_send(payload: dict, ctx: JobContext, send=mailer.send, configured=mailer.is_configured) -> None:
    if not configured():
        raise PermanentError("email_not_configured")
    try:
        subject, text, html = mailer.render(payload["template"], base_url=payload.get("base_url", ""), link=payload.get("link"), **(payload.get("ctx") or {}))
    except KeyError:
        raise PermanentError("unknown_template") from None
    result = send(payload["to"], subject, text, html)
    if result.accepted:
        return
    raise (RetryableError(result.code) if result.retryable else PermanentError(result.code))


def sms_send(payload: dict, ctx: JobContext, provider=None) -> None:
    """Free-text SMS (Twilio only). MSG91 and Indian DLT rules require a registered TEMPLATE, so free text is refused there rather than sent unsafely."""
    p = provider or sms.provider_from_env()
    if p is None:
        raise PermanentError("sms_not_configured")
    if not hasattr(p, "send"):
        raise PermanentError("provider_requires_template")
    if not p.send(payload["to"], str(payload["text"])[:320]).ok:
        raise RetryableError("sms_failed")
