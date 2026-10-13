import json
import tomllib

import pytest

from mailmcp import __version__, install

PINNED = f"mailmcp@{__version__}"
from mailmcp.errors import UsageError


@pytest.fixture(autouse=True)
def no_cli_on_path(monkeypatch):
    monkeypatch.setattr(install.shutil, "which", lambda name: None)


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    h.mkdir()
    return h


def by_key(changes):
    return {c.target.key: c for c in changes}


def jload(p):
    return json.loads(p.read_text(encoding="utf-8"))


def baks(path):
    return list(path.parent.glob(path.name + ".bak-mailmcp*"))


def test_targets_paths_and_detection(home):
    ts = {t.key: t for t in install.targets(home)}
    assert ts["claude"].path == home / ".claude.json"
    assert ts["codex"].path == home / ".codex" / "config.toml"
    assert ts["cursor"].path == home / ".cursor" / "mcp.json"
    assert ts["antigravity"].path == home / ".gemini" / "antigravity" / "mcp_config.json"
    assert ts["gemini"].path == home / ".gemini" / "settings.json"
    assert not any(t.detected for t in ts.values())
    (home / ".cursor").mkdir()
    (home / ".claude.json").write_text("{}")
    ts = {t.key: t for t in install.targets(home)}
    assert ts["cursor"].detected and ts["claude"].detected and not ts["codex"].detected


def test_detected_via_cli_on_path(home, monkeypatch):
    monkeypatch.setattr(install.shutil, "which", lambda name: "/x/codex" if name == "codex" else None)
    ts = {t.key: t for t in install.targets(home)}
    assert ts["codex"].detected and not ts["cursor"].detected


def test_plan_none_means_only_detected(home):
    assert install.plan(None, home=home) == []
    (home / ".cursor").mkdir()
    ch = install.plan(None, home=home)
    assert [c.target.key for c in ch] == ["cursor"]
    assert ch[0].action == "add"


def test_unknown_client(home):
    with pytest.raises(UsageError):
        install.plan(["nope"], home=home)


def test_undetected_explicit_client_is_skipped(home):
    ch = install.plan(["cursor"], home=home)
    assert ch[0].error and ch[0].action == "unchanged"
    install.apply(ch)
    assert not (home / ".cursor").exists()


@pytest.mark.parametrize("key,rel", [
    ("cursor", ".cursor/mcp.json"),
    ("antigravity", ".gemini/antigravity/mcp_config.json"),
    ("gemini", ".gemini/settings.json"),
])
def test_json_fresh_file_simple_entry(home, key, rel, monkeypatch):
    monkeypatch.setattr(install.shutil, "which", lambda name: "/bin/x" if name == key else None)
    p = home / rel
    p.parent.mkdir(parents=True)
    ch = install.plan([key], home=home)
    assert ch[0].action == "add"
    lines = install.apply(ch)
    assert any("added" in l for l in lines)
    assert jload(p) == {"mcpServers": {"mail": {"command": "uvx", "args": [PINNED]}}}
    assert baks(p) == []  # nothing to back up for a new file


def test_claude_entry_shape_and_other_content_preserved(home):
    p = home / ".claude.json"
    original = {
        "numStartups": 5, "projects": {"C:\\x": {"a": 1}}, "zeta": "ünï",
        "mcpServers": {"other": {"type": "stdio", "command": "foo", "args": []}},
    }
    p.write_text(json.dumps(original, indent=2, ensure_ascii=False), encoding="utf-8")
    install.apply(install.plan(["claude"], home=home))
    data = jload(p)
    assert data["mcpServers"]["other"] == original["mcpServers"]["other"]
    assert data["mcpServers"]["mail"] == {"type": "stdio", "command": "uvx", "args": [PINNED], "env": {}}
    assert list(data) == list(original)  # key order kept
    assert data["zeta"] == "ünï" and data["projects"] == original["projects"]
    assert "ünï" in p.read_text(encoding="utf-8")  # ensure_ascii=False
    assert len(baks(p)) == 1
    assert jload(baks(p)[0]) == original


def test_json_idempotent_unchanged(home):
    (home / ".cursor").mkdir()
    install.apply(install.plan(["cursor"], home=home))
    p = home / ".cursor" / "mcp.json"
    before = p.read_text()
    ch = install.plan(["cursor"], home=home)
    assert ch[0].action == "unchanged" and ch[0].error is None
    lines = install.apply(ch)
    assert "up to date" in lines[0]
    assert p.read_text() == before and baks(p) == []


def test_json_update_preserves_unknown_fields(home):
    p = home / ".cursor" / "mcp.json"
    p.parent.mkdir()
    p.write_text(json.dumps({"mcpServers": {"mail": {"command": "old", "args": ["mailmcp-old"], "env": {"A": "1"},
                                                    "disabled": False}}}))
    ch = install.plan(["cursor"], command=["python", "-m", "mailmcp"], home=home)
    assert ch[0].action == "update"
    install.apply(ch)
    m = jload(p)["mcpServers"]["mail"]
    assert m == {"command": "python", "args": ["-m", "mailmcp"], "env": {"A": "1"}, "disabled": False}
    assert len(baks(p)) == 1


def test_json_remove_only_ours(home):
    p = home / ".cursor" / "mcp.json"
    p.parent.mkdir()
    p.write_text(json.dumps({"x": 1, "mcpServers": {"mail": {"command": "uvx", "args": ["mailmcp"]}, "keep": {"command": "k"}}}))
    ch = install.plan(["cursor"], remove=True, home=home)
    assert ch[0].action == "remove"
    install.apply(ch)
    assert jload(p) == {"x": 1, "mcpServers": {"keep": {"command": "k"}}}
    assert install.plan(["cursor"], remove=True, home=home)[0].action == "unchanged"


def test_json_remove_when_absent_is_noop(home):
    ch = install.plan(["claude"], remove=True, home=home)
    assert ch[0].action == "unchanged"
    install.apply(ch)
    assert not (home / ".claude.json").exists()


def test_invalid_json_not_overwritten(home):
    p = home / ".cursor" / "mcp.json"
    p.parent.mkdir()
    p.write_text("{ not json")
    ch = install.plan(["cursor"], home=home)
    assert ch[0].error and ch[0].action == "unchanged"
    lines = install.apply(ch)
    assert "skipped" in lines[0]
    assert p.read_text() == "{ not json" and baks(p) == []


def test_mcpservers_wrong_type_skipped(home):
    p = home / ".cursor" / "mcp.json"
    p.parent.mkdir()
    p.write_text('{"mcpServers": []}')
    assert install.plan(["cursor"], home=home)[0].error


def test_apply_creates_missing_parents_when_detected_by_cli(home, monkeypatch):
    monkeypatch.setattr(install.shutil, "which", lambda n: "/bin/x" if n == "cursor" else None)
    install.apply(install.plan(["cursor"], home=home))
    assert (home / ".cursor" / "mcp.json").exists()


# ----------------------------------------------------------------------------- TOML

def codex_path(home):
    p = home / ".codex" / "config.toml"
    p.parent.mkdir(exist_ok=True)
    return p


def test_toml_fresh_file(home):
    p = codex_path(home)
    ch = install.plan(["codex"], home=home)
    assert ch[0].action == "add"
    install.apply(ch)
    data = tomllib.loads(p.read_text())
    assert data["mcp_servers"]["mail"] == {"command": "uvx", "args": [PINNED], "startup_timeout_sec": 60}


def test_toml_append_keeps_existing(home):
    p = codex_path(home)
    src = 'model = "gpt-5"\n\n# my servers\n[mcp_servers.other]\ncommand = "o"\nargs = ["a"]\n'
    p.write_text(src, encoding="utf-8")
    install.apply(install.plan(["codex"], home=home))
    text = p.read_text()
    assert text.startswith(src + "\n[mcp_servers.mail]")
    data = tomllib.loads(text)
    assert data["mcp_servers"]["other"] == {"command": "o", "args": ["a"]}
    assert data["mcp_servers"]["mail"]["command"] == "uvx"
    assert len(baks(p)) == 1
    assert baks(p)[0].read_text() == src


def test_toml_idempotent(home):
    p = codex_path(home)
    install.apply(install.plan(["codex"], home=home))
    text = p.read_text()
    ch = install.plan(["codex"], home=home)
    assert ch[0].action == "unchanged"
    install.apply(ch)
    assert p.read_text() == text and len(baks(p)) == 0


def test_toml_update_replaces_only_our_table(home):
    p = codex_path(home)
    p.write_text(
        '[mcp_servers.a]\ncommand = "a"\n\n'
        '[mcp_servers.mail]\ncommand = "old"\nargs = ["mailmcp", "y"]\nenv_vars = ["K"]\n\n'
        '[mcp_servers.mail.env]\nFOO = "1"\n\n'
        '[mcp_servers.z]\ncommand = "z"\n', encoding="utf-8")
    ch = install.plan(["codex"], command=["uvx", "mailmcp", "--x"], home=home)
    assert ch[0].action == "update"
    install.apply(ch)
    d = tomllib.loads(p.read_text())["mcp_servers"]
    assert d["a"] == {"command": "a"} and d["z"] == {"command": "z"}
    assert d["mail"] == {"command": "uvx", "args": ["mailmcp", "--x"], "env_vars": ["K"],
                         "startup_timeout_sec": 60, "env": {"FOO": "1"}}


def test_toml_remove_with_subtables(home):
    p = codex_path(home)
    p.write_text(
        '[mcp_servers.a]\ncommand = "a"\n\n[mcp_servers.mail]\ncommand = "mailmcp"\n\n'
        '[mcp_servers.mail.env]\nFOO = "1"\n\n[mcp_servers.z]\ncommand = "z"\n', encoding="utf-8")
    ch = install.plan(["codex"], remove=True, home=home)
    assert ch[0].action == "remove"
    install.apply(ch)
    d = tomllib.loads(p.read_text())
    assert set(d["mcp_servers"]) == {"a", "z"}
    assert "mail" not in p.read_text()


def test_toml_windows_path_quoting_roundtrip(home):
    p = codex_path(home)
    cmd = [r"C:\Users\Efe Lazut\.local\bin\uvx.exe", "mailmcp", 'say "hi"\tx']
    install.apply(install.plan(["codex"], command=cmd, home=home))
    m = tomllib.loads(p.read_text())["mcp_servers"]["mail"]
    assert m["command"] == cmd[0] and m["args"] == cmd[1:]
    # update with another path roundtrips as well and is then idempotent
    cmd2 = [r"D:\tools\n\mailmcp.exe"]
    install.apply(install.plan(["codex"], command=cmd2, home=home))
    m = tomllib.loads(p.read_text())["mcp_servers"]["mail"]
    assert m["command"] == cmd2[0] and m["args"] == []
    assert install.plan(["codex"], command=cmd2, home=home)[0].action == "unchanged"


def test_toml_crlf_preserved(home):
    p = codex_path(home)
    p.write_bytes(b'model = "x"\r\n')
    install.apply(install.plan(["codex"], home=home))
    raw = p.read_bytes()
    assert b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b"")
    tomllib.loads(raw.decode())


def test_invalid_toml_skipped(home):
    p = codex_path(home)
    p.write_text("this = = broken\n")
    ch = install.plan(["codex"], home=home)
    assert ch[0].error and ch[0].action == "unchanged"
    install.apply(ch)
    assert p.read_text() == "this = = broken\n" and baks(p) == []


def test_toml_inline_layout_not_edited(home):
    p = codex_path(home)
    p.write_text('[mcp_servers]\nmail = { command = "m" }\n')
    ch = install.plan(["codex"], home=home)
    assert ch[0].error
    install.apply(ch)
    assert p.read_text() == '[mcp_servers]\nmail = { command = "m" }\n'


def test_toml_validation_failure_restores_backup(home, monkeypatch):
    p = codex_path(home)
    src = 'model = "x"\n'
    p.write_text(src)
    ch = install.plan(["codex"], home=home)
    calls = {"n": 0}
    real = install._mail_table

    def flaky(text, *a):
        calls["n"] += 1
        if "[mcp_servers.mail]" in text and calls["n"] > 2:
            raise ValueError("boom")
        return real(text, *a)

    monkeypatch.setattr(install, "_mail_table", flaky)
    lines = install.apply(ch)
    assert "restored" in lines[0]
    assert p.read_text() == src


def test_default_command_is_version_pinned():
    assert install.DEFAULT_COMMAND == ["uvx", f"mailmcp@{__version__}"]


def test_foreign_json_entry_not_touched(home):
    p = home / ".cursor" / "mcp.json"
    p.parent.mkdir()
    text = json.dumps({"mcpServers": {"mail": {"command": "evil", "args": ["--steal"]}}})
    p.write_text(text)
    for remove in (False, True):
        ch = install.plan(["cursor"], remove=remove, home=home)
        assert ch[0].action == "unchanged"
        assert "already exists and is not mailmcp" in ch[0].error
        assert "skipped" in install.apply(ch)[0]
    assert p.read_text() == text and baks(p) == []


def test_foreign_toml_entry_not_touched(home):
    p = codex_path(home)
    text = '[mcp_servers.mail]\ncommand = "other"\nargs = ["x"]\n'
    p.write_text(text, encoding="utf-8")
    ch = install.plan(["codex"], home=home)
    assert "is not mailmcp" in ch[0].error
    install.apply(ch)
    assert p.read_text(encoding="utf-8") == text and baks(p) == []


def test_custom_name_coexists_with_foreign_entry(home):
    p = home / ".cursor" / "mcp.json"
    p.parent.mkdir()
    p.write_text(json.dumps({"mcpServers": {"mail": {"command": "other"}}}))
    ch = install.plan(["cursor"], home=home, name="mailmcp")
    assert ch[0].action == "add" and not ch[0].error
    install.apply(ch)
    servers = jload(p)["mcpServers"]
    assert servers["mail"] == {"command": "other"} and servers["mailmcp"]["args"] == [PINNED]
    c = codex_path(home)
    install.apply(install.plan(["codex"], home=home, name="mailmcp"))
    assert tomllib.loads(c.read_text(encoding="utf-8"))["mcp_servers"]["mailmcp"]["args"] == [PINNED]


def test_single_backup_overwritten_and_claude_hint(home):
    p = home / ".claude.json"
    p.write_text(json.dumps({"a": 1}))
    install.apply(install.plan(["claude"], home=home))
    first = (home / ".claude.json.bak-mailmcp").read_text()
    assert json.loads(first) == {"a": 1}
    p.write_text(json.dumps({"a": 2, "mcpServers": {"mail": {"command": "uvx", "args": ["mailmcp@0.0.1"]}}}))
    lines = install.apply(install.plan(["claude"], home=home))
    assert len(baks(p)) == 1 and json.loads(baks(p)[0].read_text())["a"] == 2
    assert any("Close" not in ln and "close Claude Code before installing" in ln for ln in lines)
    other = install.apply(install.plan(["cursor"], home=home, name="mail"))
    assert not any("before installing" in ln for ln in other)
