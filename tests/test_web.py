import http.client
import threading
import urllib.parse

import pytest

from mailmcp.actions import ActionStore
from mailmcp.errors import MailMcpError
from mailmcp.web import LocalWeb

XSS = '<script>alert(1)</script>"><img src=x onerror=alert(2)>'


class Env:
    def __init__(self):
        self.store = ActionStore()
        self.sent = []
        self.adds = []
        self.add_error = None
        self.lookups = []
        self.store.register_executor("send", lambda a: self.sent.append(a.id) or "Message sent.")
        self.store.register_executor("trash", lambda a: "Moved 2 messages to Trash.")
        self.store.register_executor("settings", lambda a: "Setting changed.")
        self.oauth_adds = []
        self.web = LocalWeb(self.store, self._add, self._lookup, add_oauth=self._add_oauth)
        self.web.start()
        self.port = self.web.port

    def _add(self, email, password, name, manual):
        self.adds.append((email, password, name, manual))
        if self.add_error:
            raise MailMcpError(self.add_error)
        return "acc-1"

    def _add_oauth(self, email, name):
        self.oauth_adds.append((email, name))
        if self.add_error:
            raise MailMcpError(self.add_error)
        return "acc-ms"

    def _lookup(self, email):
        self.lookups.append(email)
        if "@hotmail" in email:
            return {"provider": "outlook", "auth": "oauth2", "imap_host": "outlook.office365.com",
                    "notes": "Sign in"}
        if email.startswith("bad"):
            return {"error": "Lookup failed <b>"}
        return {"provider": "gmail", "imap_host": "imap.gmail.com", "imap_port": 993,
                "imap_security": "ssl", "smtp_host": "smtp.gmail.com", "smtp_port": 465,
                "smtp_security": "ssl", "app_password_url": "https://myaccount.google.com/apppasswords",
                "notes": "Needs 2-Step", "notes_tr": "2 Adımlı Doğrulama <gerekli>"}

    def req(self, method, path, body=None, headers=None, host=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Host": host or f"127.0.0.1:{self.port}"}
        if method == "POST":
            h["Origin"] = f"http://127.0.0.1:{self.port}"
        h.update(headers or {})
        h = {k: v for k, v in h.items() if v is not None}  # None removes a default header
        if isinstance(body, dict):
            body = urllib.parse.urlencode(body)
            h.setdefault("Content-Type", "application/x-www-form-urlencoded")
        c.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        for k, v in h.items():
            c.putheader(k, v)
        if body is not None:
            c.putheader("Content-Length", str(len(body.encode())))
        c.endheaders(body.encode() if body is not None else None)
        r = c.getresponse()
        data = r.read().decode("utf-8")
        hdrs = {k.lower(): v for k, v in r.getheaders()}
        c.close()
        return r.status, hdrs, data


@pytest.fixture
def env():
    e = Env()
    yield e
    e.web.stop()


def send_action(env, subject="Hi", body="Hello body"):
    return env.store.create("send", "acc", {"p": 1}, {
        "from": "Me <me@x.com>", "to": ["a@x.com", "b@y.com"], "cc": "c@z.com", "bcc": "secret@q.com",
        "subject": subject, "body": body})


def url_of(env, a):
    return env.web.approval_url(a.id).replace(env.web.base_url, "")


def test_binds_loopback_and_idempotent(env):
    port = env.port
    env.web.start()
    assert env.web.port == port
    assert env.web.base_url == f"http://127.0.0.1:{port}"
    assert env.web._server.server_address[0] == "127.0.0.1"


def test_lazy_start():
    e = LocalWeb(ActionStore(), lambda *a: "x", lambda e: {})
    assert e._server is None
    assert e.base_url.startswith("http://127.0.0.1:")
    e.stop()


def test_approval_page_content_and_headers(env):
    a = send_action(env)
    st, h, body = env.req("GET", url_of(env, a))
    assert st == 200
    for s in ("a@x.com", "b@y.com", "c@z.com", "secret@q.com", "Hi", "Hello body", "Me &lt;me@x.com&gt;"):
        assert s in body
    assert "<script" not in body.lower()
    assert h["content-security-policy"] == ("default-src 'none'; style-src 'unsafe-inline'; "
                                            "form-action 'self'; base-uri 'none'; frame-ancestors 'none'")
    assert h["x-frame-options"] == "DENY"
    assert h["referrer-policy"] == "same-origin"  # no-referrer would make browsers send Origin: null
    assert h["x-content-type-options"] == "nosniff"
    assert h["cache-control"] == "no-store"
    assert 'name="action" value="approve"' in body and 'name="action" value="reject"' in body


def test_xss_escaped(env):
    a = send_action(env, subject=XSS, body=XSS)
    st, _, body = env.req("GET", url_of(env, a))
    assert st == 200
    assert "<script>alert(1)" not in body and "<img src=x" not in body
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body


def test_trash_and_settings_pages(env):
    t = env.store.create("trash", "acc", {}, {"account": "acc", "folder": "INBOX", "messages": [
        {"date": "2026-01-01", "from": "<b>x@y.com</b>", "subject": "Old"}]})
    _, _, body = env.req("GET", url_of(env, t))
    assert "INBOX" in body and "Old" in body and "&lt;b&gt;x@y.com" in body
    s = env.store.create("settings", None, {}, {"changes": [
        {"setting": "send_approval", "from": True, "to": False}]})
    _, _, body = env.req("GET", url_of(env, s))
    assert "Approval before sending" in body and "send_approval" not in body and "LOOSENS" in body
    _, _, body = env.req("GET", url_of(env, s), headers={"Accept-Language": "tr"})
    assert "Göndermeden önce onay" in body
    u = env.store.create("settings", None, {}, {"changes": [
        {"setting": "trash_approval", "from": True, "to": False},
        {"setting": "mystery_<b>", "to": 1}]})
    _, _, body = env.req("GET", url_of(env, u))
    assert "Approval before moving to Trash" in body and "mystery_&lt;b&gt;" in body


def test_host_header_attack_rejected(env):
    a = send_action(env)
    for host in ("evil.com", f"evil.com:{env.port}", "127.0.0.1", f"127.0.0.1.evil.com:{env.port}",
                 "localhost:1"):
        st, _, _ = env.req("GET", url_of(env, a), host=host)
        assert st == 400, host
        st, _, _ = env.req("POST", f"/a/{a.id}", {"t": a.token, "action": "approve"}, host=host)
        assert st == 400
    assert not env.sent
    st, _, _ = env.req("GET", url_of(env, a), host=f"localhost:{env.port}")
    assert st == 200


def test_cross_origin_post_rejected(env):
    a = send_action(env)
    for origin in ("http://evil.com", "null", f"http://evil.com:{env.port}", f"https://127.0.0.1:{env.port}"):
        st, _, _ = env.req("POST", f"/a/{a.id}", {"t": a.token, "action": "approve"},
                           headers={"Origin": origin})
        assert st == 403, origin
    assert not env.sent and a.status == "pending"
    st, _, _ = env.req("POST", f"/a/{a.id}", {"t": a.token, "action": "approve"},
                       headers={"Origin": f"http://127.0.0.1:{env.port}"})
    assert st == 200 and env.sent == [a.id]


def test_missing_origin_and_bad_sec_fetch_site_rejected(env):
    a = send_action(env)
    form = {"t": a.token, "action": "approve"}
    assert env.req("POST", f"/a/{a.id}", form, headers={"Origin": None})[0] == 403
    for site in ("cross-site", "same-site", "none"):
        assert env.req("POST", f"/a/{a.id}", form, headers={"Sec-Fetch-Site": site})[0] == 403
    assert env.req("POST", "/add", {"t": "x"}, headers={"Origin": None})[0] == 403
    assert not env.sent and a.status == "pending"
    assert env.req("POST", f"/a/{a.id}", form, headers={"Sec-Fetch-Site": "same-origin"})[0] == 200
    assert env.sent == [a.id]


def test_recipients_are_bidi_isolated(env):
    a = send_action(env)
    _, _, body = env.req("GET", url_of(env, a))
    assert body.count("unicode-bidi:isolate") >= 4
    assert "<bdi" in body


def test_wrong_content_type_and_oversize(env):
    a = send_action(env)
    st, _, _ = env.req("POST", f"/a/{a.id}", f"t={a.token}&action=approve",
                       headers={"Content-Type": "text/plain"})
    assert st == 400
    st, _, _ = env.req("POST", f"/a/{a.id}", "t=" + "x" * 70000,
                       headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert st == 413
    assert not env.sent


def test_missing_or_wrong_token_403(env):
    a = send_action(env)
    assert env.req("GET", f"/a/{a.id}")[0] == 403
    assert env.req("GET", f"/a/{a.id}?t=wrong")[0] == 403
    assert env.req("GET", f"/a/nonexistent?t={a.token}")[0] == 403
    assert env.req("POST", f"/a/{a.id}", {"action": "approve"})[0] == 403
    assert env.req("POST", f"/a/{a.id}", {"t": "wrong", "action": "approve"})[0] == 403
    assert not env.sent and a.status == "pending"


def test_approve_then_token_single_use(env):
    a = send_action(env)
    st, _, body = env.req("POST", f"/a/{a.id}", {"t": a.token, "action": "approve"})
    assert st == 200 and "Message sent." in body and "close this tab" in body
    assert env.sent == [a.id]
    st, _, body = env.req("POST", f"/a/{a.id}", {"t": a.token, "action": "approve"})
    assert st == 409 and env.sent == [a.id]
    st, _, body = env.req("GET", url_of(env, a))
    assert st == 200 and "Message sent." in body and 'name="action"' not in body


def test_concurrent_double_post_runs_once(env):
    a = send_action(env)
    codes = []

    def go():
        codes.append(env.req("POST", f"/a/{a.id}", {"t": a.token, "action": "approve"})[0])
    ts = [threading.Thread(target=go) for _ in range(6)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert env.sent == [a.id]
    assert sorted(codes) == [200] + [409] * 5


def test_reject_path(env):
    a = send_action(env)
    st, _, body = env.req("POST", f"/a/{a.id}", {"t": a.token, "action": "reject"})
    assert st == 200 and "Rejected" in body and a.status == "rejected" and not env.sent
    st, _, _ = env.req("POST", f"/a/{a.id}", {"t": a.token, "action": "approve"})
    assert st == 409 and not env.sent


def test_bad_action_value(env):
    a = send_action(env)
    assert env.req("POST", f"/a/{a.id}", {"t": a.token, "action": "nuke"})[0] == 400


def test_expired_action(env):
    a = send_action(env)
    a.expires_at = 0
    st, _, body = env.req("GET", url_of(env, a))
    assert st == 200 and "expired" in body.lower() and 'name="action"' not in body
    st, _, _ = env.req("POST", f"/a/{a.id}", {"t": a.token, "action": "approve"})
    assert st == 409 and not env.sent


def test_failed_executor_shown(env):
    def boom(a):
        raise MailMcpError("SMTP login <failed>")
    env.store.register_executor("send", boom)
    a = send_action(env)
    st, _, body = env.req("POST", f"/a/{a.id}", {"t": a.token, "action": "approve"})
    assert st == 200 and "SMTP login &lt;failed&gt;" in body and "Failed" in body


def test_404(env):
    assert env.req("GET", "/")[0] == 404
    assert env.req("GET", "/etc/passwd")[0] == 404
    assert env.req("GET", "/a/")[0] == 404
    assert env.req("POST", "/other", {"a": "b"})[0] == 404


def test_turkish_ui(env):
    a = send_action(env)
    _, _, body = env.req("GET", url_of(env, a), headers={"Accept-Language": "tr-TR,tr;q=0.9,en;q=0.5"})
    assert 'lang="tr"' in body and "Onayla" in body and "Reddet" in body
    _, _, body = env.req("GET", url_of(env, a), headers={"Accept-Language": "en-US,en;q=0.9,tr;q=0.8"})
    assert 'lang="en"' in body and "Approve" in body
    _, _, body = env.req("GET", url_of(env, a), headers={"Accept-Language": "de,tr;q=0.4,en;q=0.2"})
    assert 'lang="en"' in body
    _, _, body = env.req("POST", f"/a/{a.id}", {"t": a.token, "action": "approve"},
                         headers={"Accept-Language": "tr"})
    assert "Tamamlandı" in body


# ---------------------------------------------------------------- add account

def add_url(env):
    return env.web.new_add_account_url().replace(env.web.base_url, "")


def test_add_form_and_lookup(env):
    u = add_url(env)
    st, h, body = env.req("GET", u)
    assert st == 200 and 'type="password"' not in body and 'autocomplete="off"' in body
    assert "Continue" in body and "<script" not in body.lower()
    assert h["content-security-policy"].startswith("default-src 'none'")
    st, _, body = env.req("GET", u + "&email=me%40gmail.com")
    assert env.lookups == ["me@gmail.com"]
    assert "imap.gmail.com" in body and 'value="me@gmail.com"' in body
    assert 'href="https://myaccount.google.com/apppasswords"' in body
    assert 'rel="noopener noreferrer"' in body and 'target="_blank"' in body
    assert "Needs 2-Step" in body and "Connect me@gmail.com" in body
    assert 'type="password"' in body and "Google does not let apps" in body
    assert "2 Adımlı" not in body
    _, _, body = env.req("GET", u + "&email=me%40gmail.com", headers={"Accept-Language": "tr"})
    assert "2 Adımlı Doğrulama &lt;gerekli&gt;" in body and "Needs 2-Step" not in body
    st, _, body = env.req("GET", u + "&email=bad%40x.com")
    assert "Lookup failed &lt;b&gt;" in body


def test_add_requires_session(env):
    assert env.req("GET", "/add")[0] == 403
    assert env.req("GET", "/add?t=nope")[0] == 403
    st, _, _ = env.req("POST", "/add", {"t": "nope", "email": "a@b.com", "password": "pw"})
    assert st == 403 and not env.adds


def test_add_cross_origin_and_host_rejected(env):
    u = add_url(env)
    tok = u.split("t=")[1]
    f = {"t": tok, "email": "a@b.com", "password": "pw"}
    assert env.req("POST", "/add", f, headers={"Origin": "http://evil.com"})[0] == 403
    assert env.req("POST", "/add", f, host="evil.com")[0] == 400
    assert not env.adds


def test_add_success_and_wait(env):
    u = add_url(env)
    tok = u.split("t=")[1]
    assert env.web.wait_for_add(0.05) is None
    st, _, body = env.req("POST", "/add", {"t": tok, "email": "me@gmail.com", "password": "s3cret!",
                                           "display_name": "Efe", "imap_host": "", "smtp_host": ""})
    assert st == 200 and "Account added" in body and "acc-1" in body
    assert env.adds == [("me@gmail.com", "s3cret!", "Efe", None)]
    assert env.web.wait_for_add(1) == "acc-1"
    # single use on success
    st, _, _ = env.req("POST", "/add", {"t": tok, "email": "me@gmail.com", "password": "x"})
    assert st == 403 and len(env.adds) == 1
    assert env.req("GET", u)[0] == 403


def test_add_manual_settings(env):
    tok = add_url(env).split("t=")[1]
    env.req("POST", "/add", {"t": tok, "email": "me@corp.com", "password": "pw", "display_name": "",
                             "imap_host": "mail.corp.com", "imap_port": "143", "imap_security": "starttls",
                             "smtp_host": "smtp.corp.com", "smtp_port": "587", "smtp_security": "starttls",
                             "username": "me"})
    assert env.adds[0][3] == {"imap_host": "mail.corp.com", "imap_port": 143, "imap_security": "starttls",
                              "smtp_host": "smtp.corp.com", "smtp_port": 587, "smtp_security": "starttls",
                              "username": "me"}


def test_add_error_rerender_no_password_echo_and_retry(env):
    tok = add_url(env).split("t=")[1]
    env.add_error = "Login failed <wrong app password>"
    st, _, body = env.req("POST", "/add", {"t": tok, "email": "me@gmail.com", "password": "TopSecret123",
                                           "display_name": "Efe"})
    assert st == 200
    assert "Login failed &lt;wrong app password&gt;" in body
    assert "TopSecret123" not in body
    assert 'value="me@gmail.com"' in body and 'value="Efe"' in body
    assert env.web.wait_for_add(0.05) is None
    env.add_error = None
    st, _, body = env.req("POST", "/add", {"t": tok, "email": "me@gmail.com", "password": "TopSecret123"})
    assert "Account added" in body
    assert env.web.wait_for_add(1) == "acc-1"


def test_add_validation_errors(env):
    tok = add_url(env).split("t=")[1]
    _, _, body = env.req("POST", "/add", {"t": tok, "email": "nope", "password": "x"})
    assert "valid email" in body
    _, _, body = env.req("POST", "/add", {"t": tok, "email": "a@b.com", "password": ""})
    assert "password" in body.lower()
    _, _, body = env.req("POST", "/add", {"t": tok, "email": "a@b.com", "password": "p",
                                          "imap_host": "h", "imap_port": "abc"})
    assert "numbers" in body
    assert not env.adds


def test_add_turkish(env):
    u = add_url(env)
    _, _, body = env.req("GET", u, headers={"Accept-Language": "tr"})
    assert "Posta hesabı ekle" in body and "Devam" in body
    _, _, body = env.req("GET", u + "&email=me%40gmail.com", headers={"Accept-Language": "tr"})
    assert "me@gmail.com adresini bağla" in body and "Bağlan" in body


def test_add_unexpected_error_generic(env):
    tok = add_url(env).split("t=")[1]

    def boom(*a):
        raise RuntimeError("pw=leak")
    env.web.add_account = boom
    st, _, body = env.req("POST", "/add", {"t": tok, "email": "a@b.com", "password": "p"})
    assert st == 200 and "leak" not in body and "Unexpected" in body


def test_open_in_browser_never_raises(monkeypatch):
    import webbrowser
    from mailmcp.web import open_in_browser
    monkeypatch.setattr(webbrowser, "open", lambda u: True)
    assert open_in_browser("http://127.0.0.1:1/") is True

    def boom(u):
        raise RuntimeError("no browser")
    monkeypatch.setattr(webbrowser, "open", boom)
    assert open_in_browser("http://127.0.0.1:1/") is False
    monkeypatch.setattr(webbrowser, "open", lambda u: False)
    assert open_in_browser("x") is False


def test_microsoft_screen_has_sign_in_button_and_no_password(env):
    u = add_url(env)
    _, _, body = env.req("GET", u + "&email=me%40hotmail.com")
    assert 'action="/add/microsoft"' in body and "Sign in with Microsoft" in body
    assert 'type="password"' not in body and "<script" not in body.lower()


def test_microsoft_post_adds_account_and_consumes_session(env):
    tok = add_url(env).split("t=")[1]
    st, _, body = env.req("POST", "/add/microsoft", {"t": tok, "email": "me@hotmail.com", "display_name": "Efe"})
    assert st == 200 and "acc-ms" in body and env.oauth_adds == [("me@hotmail.com", "Efe")]
    st, _, _ = env.req("POST", "/add/microsoft", {"t": tok, "email": "me@hotmail.com"})
    assert st == 403 and len(env.oauth_adds) == 1


def test_microsoft_post_error_redisplays_button(env):
    env.add_error = "Microsoft sign-in did not complete (access_denied)."
    tok = add_url(env).split("t=")[1]
    st, _, body = env.req("POST", "/add/microsoft", {"t": tok, "email": "me@hotmail.com"})
    assert st == 200 and "access_denied" in body and "Sign in with Microsoft" in body


def test_microsoft_post_rejects_cross_origin(env):
    tok = add_url(env).split("t=")[1]
    f = {"t": tok, "email": "me@hotmail.com"}
    assert env.req("POST", "/add/microsoft", f, headers={"Origin": "http://evil.com"})[0] == 403
    assert not env.oauth_adds
