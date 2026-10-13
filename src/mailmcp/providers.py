"""Find IMAP/SMTP settings for an email address."""
from __future__ import annotations

import os
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from .errors import ProviderNotSupported

AUTOCONFIG_URL = "https://autoconfig.thunderbird.net/v1.1/{domain}"
_DOMAIN_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")


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
    notes_tr: str | None = None           # Turkish version of notes
    source: str = "builtin"               # "builtin" | "autoconfig" | "guess" | "manual"


_MS_LABELS = {"outlook", "hotmail", "live"}
_MS_DOMAINS = {"msn.com", "passport.com", "windowslive.com"}

_PROTON_DOMAINS = {"proton.me", "protonmail.com", "protonmail.ch", "pm.me"}


def _domain_of(email: str) -> str:
    return email.strip().rpartition("@")[2].lower().rstrip(".")


def is_microsoft(domain: str) -> bool:
    """outlook.com, hotmail.*, live.*, msn.com, passport.com ... (personal Microsoft)."""
    domain = domain.strip().lower().rstrip(".")
    if domain in _MS_DOMAINS:
        return True
    parts = domain.split(".")
    return len(parts) >= 2 and parts[0] in _MS_LABELS


_GMAIL = ServerSettings(
    provider="gmail", imap_host="imap.gmail.com", imap_port=993, imap_security="ssl",
    smtp_host="smtp.gmail.com", smtp_port=465, smtp_security="ssl", smtp_saves_sent=True,
    app_password_url="https://myaccount.google.com/apppasswords",
    notes=("Requires 2-Step Verification, then create an app password. Google Workspace "
           "accounts usually cannot use app passwords (the admin must allow them)."),
    notes_tr="2 Adımlı Doğrulama açık olmalı, sonra uygulama şifresi oluştur. Google Workspace (iş/okul) hesapları genelde uygulama şifresi kullanamaz (yöneticinin izin vermesi gerekir).",
)
_ICLOUD = ServerSettings(
    provider="icloud", imap_host="imap.mail.me.com", imap_port=993, imap_security="ssl",
    smtp_host="smtp.mail.me.com", smtp_port=587, smtp_security="starttls",
    app_password_url="https://account.apple.com",
    notes=("Use an app-specific password (Sign-In and Security > App-Specific Passwords) and "
           "your full iCloud address as the username."),
    notes_tr="Uygulamaya özel bir şifre kullan (Giriş ve Güvenlik > Uygulamaya Özel Şifreler) ve kullanıcı adı olarak tam iCloud adresini yaz.",
)
_YANDEX = ServerSettings(
    provider="yandex", imap_host="imap.yandex.com", imap_port=993, imap_security="ssl",
    smtp_host="smtp.yandex.com", smtp_port=465, smtp_security="ssl",
    app_password_url="https://id.yandex.com/security/app-passwords",
    notes=("Enable IMAP in Yandex Mail settings (Email clients) and use an app password."),
    notes_tr="Yandex Mail ayarlarında (E-posta istemcileri) IMAP'i aç ve uygulama şifresi kullan.",
)
_ZOHO = ServerSettings(
    provider="zoho", imap_host="imap.zoho.com", imap_port=993, imap_security="ssl",
    smtp_host="smtp.zoho.com", smtp_port=465, smtp_security="ssl",
    app_password_url="https://accounts.zoho.com/home#security/app_password",
    notes=("EU accounts use imap.zoho.eu / smtp.zoho.eu (add the account manually). "
           "Enable IMAP access in Zoho Mail settings."),
    notes_tr="AB hesapları imap.zoho.eu / smtp.zoho.eu kullanır (hesabı elle ekle). Zoho Mail ayarlarında IMAP erişimini aç.",
)
_FASTMAIL = ServerSettings(
    provider="fastmail", imap_host="imap.fastmail.com", imap_port=993, imap_security="ssl",
    smtp_host="smtp.fastmail.com", smtp_port=465, smtp_security="ssl",
    app_password_url="https://app.fastmail.com/settings/security/devices",
    notes="Create an app password with IMAP and SMTP access.",
    notes_tr="IMAP ve SMTP erişimi olan bir uygulama şifresi oluştur.",
)
_YAHOO = ServerSettings(
    provider="yahoo", imap_host="imap.mail.yahoo.com", imap_port=993, imap_security="ssl",
    smtp_host="smtp.mail.yahoo.com", smtp_port=465, smtp_security="ssl",
    app_password_url="https://login.yahoo.com/account/security/app-passwords",
    notes="Generate an app password in Account Security.",
    notes_tr="Hesap Güvenliği bölümünde bir uygulama şifresi oluştur.",
)
_GMX_COM = ServerSettings(
    provider="gmx", imap_host="imap.gmx.com", imap_port=993, imap_security="ssl",
    smtp_host="mail.gmx.com", smtp_port=587, smtp_security="starttls",
    notes="Enable IMAP/POP3 access in GMX settings (POP3 & IMAP).",
    notes_tr="GMX ayarlarında IMAP/POP3 erişimini aç (POP3 ve IMAP).",
)
_GMX_NET = ServerSettings(
    provider="gmx", imap_host="imap.gmx.net", imap_port=993, imap_security="ssl",
    smtp_host="mail.gmx.net", smtp_port=587, smtp_security="starttls",
    notes="Enable IMAP/POP3 access in GMX settings (POP3 & IMAP).",
    notes_tr="GMX ayarlarında IMAP/POP3 erişimini aç (POP3 ve IMAP).",
)
_AOL = ServerSettings(
    provider="aol", imap_host="imap.aol.com", imap_port=993, imap_security="ssl",
    smtp_host="smtp.aol.com", smtp_port=465, smtp_security="ssl",
    app_password_url="https://login.aol.com/account/security",
    notes="Generate an app password in Account Security.",
    notes_tr="Hesap Güvenliği bölümünde bir uygulama şifresi oluştur.",
)
_MAILRU = ServerSettings(
    provider="mail.ru", imap_host="imap.mail.ru", imap_port=993, imap_security="ssl",
    smtp_host="smtp.mail.ru", smtp_port=465, smtp_security="ssl",
    app_password_url="https://id.mail.ru/security",
    notes="Create an external-app password in Mail.ru security settings.",
    notes_tr="Mail.ru güvenlik ayarlarında harici uygulama şifresi oluştur.",
)

_BUILTIN: dict[str, ServerSettings] = {}
for _domains, _settings in (
    (("gmail.com", "googlemail.com"), _GMAIL),
    (("icloud.com", "me.com", "mac.com"), _ICLOUD),
    (("yandex.com", "yandex.ru", "yandex.com.tr", "yandex.ua", "yandex.kz", "yandex.by", "ya.ru"), _YANDEX),
    (("zoho.com", "zohomail.com"), _ZOHO),
    (("fastmail.com", "fastmail.fm"), _FASTMAIL),
    (("yahoo.com", "ymail.com", "rocketmail.com"), _YAHOO),
    (("gmx.com",), _GMX_COM),
    (("gmx.net", "gmx.de"), _GMX_NET),
    (("aol.com",), _AOL),
    (("mail.ru",), _MAILRU),
):
    for _d in _domains:
        _BUILTIN[_d] = _settings


def _builtin(domain: str) -> ServerSettings | None:
    s = _BUILTIN.get(domain)
    if s is None and domain.startswith("yandex."):
        s = _YANDEX
    return None if s is None else ServerSettings(**s.__dict__)


def lookup(email: str, allow_network: bool = True) -> ServerSettings | None:
    """Builtin table first, then Thunderbird autoconfig (if allow_network and env MAILMCP_NO_AUTOCONFIG
    unset), then None. Raises errors.ProviderNotSupported for Proton and personal Microsoft domains."""
    domain = _domain_of(email)
    if domain in _PROTON_DOMAINS:
        raise ProviderNotSupported(
            "Proton requires Proton Mail Bridge; add it manually with Bridge's host/port."
        )
    if is_microsoft(domain):
        raise ProviderNotSupported(
            "Outlook/Hotmail/Live accounts are not supported yet: Microsoft turned off "
            "password login for IMAP, so they need OAuth. Support arrives in v0.2."
        )
    found = _builtin(domain)
    if found is not None:
        return found
    if allow_network and not os.environ.get("MAILMCP_NO_AUTOCONFIG"):
        return _autoconfig(domain)
    return None


def _autoconfig(domain: str) -> ServerSettings | None:
    if not _DOMAIN_RE.match(domain):
        return None
    try:
        with urllib.request.urlopen(AUTOCONFIG_URL.format(domain=domain), timeout=5) as resp:
            data = resp.read(262144)
    except (OSError, urllib.error.URLError, ValueError):
        return None
    return _parse_autoconfig(data, domain)


def _parse_autoconfig(data: bytes, domain: str) -> ServerSettings | None:
    """Parse Thunderbird clientConfig XML; None if no usable (encrypted) IMAP+SMTP pair."""
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        return None  # refuse DTDs/entities from the network
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return None

    def pick(kind: str) -> tuple[str, int, str] | None:
        best: tuple[str, int, str] | None = None
        for srv in root.iter(f"{kind}Server"):
            if (srv.get("type") or "").lower() != ("imap" if kind == "incoming" else "smtp"):
                continue
            host = (srv.findtext("hostname") or "").strip()
            port_s = (srv.findtext("port") or "").strip()
            sock = (srv.findtext("socketType") or "").strip().upper()
            security = {"SSL": "ssl", "STARTTLS": "starttls"}.get(sock)
            if not host or not port_s.isdigit() or security is None:
                continue
            host = host.replace("%EMAILDOMAIN%", domain)
            if "%" in host or not _DOMAIN_RE.match(host.lower()):
                continue
            cand = (host, int(port_s), security)
            if best is None or (security == "ssl" and best[2] != "ssl"):
                best = cand
        return best

    imap, smtp = pick("incoming"), pick("outgoing")
    if imap is None or smtp is None:
        return None
    return ServerSettings(
        provider=domain, imap_host=imap[0], imap_port=imap[1], imap_security=imap[2],
        smtp_host=smtp[0], smtp_port=smtp[1], smtp_security=smtp[2], source="autoconfig",
    )


def guess(email: str) -> ServerSettings:
    """Last resort: imap.<domain>:993 ssl, smtp.<domain>:465 ssl, source='guess'."""
    domain = _domain_of(email)
    return ServerSettings(
        provider="custom", imap_host=f"imap.{domain}", imap_port=993, imap_security="ssl",
        smtp_host=f"smtp.{domain}", smtp_port=465, smtp_security="ssl", source="guess",
    )
