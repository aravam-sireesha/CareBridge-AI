"""Mailer: never claims more than 'accepted', blocks header injection, classifies failures for the retry policy."""
import smtplib

import pytest

from app.services import mailer

ENV = {"SMTP_HOST": "smtp.example.test", "SMTP_PORT": "587", "SMTP_FROM": "CareBridge <no-reply@example.test>",
       "SMTP_USERNAME": "user", "SMTP_PASSWORD": "pw"}


class FakeSMTP:
    instances = []

    def __init__(self, host, port, fail=None):
        self.host, self.port, self.fail, self.calls, self.sent = host, port, fail, [], None
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, context=None):
        self.calls.append("starttls")

    def login(self, u, p):
        self.calls.append("login")

    def send_message(self, msg):
        if self.fail:
            raise self.fail
        self.sent = msg
        self.calls.append("send")


def factory(fail=None):
    return lambda host, port: FakeSMTP(host, port, fail)


def test_not_configured_sends_nothing():
    r = mailer.send("a@b.org", "s", "t", env={}, smtp_factory=factory())
    assert (r.accepted, r.code) == (False, "not_configured")


def test_accepted_path_uses_starttls_then_login_then_send():
    FakeSMTP.instances.clear()
    r = mailer.send("a@b.org", "Hello", "Body", env=ENV, smtp_factory=factory())
    assert (r.accepted, r.code, r.retryable) == (True, "accepted", False)
    assert FakeSMTP.instances[0].calls == ["starttls", "login", "send"]


@pytest.mark.parametrize("bad", ["", "no-at-sign", "a b@c.org", "x@y.org\r\nBcc: evil@z.org"])
def test_invalid_addresses_are_refused_before_connecting(bad):
    FakeSMTP.instances.clear()
    r = mailer.send(bad, "s", "t", env=ENV, smtp_factory=factory())
    assert r.code == "invalid_address" and not FakeSMTP.instances


def test_subject_header_injection_is_neutralised():
    msg = mailer.build_message("a@b.org", "c@d.org", "Hi\r\nBcc: evil@z.org", "x")
    assert "\n" not in msg["Subject"] and "Bcc" not in msg.keys()


def test_permanent_refusal_is_not_retryable():
    r = mailer.send("a@b.org", "s", "t", env=ENV, smtp_factory=factory(smtplib.SMTPRecipientsRefused({"a@b.org": (550, b"x")})))
    assert (r.accepted, r.code, r.retryable) == (False, "rejected", False)


def test_4xx_is_temporary_and_retryable():
    r = mailer.send("a@b.org", "s", "t", env=ENV, smtp_factory=factory(smtplib.SMTPResponseException(451, b"try later")))
    assert (r.code, r.retryable) == ("temporary_error", True)


def test_5xx_is_permanent():
    r = mailer.send("a@b.org", "s", "t", env=ENV, smtp_factory=factory(smtplib.SMTPResponseException(554, b"no")))
    assert (r.code, r.retryable) == ("rejected", False)


def test_network_error_is_retryable():
    r = mailer.send("a@b.org", "s", "t", env=ENV, smtp_factory=factory(ConnectionRefusedError()))
    assert (r.accepted, r.code, r.retryable) == (False, "connection_error", True)


def test_render_escapes_html_and_only_links_same_site_paths():
    subject, text, html = mailer.render("need_rejected", base_url="https://app.example.org", link="/needs",
                                        title="<script>alert(1)</script>", reason="too vague")
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "https://app.example.org/needs" in text and "https://app.example.org/needs" in html
    _, text2, html2 = mailer.render("need_approved", base_url="https://app.example.org", link="//evil.example", title="t")
    assert "evil.example" not in text2 and "evil.example" not in html2
    _, text3, _ = mailer.render("need_approved", base_url="https://app.example.org", link="javascript:alert(1)", title="t")
    assert "javascript" not in text3


def test_render_unknown_template_fails_loudly_and_missing_placeholder_is_blank():
    with pytest.raises(KeyError):
        mailer.render("no_such_template")
    _, text, _ = mailer.render("need_approved")        # no title supplied: renders blank, does not crash a worker
    assert "approved" in text
