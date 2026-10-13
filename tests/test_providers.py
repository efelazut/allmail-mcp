import io
import urllib.error

import pytest

from mailmcp import providers
from mailmcp.errors import ProviderNotSupported


@pytest.mark.parametrize("email, imap, imap_port, smtp, smtp_port, smtp_sec", [
    ("a@gmail.com", "imap.gmail.com", 993, "smtp.gmail.com", 465, "ssl"),
    ("a@googlemail.com", "imap.gmail.com", 993, "smtp.gmail.com", 465, "ssl"),
    ("a@icloud.com", "imap.mail.me.com", 993, "smtp.mail.me.com", 587, "starttls"),
    ("a@me.com", "imap.mail.me.com", 993, "smtp.mail.me.com", 587, "starttls"),
    ("a@mac.com", "imap.mail.me.com", 993, "smtp.mail.me.com", 587, "starttls"),
    ("a@yandex.com", "imap.yandex.com", 993, "smtp.yandex.com", 465, "ssl"),
    ("a@yandex.com.tr", "imap.yandex.com", 993, "smtp.yandex.com", 465, "ssl"),
    ("a@ya.ru", "imap.yandex.com", 993, "smtp.yandex.com", 465, "ssl"),
    ("a@zoho.com", "imap.zoho.com", 993, "smtp.zoho.com", 465, "ssl"),
    ("a@fastmail.com", "imap.fastmail.com", 993, "smtp.fastmail.com", 465, "ssl"),
    ("a@yahoo.com", "imap.mail.yahoo.com", 993, "smtp.mail.yahoo.com", 465, "ssl"),
    ("a@gmx.com", "imap.gmx.com", 993, "mail.gmx.com", 587, "starttls"),
    ("a@gmx.de", "imap.gmx.net", 993, "mail.gmx.net", 587, "starttls"),
    ("a@aol.com", "imap.aol.com", 993, "smtp.aol.com", 465, "ssl"),
    ("a@mail.ru", "imap.mail.ru", 993, "smtp.mail.ru", 465, "ssl"),
])
def test_builtin_table(email, imap, imap_port, smtp, smtp_port, smtp_sec, monkeypatch):
    monkeypatch.setattr(providers.urllib.request, "urlopen",
                        lambda *a, **k: pytest.fail("network used for a builtin provider"))
    s = providers.lookup(email)
    assert s is not None and s.source == "builtin"
    assert (s.imap_host, s.imap_port, s.imap_security) == (imap, imap_port, "ssl")
    assert (s.smtp_host, s.smtp_port, s.smtp_security) == (smtp, smtp_port, smtp_sec)


def test_gmail_details():
    s = providers.lookup("Someone@GMAIL.com")
    assert s.smtp_saves_sent is True
    assert s.app_password_url == "https://myaccount.google.com/apppasswords"
    assert "2-Step" in s.notes and "Workspace" in s.notes


def test_other_providers_do_not_claim_saved_sent():
    assert providers.lookup("a@icloud.com").smtp_saves_sent is False
    assert providers.lookup("a@yandex.com").app_password_url == "https://id.yandex.com/security/app-passwords"
    assert "IMAP" in providers.lookup("a@yandex.ru").notes
    assert ".eu" in providers.lookup("a@zoho.com").notes


def test_lookup_returns_independent_copies():
    a = providers.lookup("a@gmail.com")
    a.imap_host = "evil"
    assert providers.lookup("b@gmail.com").imap_host == "imap.gmail.com"


@pytest.mark.parametrize("email", ["a@proton.me", "a@protonmail.com"])
def test_proton_needs_bridge(email):
    with pytest.raises(ProviderNotSupported, match="Bridge"):
        providers.lookup(email)


@pytest.mark.parametrize("email", [
    "a@outlook.com", "a@hotmail.com", "a@hotmail.co.uk", "a@live.com", "a@msn.com",
    "a@passport.com", "a@windowslive.com", "a@outlook.com.tr",
])
def test_microsoft_rejected_with_v02_message(email):
    with pytest.raises(ProviderNotSupported, match="v0.2"):
        providers.lookup(email)


def test_is_microsoft():
    assert providers.is_microsoft("Outlook.com")
    assert providers.is_microsoft("live.nl")
    assert not providers.is_microsoft("gmail.com")
    assert not providers.is_microsoft("livelovely.com")


AUTOCONFIG_XML = b"""<?xml version="1.0"?>
<clientConfig version="1.1">
  <emailProvider id="example.org">
    <incomingServer type="imap">
      <hostname>plain.example.org</hostname><port>143</port><socketType>plain</socketType>
    </incomingServer>
    <incomingServer type="imap">
      <hostname>imap.example.org</hostname><port>143</port><socketType>STARTTLS</socketType>
    </incomingServer>
    <incomingServer type="imap">
      <hostname>mail.%EMAILDOMAIN%</hostname><port>993</port><socketType>SSL</socketType>
    </incomingServer>
    <incomingServer type="pop3">
      <hostname>pop.example.org</hostname><port>995</port><socketType>SSL</socketType>
    </incomingServer>
    <outgoingServer type="smtp">
      <hostname>smtp.example.org</hostname><port>587</port><socketType>STARTTLS</socketType>
    </outgoingServer>
  </emailProvider>
</clientConfig>"""


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def test_autoconfig_parsed(monkeypatch):
    seen = {}

    def fake_urlopen(url, timeout=None):
        seen["url"], seen["timeout"] = url, timeout
        return _Resp(AUTOCONFIG_XML)

    monkeypatch.setattr(providers.urllib.request, "urlopen", fake_urlopen)
    s = providers.lookup("me@example.org")
    assert seen == {"url": "https://autoconfig.thunderbird.net/v1.1/example.org", "timeout": 5}
    assert s.source == "autoconfig"
    assert (s.imap_host, s.imap_port, s.imap_security) == ("mail.example.org", 993, "ssl")
    assert (s.smtp_host, s.smtp_port, s.smtp_security) == ("smtp.example.org", 587, "starttls")


def test_autoconfig_skips_plain_only(monkeypatch):
    xml = AUTOCONFIG_XML.replace(b"STARTTLS", b"plain").replace(b"SSL", b"plain")
    monkeypatch.setattr(providers.urllib.request, "urlopen", lambda *a, **k: _Resp(xml))
    assert providers.lookup("me@example.org") is None


def test_autoconfig_rejects_dtd(monkeypatch):
    xml = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]>' + AUTOCONFIG_XML
    monkeypatch.setattr(providers.urllib.request, "urlopen", lambda *a, **k: _Resp(xml))
    assert providers.lookup("me@example.org") is None


def test_autoconfig_network_failure_returns_none(monkeypatch):
    def boom(*a, **k):
        raise urllib.error.URLError("down")

    monkeypatch.setattr(providers.urllib.request, "urlopen", boom)
    assert providers.lookup("me@example.org") is None


def test_autoconfig_garbage_returns_none(monkeypatch):
    monkeypatch.setattr(providers.urllib.request, "urlopen", lambda *a, **k: _Resp(b"<html>nope"))
    assert providers.lookup("me@example.org") is None


def test_autoconfig_disabled_by_env_or_flag(monkeypatch):
    monkeypatch.setattr(providers.urllib.request, "urlopen",
                        lambda *a, **k: pytest.fail("network must not be used"))
    assert providers.lookup("me@example.org", allow_network=False) is None
    monkeypatch.setenv("MAILMCP_NO_AUTOCONFIG", "1")
    assert providers.lookup("me@example.org") is None


def test_guess():
    s = providers.guess("me@example.org")
    assert (s.imap_host, s.imap_port, s.imap_security) == ("imap.example.org", 993, "ssl")
    assert (s.smtp_host, s.smtp_port, s.smtp_security) == ("smtp.example.org", 465, "ssl")
    assert s.source == "guess"


def test_every_builtin_has_turkish_notes():
    for d in ("gmail.com", "icloud.com", "yandex.com", "zoho.com", "fastmail.com", "yahoo.com",
              "gmx.com", "gmx.net", "aol.com", "mail.ru"):
        s = providers.lookup("a@" + d)
        assert s.notes and s.notes_tr and s.notes_tr != s.notes, d
    assert "2 Adımlı Doğrulama" in providers.lookup("a@gmail.com").notes_tr
    assert providers.guess("a@example.com").notes_tr is None
