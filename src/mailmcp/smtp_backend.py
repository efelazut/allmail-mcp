"""SMTP sending."""
from __future__ import annotations

import os
import smtplib
import socket
import ssl
from email.message import EmailMessage
from email.utils import getaddresses, make_msgid

from .config import Account
from .errors import MailServerError


def _plaintext_allowed() -> bool:
    return os.environ.get("MAILMCP_ALLOW_PLAINTEXT_FOR_TESTS") == "1"


def send_message(account: Account, password: str, msg: EmailMessage, timeout: float = 30) -> str:
    """Send via SMTP_SSL (security 'ssl') or SMTP + STARTTLS ('starttls'), verified TLS context.
    Return the Message-ID. Raise errors.MailServerError (no password in message)."""
    security = account.smtp_security
    if security not in ("ssl", "starttls") and not (security == "plain" and _plaintext_allowed()):
        raise MailServerError(f"Unsupported SMTP security mode {security!r}; use 'ssl' or 'starttls'.")
    if not msg["Message-ID"]:
        msg["Message-ID"] = make_msgid(domain=account.email.rpartition("@")[2] or None)
    message_id = str(msg["Message-ID"])
    recipients = [a for _, a in getaddresses(
        [str(v) for h in ("To", "Cc", "Bcc") for v in msg.get_all(h, [])]) if a]
    if not recipients:
        raise MailServerError("The message has no recipients.")

    ctx = ssl.create_default_context()
    try:
        if security == "ssl":
            client: smtplib.SMTP = smtplib.SMTP_SSL(
                account.smtp_host, account.smtp_port, timeout=timeout, context=ctx)
        else:
            client = smtplib.SMTP(account.smtp_host, account.smtp_port, timeout=timeout)
        with client:
            client.ehlo()
            if security == "starttls":
                client.starttls(context=ctx)
                client.ehlo()
            client.login(account.username, password)
            # send_message() strips Bcc from the transmitted headers but still delivers to Bcc.
            client.send_message(msg, from_addr=account.email, to_addrs=recipients)
    except smtplib.SMTPAuthenticationError as exc:
        raise MailServerError(
            "SMTP login failed: check the app password (Gmail needs 2-Step Verification and an "
            f"app password; iCloud needs an app-specific password). Server said: {exc.smtp_code}."
        ) from None
    except smtplib.SMTPRecipientsRefused as exc:
        raise MailServerError(
            "The server refused the recipient(s): " + ", ".join(sorted(exc.recipients))) from None
    except smtplib.SMTPSenderRefused:
        raise MailServerError(
            f"The server refused the sender address {account.email}.") from None
    except smtplib.SMTPException as exc:
        raise MailServerError(f"SMTP error: {type(exc).__name__}: {_safe(exc, password)}") from None
    except ssl.SSLError as exc:
        raise MailServerError(
            f"TLS error talking to {account.smtp_host}:{account.smtp_port} ({exc.reason or 'ssl error'}). "
            "Check the port/security setting.") from None
    except (socket.timeout, TimeoutError):
        raise MailServerError(f"Timed out connecting to {account.smtp_host}:{account.smtp_port}.") from None
    except OSError as exc:
        raise MailServerError(
            f"Cannot reach {account.smtp_host}:{account.smtp_port} ({type(exc).__name__}).") from None
    return message_id


def _safe(exc: Exception, password: str) -> str:
    text = str(exc)
    return text.replace(password, "***") if password else text
