import threading
import time

import pytest

from mailmcp.actions import ActionStore
from mailmcp.errors import MailMcpError


def make(store=None, kind="send"):
    store = store or ActionStore()
    return store, store.create(kind, "acc", {"secret": "payload"}, {"subject": "s"})


def test_create_fields_unique():
    s = ActionStore()
    acts = [s.create("send", None, {}, {}) for _ in range(200)]
    assert len({a.id for a in acts}) == 200
    assert len({a.token for a in acts}) == 200
    assert all(len(a.token) >= 40 and a.status == "pending" for a in acts)
    assert s.get(acts[0].id) is acts[0]
    assert s.get("nope") is None


def test_approve_runs_executor_once_and_consumes_token():
    s, a = make()
    calls = []
    s.register_executor("send", lambda act: calls.append(act.payload) or "Sent ok")
    r = s.approve(a.id, a.token)
    assert r.status == "done" and r.result == "Sent ok" and calls == [{"secret": "payload"}]
    with pytest.raises(MailMcpError):
        s.approve(a.id, a.token)
    assert len(calls) == 1
    assert s.check_token(a.id, a.token) is None


def test_wrong_token_and_unknown_id():
    s, a = make()
    s.register_executor("send", lambda act: "x")
    with pytest.raises(MailMcpError):
        s.approve(a.id, "wrong")
    with pytest.raises(MailMcpError):
        s.approve("zzzzzz", a.token)
    assert s.check_token(a.id, "wrong") is None
    assert s.check_token(a.id, a.token) is a
    assert a.status == "pending"


def test_executor_mailmcp_error_becomes_failed():
    s, a = make()

    def boom(act):
        raise MailMcpError("SMTP said no")
    s.register_executor("send", boom)
    r = s.approve(a.id, a.token)
    assert r.status == "failed" and r.result == "SMTP said no"


def test_executor_unexpected_error_generic(capsys):
    s, a = make()

    def boom(act):
        raise RuntimeError("password=hunter2")
    s.register_executor("send", boom)
    r = s.approve(a.id, a.token)
    assert r.status == "failed" and r.result == "Unexpected error"
    assert "hunter2" not in capsys.readouterr().err


def test_no_executor_fails():
    s, a = make(kind="trash")
    r = s.approve(a.id, a.token)
    assert r.status == "failed" and "executor" in r.result.lower()


def test_reject():
    s, a = make()
    s.register_executor("send", lambda act: pytest.fail("must not run"))
    r = s.reject(a.id, a.token)
    assert r.status == "rejected"
    for fn in (s.approve, s.reject):
        with pytest.raises(MailMcpError):
            fn(a.id, a.token)


def test_reject_wrong_token():
    s, a = make()
    with pytest.raises(MailMcpError):
        s.reject(a.id, "bad")
    assert a.status == "pending"


def test_expiry():
    s = ActionStore(ttl_seconds=900)
    s.register_executor("send", lambda act: pytest.fail("must not run"))
    a = s.create("send", None, {}, {})
    a.expires_at = time.time() - 1
    assert s.check_token(a.id, a.token) is None
    assert s.get(a.id).status == "expired"
    with pytest.raises(MailMcpError):
        s.approve(a.id, a.token)


def test_short_ttl():
    s = ActionStore(ttl_seconds=0)
    a = s.create("send", None, {}, {})
    time.sleep(0.01)
    assert s.get(a.id).status == "expired"


def test_concurrent_approve_runs_once():
    s, a = make()
    count = []
    gate = threading.Event()

    def ex(act):
        count.append(1)
        gate.wait(0.2)
        return "ok"
    s.register_executor("send", ex)
    results = []

    def go():
        try:
            results.append(s.approve(a.id, a.token).status)
        except MailMcpError:
            results.append("err")
    ts = [threading.Thread(target=go) for _ in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(count) == 1
    assert sorted(results) == ["done"] + ["err"] * 7
