"""SMTP sending."""
from __future__ import annotations

from email.message import EmailMessage

from .config import Account


def send_message(account: Account, password: str, msg: EmailMessage, timeout: float = 30) -> str:
    """Send via SMTP_SSL (security 'ssl') or SMTP + STARTTLS ('starttls'), verified TLS context.
    Return the Message-ID. Raise errors.MailServerError (no password in message)."""
    raise NotImplementedError
