"""Accounts and settings on disk (JSON). Never stores secrets."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Account:
    id: str
    email: str
    display_name: str
    provider: str            # e.g. "gmail", "icloud", "yandex", "custom"
    imap_host: str
    imap_port: int
    imap_security: str       # "ssl" | "starttls"
    smtp_host: str
    smtp_port: int
    smtp_security: str       # "ssl" | "starttls"
    username: str
    smtp_saves_sent: bool = False   # True when the provider stores a Sent copy itself (Gmail)


@dataclass
class Settings:
    send_approval: bool = True
    trash_approval: bool = True
    autoconfig_lookup: bool = True


@dataclass
class Config:
    accounts: dict[str, Account] = field(default_factory=dict)
    settings: Settings = field(default_factory=Settings)

    def get(self, account_id_or_email: str) -> Account:
        """Find by id or email (case-insensitive). Raise errors.AccountNotFound listing valid ids."""
        raise NotImplementedError


def config_dir() -> Path:
    """$MAILMCP_HOME if set, else platformdirs.user_config_dir("mailmcp", appauthor=False). Created if missing."""
    raise NotImplementedError


def load_config() -> Config:
    """Read config.json; missing file -> empty Config. Unknown keys ignored (forward compatible)."""
    raise NotImplementedError


def save_config(cfg: Config) -> None:
    """Atomic write (temp file + os.replace) of config.json with a "version": 1 field."""
    raise NotImplementedError


def make_account_id(email: str, existing: set[str]) -> str:
    """Readable unique slug, e.g. 'efe@gmail.com' -> 'efe-gmail', then 'efe-gmail-2'."""
    raise NotImplementedError
