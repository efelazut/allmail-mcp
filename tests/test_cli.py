import json
import sys
import types

import pytest

import mailmcp
from mailmcp import cli, install
from mailmcp.config import Account, Config
from mailmcp.errors import AccountNotFound, MailMcpError


@pytest.fixture(autouse=True)
def isolate(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(install.shutil, "which", lambda name: None)
    monkeypatch.setattr(install.Path, "home", classmethod(lambda cls: home))
    return home


@pytest.fixture
def home(isolate):
    return isolate


def fake_server(monkeypatch, **attrs):
    mod = types.ModuleType("mailmcp.server")
    for k, v in attrs.items():
        setattr(mod, k, v)
    monkeypatch.setitem(sys.modules, "mailmcp.server", mod)
    return mod


def test_version(capsys):
    assert cli.main(["--version"]) == 0
    assert mailmcp.__version__ in capsys.readouterr().out


@pytest.mark.parametrize("argv", [[], ["serve"]])
def test_no_args_and_serve_run_server(monkeypatch, argv):
    called = []
    fake_server(monkeypatch, run=lambda: called.append(1))
    assert cli.main(argv) == 0
    assert called == [1]


def test_unknown_command_and_bad_client_are_usage_errors(capsys):
    assert cli.main(["bogus"]) == 2
    assert cli.main(["install", "--client", "nope"]) == 2
    assert cli.main(["remove-account"]) == 2


def test_mailmcp_error_exits_1(monkeypatch, capsys):
    def boom():
        raise MailMcpError("friendly failure")
    fake_server(monkeypatch, run=boom)
    assert cli.main(["serve"]) == 1
    assert "friendly failure" in capsys.readouterr().err


def test_add_account_delegates(monkeypatch):
    fake_server(monkeypatch, add_account_cli=lambda: 3)
    assert cli.main(["add-account"]) == 3


def account(i="efe-gmail"):
    return Account(id=i, email="efe@gmail.com", display_name="Efe", provider="gmail",
                   imap_host="imap.gmail.com", imap_port=993, imap_security="ssl",
                   smtp_host="smtp.gmail.com", smtp_port=465, smtp_security="ssl", username="efe@gmail.com")


class FakeCfg(Config):
    def get(self, key):
        for a in self.accounts.values():
            if key in (a.id, a.email):
                return a
        raise AccountNotFound(f"no such account {key}")


def patch_config(monkeypatch, cfg):
    from mailmcp import config
    saved = []
    monkeypatch.setattr(config, "load_config", lambda: cfg)
    monkeypatch.setattr(config, "save_config", lambda c: saved.append(dict(c.accounts)))
    return saved


def test_accounts_table(monkeypatch, capsys):
    cfg = FakeCfg(accounts={"efe-gmail": account()})
    patch_config(monkeypatch, cfg)
    assert cli.main(["accounts"]) == 0
    out = capsys.readouterr().out
    assert "efe-gmail" in out and "efe@gmail.com" in out and "gmail" in out and "imap.gmail.com" in out


def test_accounts_empty(monkeypatch, capsys):
    patch_config(monkeypatch, FakeCfg())
    assert cli.main(["accounts"]) == 0
    assert "add-account" in capsys.readouterr().out


def test_remove_account_yes(monkeypatch):
    from mailmcp import secrets_store
    cfg = FakeCfg(accounts={"efe-gmail": account()})
    saved = patch_config(monkeypatch, cfg)
    deleted = []
    monkeypatch.setattr(secrets_store, "delete_password", lambda i: deleted.append(i))
    assert cli.main(["remove-account", "efe-gmail", "--yes"]) == 0
    assert deleted == ["efe-gmail"] and saved == [{}]


def test_remove_account_declined(monkeypatch):
    from mailmcp import secrets_store
    cfg = FakeCfg(accounts={"efe-gmail": account()})
    saved = patch_config(monkeypatch, cfg)
    monkeypatch.setattr(secrets_store, "delete_password", lambda i: pytest.fail("must not delete"))
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    assert cli.main(["remove-account", "efe-gmail"]) == 0
    assert saved == []


def test_remove_account_unknown(monkeypatch, capsys):
    patch_config(monkeypatch, FakeCfg())
    assert cli.main(["remove-account", "nope", "--yes"]) == 1
    assert "no such account" in capsys.readouterr().err


# ------------------------------------------------------------------------- install

def test_parse_command():
    assert cli._parse_command(None) == ["uvx", f"mailmcp@{mailmcp.__version__}"]
    assert cli._parse_command("uvx mailmcp") == ["uvx", "mailmcp"]
    assert cli._parse_command('["python", "-m", "mailmcp"]') == ["python", "-m", "mailmcp"]
    assert cli._parse_command('"C:\\Program Files\\uvx.exe" mailmcp')[1] == "mailmcp"
    with pytest.raises(MailMcpError):
        cli._parse_command("[1, 2]")


def test_install_dry_run_writes_nothing(home, capsys):
    (home / ".cursor").mkdir()
    assert cli.main(["install", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "Cursor" in out and "ADD" in out and "mailmcp" in out
    assert not (home / ".cursor" / "mcp.json").exists()


def test_install_yes_writes(home, capsys):
    (home / ".cursor").mkdir()
    assert cli.main(["install", "--yes", "--command", "uvx mailmcp"]) == 0
    data = json.loads((home / ".cursor" / "mcp.json").read_text())
    assert data["mcpServers"]["mail"] == {"command": "uvx", "args": ["mailmcp"]}


def test_install_confirm_prompt(home, monkeypatch):
    (home / ".cursor").mkdir()
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    assert cli.main(["install"]) == 0
    assert not (home / ".cursor" / "mcp.json").exists()
    monkeypatch.setattr("builtins.input", lambda prompt="": "y")
    assert cli.main(["install"]) == 0
    assert (home / ".cursor" / "mcp.json").exists()


def test_install_explicit_client_and_json_command(home):
    (home / ".codex").mkdir()
    assert cli.main(["install", "--client", "codex", "--yes", "--command", '["py", "-m", "mailmcp"]']) == 0
    import tomllib
    m = tomllib.loads((home / ".codex" / "config.toml").read_text())["mcp_servers"]["mail"]
    assert m["command"] == "py" and m["args"] == ["-m", "mailmcp"]


def test_install_nothing_detected(home, capsys):
    assert cli.main(["install", "--yes"]) == 1
    assert "No supported" in capsys.readouterr().err


def test_install_invalid_json_reports_error_exit_1(home, capsys):
    (home / ".cursor").mkdir()
    (home / ".cursor" / "mcp.json").write_text("{bad")
    assert cli.main(["install", "--yes"]) == 1
    assert (home / ".cursor" / "mcp.json").read_text() == "{bad"


def test_uninstall(home):
    (home / ".cursor").mkdir()
    cli.main(["install", "--yes"])
    assert cli.main(["uninstall", "--yes"]) == 0
    assert json.loads((home / ".cursor" / "mcp.json").read_text()) == {"mcpServers": {}}


# ------------------------------------------------------------------------- doctor

def test_doctor_not_available_does_not_crash(monkeypatch, capsys):
    from mailmcp import config, secrets_store

    def ni(*a, **k):
        raise NotImplementedError
    monkeypatch.setattr(secrets_store, "assert_secure_backend", ni)
    monkeypatch.setattr(config, "load_config", ni)
    assert cli.main(["doctor"]) == 0
    assert "not available" in capsys.readouterr().out


def test_doctor_full(monkeypatch, capsys):
    from mailmcp import config, imap_backend, secrets_store
    cfg = FakeCfg(accounts={"efe-gmail": account()})
    monkeypatch.setattr(secrets_store, "assert_secure_backend", lambda: None)
    monkeypatch.setattr(config, "load_config", lambda: cfg)
    monkeypatch.setattr(config, "config_dir", lambda: "C:/cfg")
    monkeypatch.setattr(secrets_store, "get_password", lambda i: "s3cret-pw")
    seen = {}
    monkeypatch.setattr(imap_backend, "test_login", lambda srv, u, p: seen.update(host=srv.imap_host, user=u))
    assert cli.main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "s3cret-pw" not in out and "✓" in out
    assert seen == {"host": "imap.gmail.com", "user": "efe@gmail.com"}


def test_doctor_failures_exit_1_no_secret(monkeypatch, capsys):
    from mailmcp import config, imap_backend, secrets_store
    from mailmcp.errors import MailServerError, SecretStoreError
    cfg = FakeCfg(accounts={"a": account("a"), "b": account("b")})
    monkeypatch.setattr(secrets_store, "assert_secure_backend",
                        lambda: (_ for _ in ()).throw(SecretStoreError("no secure keyring")))
    monkeypatch.setattr(config, "load_config", lambda: cfg)
    monkeypatch.setattr(config, "config_dir", lambda: "C:/cfg")

    def gp(i):
        if i == "a":
            raise SecretStoreError("No stored password for a")
        return "pw-b"
    monkeypatch.setattr(secrets_store, "get_password", gp)

    def tl(*a):
        raise MailServerError("login rejected")
    monkeypatch.setattr(imap_backend, "test_login", tl)
    assert cli.main(["doctor"]) == 1
    out = capsys.readouterr().out
    assert "✗" in out and "login rejected" in out and "pw-b" not in out
