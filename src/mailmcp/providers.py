"""Find IMAP/SMTP settings for an email address."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ServerSettings:
    provider: str
    imap_host: str
    imap_port: int
    imap_security: str      # "ssl" | "starttls"
    smtp_host: str
    smtp_port: int
    smtp_security: str
    smtp_saves_sent: bool = False
    app_password_url: str | None = None   # where the user creates an app password
    notes: str | None = None              # short human hint (e.g. "Requires 2-Step Verification")
    source: str = "builtin"               # "builtin" | "autoconfig" | "guess" | "manual"


def is_microsoft(domain: str) -> bool:
    """outlook.com, hotmail.*, live.*, msn.com, passport.com ... (personal Microsoft)."""
    raise NotImplementedError


def lookup(email: str, allow_network: bool = True) -> ServerSettings | None:
    """Builtin table first (gmail/googlemail, icloud/me/mac, yandex.*/ya.ru, zoho*, fastmail*, yahoo*,
    gmx.*, aol.com, mail.ru, proton? -> None (Proton needs Bridge)). Then Thunderbird autoconfig
    (if allow_network and env MAILMCP_NO_AUTOCONFIG unset), then None.
    Raise errors.ProviderNotSupported for Microsoft domains (message: Outlook/Hotmail support arrives in v0.2)."""
    raise NotImplementedError


def guess(email: str) -> ServerSettings:
    """Last resort: imap.<domain>:993 ssl, smtp.<domain>:465 ssl, source='guess'."""
    raise NotImplementedError
