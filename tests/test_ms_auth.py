"""Microsoft sign-in wiring: XOAUTH2 on IMAP/SMTP and the add_oauth_account flow (no network)."""
import pytest

from mailmcp import ms_auth
from mailmcp.config import load_config
from mailmcp.errors import MailMcpError
from mailmcp.server import App, account_secret


class FakeImap:
    def __init__(self):
        self.calls = []

    def oauth2_login(self, user, token):
        self.calls.append(("oauth2", user, token))

    def login(self, user, pw):
        self.calls.append(("login", user, pw))


def test_imap_login_dispatch():
    from mailmcp.imap_backend import _login
    c = FakeImap()
    _login(c, "me@hotmail.com", "tok", "oauth2")
    _login(c, "me@gmail.com", "pw", "basic")
    assert c.calls == [("oauth2", "me@hotmail.com", "tok"), ("login", "me@gmail.com", "pw")]


def test_client_id_required(monkeypatch):
    monkeypatch.delenv("MAILMCP_MS_CLIENT_ID", raising=False)
    monkeypatch.setattr(ms_auth, "DEFAULT_CLIENT_ID", "")
    with pytest.raises(ms_auth.MicrosoftAuthError, match="MAILMCP_MS_CLIENT_ID"):
        ms_auth.client_id()
    monkeypatch.setenv("MAILMCP_MS_CLIENT_ID", " abc ")
    assert ms_auth.client_id() == "abc"


def test_add_oauth_account(memory_keyring, monkeypatch):
    import mailmcp.server as srv
    monkeypatch.setattr(ms_auth, "sign_in", lambda email, timeout=300: "Me@Hotmail.com")
    monkeypatch.setattr(ms_auth, "access_token", lambda user: "tok-" + user)
    seen = []
    monkeypatch.setattr(srv, "test_login", lambda server, user, secret: seen.append((server.auth, user, secret)))
    a = App(browser=lambda url: True)
    try:
        acc_id = a.add_oauth_account("me@hotmail.com", "")
        acc = load_config().get(acc_id)
        assert acc.auth == "oauth2" and acc.provider == "outlook" and acc.username == "Me@Hotmail.com"
        assert seen == [("oauth2", "Me@Hotmail.com", "tok-Me@Hotmail.com")]
        assert account_secret(acc) == "tok-Me@Hotmail.com"
        with pytest.raises(MailMcpError, match="already added"):
            a.add_oauth_account("me@hotmail.com", "")
        with pytest.raises(MailMcpError, match="Microsoft sign-in"):
            a.add_oauth_account("me@gmail.com", "")
        with pytest.raises(MailMcpError, match="signs in with Microsoft"):
            a.add_account("x@outlook.com", "pw", "", None)
    finally:
        a.web.stop()


def test_token_cache_roundtrip_is_encrypted(memory_keyring, tmp_path, monkeypatch):
    monkeypatch.setenv("MAILMCP_HOME", str(tmp_path))
    import msal
    cache = msal.SerializableTokenCache()
    cache.add({"client_id": "c", "scope": ["s"], "token_endpoint": "https://login.microsoftonline.com/consumers/oauth2/v2.0/token",
               "response": {"access_token": "AT", "refresh_token": "RT-secret", "expires_in": 3600,
                            "token_type": "Bearer"}})
    ms_auth._save_cache(cache)
    raw = (tmp_path / "ms_tokens.bin").read_bytes()
    assert b"RT-secret" not in raw
    assert "RT-secret" in ms_auth._load_cache().serialize()
