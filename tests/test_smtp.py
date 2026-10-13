"""SMTP backend against a local aiosmtpd server (plaintext allowed only via the test env var)."""
from __future__ import annotations

import smtplib
from email import message_from_bytes, policy

import pytest
from aiosmtpd.controller import Controller
from aiosmtpd.smtp import AuthResult, LoginPassword

from mailmcp import compose, smtp_backend
from mailmcp.errors import MailServerError

from conftest import free_port

PASSWORD = "correct-horse-battery"


class Capture:
    def __init__(self):
        self.messages = []

    async def handle_DATA(self, server, session, envelope):
        self.messages.append(envelope)
        return "250 OK"


def authenticator(server, session, envelope, mechanism, auth_data):
    if isinstance(auth_data, LoginPassword) and auth_data.password == PASSWORD.encode():
        return AuthResult(success=True)
    return AuthResult(success=False, handled=False)


@pytest.fixture
def smtp_server(monkeypatch):
    monkeypatch.setenv("MAILMCP_ALLOW_PLAINTEXT_FOR_TESTS", "1")
    handler = Capture()
    port = free_port()
    controller = Controller(handler, hostname="127.0.0.1", port=port, authenticator=authenticator,
                            auth_required=True, auth_require_tls=False, ready_timeout=30)
    controller.start()
    handler.port = port
    yield handler
    controller.stop()


@pytest.fixture
def account(make_account, smtp_server):
    return make_account(smtp_host="127.0.0.1", smtp_port=smtp_server.port, smtp_security="plain",
                        username="efe@gmail.com")


def test_send_delivers_and_returns_message_id(account, smtp_server):
    msg = compose.build_message(account, "a@example.com", "Çarşamba", "Merhaba, görüşürüz.")
    mid = smtp_backend.send_message(account, PASSWORD, msg)
    assert mid == str(msg["Message-ID"])
    [env] = smtp_server.messages
    assert env.mail_from == "efe@gmail.com" and env.rcpt_tos == ["a@example.com"]
    got = message_from_bytes(env.content, policy=policy.default)
    assert got["Subject"] == "Çarşamba" and "görüşürüz" in got.get_content()
    assert got["Message-ID"] == mid


def test_bcc_not_in_headers_but_in_envelope(account, smtp_server):
    msg = compose.build_message(account, "a@example.com", "s", "b", cc="c@example.com",
                                bcc=["secret@example.com", "Hidden <h2@example.com>"])
    smtp_backend.send_message(account, PASSWORD, msg)
    [env] = smtp_server.messages
    assert sorted(env.rcpt_tos) == sorted(
        ["a@example.com", "c@example.com", "secret@example.com", "h2@example.com"])
    raw = env.content.decode("utf-8", "replace").lower()
    assert "bcc" not in raw and "secret@example.com" not in raw and "h2@example.com" not in raw
    assert "cc: c@example.com" in raw


def test_message_not_mutated_so_bcc_survives_for_sent_copy(account, smtp_server):
    msg = compose.build_message(account, "a@example.com", "s", "b", bcc="secret@example.com")
    smtp_backend.send_message(account, PASSWORD, msg)
    assert str(msg["Bcc"]) == "secret@example.com"


def test_bad_password_gives_friendly_error_without_secret(account, smtp_server):
    msg = compose.build_message(account, "a@example.com", "s", "b")
    with pytest.raises(MailServerError) as exc:
        smtp_backend.send_message(account, "wrong-password-123", msg)
    text = str(exc.value)
    assert "app password" in text and "wrong-password-123" not in text
    assert smtp_server.messages == []


def test_connection_refused_is_friendly(make_account, monkeypatch):
    monkeypatch.setenv("MAILMCP_ALLOW_PLAINTEXT_FOR_TESTS", "1")
    acc = make_account(smtp_host="127.0.0.1", smtp_port=free_port(), smtp_security="plain")
    msg = compose.build_message(acc, "a@example.com", "s", "b")
    with pytest.raises(MailServerError, match="Cannot reach"):
        smtp_backend.send_message(acc, "pw", msg, timeout=3)


def test_plain_rejected_without_test_env(make_account):
    acc = make_account(smtp_host="127.0.0.1", smtp_port=25, smtp_security="plain")
    msg = compose.build_message(acc, "a@example.com", "s", "b")
    with pytest.raises(MailServerError, match="Unsupported SMTP security"):
        smtp_backend.send_message(acc, "pw", msg)


def test_no_recipients_rejected(account):
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["From"] = "efe@gmail.com"
    msg.set_content("x")
    with pytest.raises(MailServerError, match="no recipients"):
        smtp_backend.send_message(account, PASSWORD, msg)


def test_ssl_and_starttls_use_verifying_context(make_account, monkeypatch):
    """Without a real TLS server, check which smtplib class/context is used for each mode."""
    import ssl

    calls = []

    class FakeSMTP:
        def __init__(self, host, port, timeout=None, context=None):
            calls.append((type(self).__name__, host, port, context))

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def ehlo(self):
            pass

        def starttls(self, context=None):
            calls.append(("starttls", context))

        def login(self, u, p):
            calls.append(("login", u))

        def send_message(self, msg, from_addr=None, to_addrs=None):
            calls.append(("send", from_addr, tuple(to_addrs)))

    class FakeSMTP_SSL(FakeSMTP):
        pass

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP_SSL)

    acc = make_account()
    smtp_backend.send_message(acc, "pw", compose.build_message(acc, "a@x.com", "s", "b"))
    assert calls[0][0] == "FakeSMTP_SSL" and calls[0][1:3] == ("smtp.gmail.com", 465)
    ctx = calls[0][3]
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname

    calls.clear()
    acc2 = make_account(smtp_host="smtp.mail.me.com", smtp_port=587, smtp_security="starttls")
    smtp_backend.send_message(acc2, "pw", compose.build_message(acc2, "a@x.com", "s", "b"))
    assert calls[0][0] == "FakeSMTP" and calls[0][2] == 587
    assert calls[1][0] == "starttls" and calls[1][1].verify_mode == ssl.CERT_REQUIRED
    assert ("login", acc2.username) in calls and calls[-1][0] == "send"
