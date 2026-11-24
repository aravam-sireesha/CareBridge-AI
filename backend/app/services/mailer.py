"""Outbound e-mail through any SMTP provider (Brevo, Amazon SES, SendGrid, Mailgun, a company relay...).

Configuration (environment only): SMTP_HOST, SMTP_PORT, SMTP_FROM, SMTP_USERNAME, SMTP_PASSWORD, SMTP_STARTTLS (default
true), SMTP_SSL (true for implicit TLS on port 465). Nothing is sent unless SMTP_HOST and SMTP_FROM are both set.

Honesty rule: `MailResult.accepted` means the SMTP server accepted the message for delivery. It does NOT mean the
recipient received it, and nothing here reports "delivered". Bounces arrive later and are out of band.

The account-recovery / OTP / registration-verification mails keep using services/otp.py; this module is for
notification mail (need decisions, donation confirmations, delivery alerts), normally called from a background job.
"""
from __future__ import annotations

import html
import logging
import os
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr
from typing import Callable, Mapping, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MailResult:
    accepted: bool
    code: str            # accepted | not_configured | invalid_address | rejected | connection_error | temporary_error
    retryable: bool = False


def is_configured(env: Optional[Mapping[str, str]] = None) -> bool:
    env = os.environ if env is None else env
    return bool((env.get("SMTP_HOST") or "").strip() and (env.get("SMTP_FROM") or "").strip())


def _clean_header(value: str) -> str:
    """Header injection guard: a subject or address can never carry a line break."""
    return " ".join(str(value).replace("\r", " ").replace("\n", " ").split())


def valid_address(value: str) -> bool:
    _, addr = parseaddr(value or "")
    return bool(addr) and "@" in addr and " " not in addr and len(addr) <= 254 and "\n" not in value and "\r" not in value


def build_message(sender: str, to: str, subject: str, text: str, html_body: Optional[str] = None) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = _clean_header(sender)
    msg["To"] = _clean_header(to)
    msg["Subject"] = _clean_header(subject)[:200]
    msg["Date"] = formatdate(localtime=False)
    msg["Message-ID"] = make_msgid(domain=(parseaddr(sender)[1].split("@")[-1] or "carebridge.local"))
    msg.set_content(text)
    if html_body:
        msg.add_alternative(html_body, subtype="html")
    return msg


def send(to: str, subject: str, text: str, html_body: Optional[str] = None, env: Optional[Mapping[str, str]] = None,
         smtp_factory: Optional[Callable] = None) -> MailResult:
    env = os.environ if env is None else env
    if not is_configured(env):
        return MailResult(False, "not_configured")
    if not valid_address(to):
        return MailResult(False, "invalid_address")
    msg = build_message(env["SMTP_FROM"], to, subject, text, html_body)
    host, port = env["SMTP_HOST"].strip(), int(env.get("SMTP_PORT") or 587)
    use_ssl = str(env.get("SMTP_SSL", "false")).lower() == "true"
    starttls = str(env.get("SMTP_STARTTLS", "true")).lower() == "true"
    try:
        if smtp_factory is not None:
            client_cm = smtp_factory(host, port)
        elif use_ssl:
            client_cm = smtplib.SMTP_SSL(host, port, timeout=15, context=ssl.create_default_context())
        else:
            client_cm = smtplib.SMTP(host, port, timeout=15)
        with client_cm as client:
            if starttls and not use_ssl:
                client.starttls(context=ssl.create_default_context())
            if env.get("SMTP_USERNAME") and env.get("SMTP_PASSWORD"):
                client.login(env["SMTP_USERNAME"], env["SMTP_PASSWORD"])
            client.send_message(msg)
        return MailResult(True, "accepted")
    except smtplib.SMTPRecipientsRefused:
        return MailResult(False, "rejected")                       # permanent: do not retry
    except smtplib.SMTPResponseException as exc:
        retryable = 400 <= int(exc.smtp_code) < 500
        logger.warning("SMTP error %s", exc.smtp_code)               # the code only: provider text can echo the address
        return MailResult(False, "temporary_error" if retryable else "rejected", retryable)
    except (OSError, smtplib.SMTPException) as exc:
        logger.warning("SMTP connection problem (%s)", type(exc).__name__)
        return MailResult(False, "connection_error", True)


# --------------------------------------------------------------------------- templates
# Plain text first (always readable), with a simple HTML twin. Values are escaped for HTML; links must be same-site paths.
TEMPLATES: dict[str, tuple[str, str]] = {
    "need_approved": ("Your need was approved", "Your need \"{title}\" was approved and is now visible to donors and volunteers."),
    "need_rejected": ("Your need was not approved", "Your need \"{title}\" was not approved.\nReason: {reason}"),
    "donation_confirmed": ("Thank you: your donation commitment is recorded", "Your commitment for \"{title}\" is recorded. We will tell you as it moves forward."),
    "delivery_offered": ("A delivery needs a volunteer", "A delivery for \"{title}\" is waiting for you. Open CareBridge to accept or decline."),
    "delivery_assigned": ("A volunteer accepted the delivery", "A volunteer accepted the delivery for \"{title}\"."),
    "delivery_delayed": ("A delivery is running late", "The delivery for \"{title}\" has not progressed as expected. An administrator has been notified."),
    "delivery_completed": ("Delivery completed", "The delivery for \"{title}\" was marked delivered. Please confirm the quantity you received."),
    "receipt_required": ("Please confirm what you received", "The delivery for \"{title}\" is waiting for your receipt confirmation."),
    "generic": ("{title}", "{title}"),
    "verification_decided": ("Your verification was reviewed", "Your verification status is now: {status}."),
}


class _Safe(dict):
    def __missing__(self, key):          # a missing placeholder renders empty instead of raising inside a worker
        return ""


def render(kind: str, base_url: str = "", link: Optional[str] = None, **ctx) -> tuple[str, str, str]:
    """(subject, text, html). Unknown kinds raise KeyError so a typo is caught by the first test, not by a user."""
    subject, body = TEMPLATES[kind]
    data = _Safe({k: _clean_header(v) if k != "reason" else str(v)[:300] for k, v in ctx.items()})
    subject = subject.format_map(data)[:200] or "CareBridge notification"
    text = body.format_map(data)
    url = None
    if link and link.startswith("/") and not link.startswith("//") and base_url:
        url = base_url.rstrip("/") + link
        text += f"\n\nOpen: {url}"
    text += "\n\nCareBridge AI: Connecting Hearts, Fulfilling Needs."
    safe_html = "<p>" + html.escape(body.format_map(data)).replace("\n", "<br>") + "</p>"
    if url:
        safe_html += f'<p><a href="{html.escape(url, quote=True)}">Open CareBridge</a></p>'
    safe_html += "<p style=\"color:#65766F\">CareBridge AI: Connecting Hearts, Fulfilling Needs.</p>"
    return subject, text, safe_html
