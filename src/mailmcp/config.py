"""Accounts and settings on disk (JSON). Never stores secrets."""
from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from .errors import AccountNotFound, ConfigError

CONFIG_VERSION = 1


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
        key = (account_id_or_email or "").strip().lower()
        for acc in self.accounts.values():
            if acc.id.lower() == key or acc.email.lower() == key:
                return acc
        valid = ", ".join(sorted(self.accounts)) or "none configured yet"
        raise AccountNotFound(f"Unknown account {account_id_or_email!r}. Valid account ids: {valid}")


def config_dir() -> Path:
    """$MAILMCP_HOME if set, else platformdirs.user_config_dir("mailmcp", appauthor=False). Created if missing."""
    override = os.environ.get("MAILMCP_HOME")
    if override:
        path = Path(override).expanduser()
    else:
        from platformdirs import user_config_dir

        path = Path(user_config_dir("mailmcp", appauthor=False))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _config_path() -> Path:
    return config_dir() / "config.json"


def _from_dict(cls, data: dict):
    """Build a dataclass from a dict, ignoring unknown keys (forward compatible)."""
    names = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in data.items() if k in names})


def load_config() -> Config:
    """Read config.json; missing file -> empty Config. Unknown keys ignored (forward compatible)."""
    path = _config_path()
    if not path.exists():
        return Config()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("top level must be an object")
        accounts: dict[str, Account] = {}
        for acc_id, data in (raw.get("accounts") or {}).items():
            data = dict(data)
            data.setdefault("id", acc_id)
            accounts[acc_id] = _from_dict(Account, data)
        settings = _from_dict(Settings, raw.get("settings") or {})
    except (ValueError, TypeError, AttributeError) as exc:
        raise ConfigError(f"Could not read {path}: {exc}") from exc
    return Config(accounts=accounts, settings=settings)


def save_config(cfg: Config) -> None:
    """Atomic write (temp file + os.replace) of config.json with a "version": 1 field."""
    path = _config_path()
    payload = {
        "version": CONFIG_VERSION,
        "accounts": {k: asdict(v) for k, v in cfg.accounts.items()},
        "settings": asdict(cfg.settings),
    }
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".config-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def make_account_id(email: str, existing: set[str]) -> str:
    """Readable unique slug, e.g. 'efe@gmail.com' -> 'efe-gmail', then 'efe-gmail-2'."""
    local, _, domain = email.strip().lower().partition("@")
    label = domain.split(".")[0] if domain else ""
    slug = re.sub(r"[^a-z0-9]+", "-", f"{local}-{label}").strip("-") or "account"
    candidate, n = slug, 2
    while candidate in existing:
        candidate = f"{slug}-{n}"
        n += 1
    return candidate
