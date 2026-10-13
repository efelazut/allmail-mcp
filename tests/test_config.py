import json

import pytest

from mailmcp import config
from mailmcp.errors import AccountNotFound, ConfigError


def test_config_dir_uses_env_override(mailmcp_home):
    d = config.config_dir()
    assert d == mailmcp_home
    assert d.is_dir()


def test_config_dir_default_is_platformdirs(monkeypatch, tmp_path):
    monkeypatch.delenv("MAILMCP_HOME")
    monkeypatch.setattr("platformdirs.user_config_dir", lambda *a, **k: str(tmp_path / "pd"))
    assert config.config_dir() == tmp_path / "pd"


def test_load_missing_returns_empty():
    cfg = config.load_config()
    assert cfg.accounts == {}
    assert cfg.settings.send_approval is True and cfg.settings.trash_approval is True


def test_roundtrip(make_account):
    cfg = config.Config()
    cfg.accounts["efe-gmail"] = make_account()
    cfg.settings.send_approval = False
    config.save_config(cfg)
    raw = json.loads((config.config_dir() / "config.json").read_text(encoding="utf-8"))
    assert raw["version"] == 1
    assert raw["accounts"]["efe-gmail"]["imap_host"] == "imap.gmail.com"
    assert "password" not in json.dumps(raw).lower()
    loaded = config.load_config()
    assert loaded.accounts["efe-gmail"] == cfg.accounts["efe-gmail"]
    assert loaded.settings.send_approval is False


def test_save_is_atomic_no_temp_leftovers(make_account):
    cfg = config.Config(accounts={"a": make_account(id="a")})
    config.save_config(cfg)
    config.save_config(cfg)
    assert [p.name for p in config.config_dir().iterdir()] == ["config.json"]


def test_unknown_keys_ignored():
    (config.config_dir() / "config.json").write_text(json.dumps({
        "version": 7, "future": True,
        "accounts": {"x": {"id": "x", "email": "x@y.z", "display_name": "X", "provider": "p",
                           "imap_host": "h", "imap_port": 1, "imap_security": "ssl",
                           "smtp_host": "h", "smtp_port": 2, "smtp_security": "ssl",
                           "username": "x@y.z", "new_field": 1}},
        "settings": {"send_approval": False, "something_new": 3},
    }), encoding="utf-8")
    cfg = config.load_config()
    assert cfg.accounts["x"].email == "x@y.z"
    assert cfg.settings.send_approval is False


def test_corrupt_file_raises_config_error():
    (config.config_dir() / "config.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ConfigError):
        config.load_config()


def test_get_by_id_or_email_case_insensitive(make_account):
    cfg = config.Config(accounts={"efe-gmail": make_account()})
    assert cfg.get("EFE-GMAIL").id == "efe-gmail"
    assert cfg.get("Efe@Gmail.com").id == "efe-gmail"


def test_get_unknown_lists_valid_ids(make_account):
    cfg = config.Config(accounts={"efe-gmail": make_account(), "b-icloud": make_account(id="b-icloud", email="b@icloud.com")})
    with pytest.raises(AccountNotFound) as exc:
        cfg.get("nope")
    assert "b-icloud" in str(exc.value) and "efe-gmail" in str(exc.value)


def test_make_account_id():
    assert config.make_account_id("efe@gmail.com", set()) == "efe-gmail"
    assert config.make_account_id("efe@gmail.com", {"efe-gmail"}) == "efe-gmail-2"
    assert config.make_account_id("efe@gmail.com", {"efe-gmail", "efe-gmail-2"}) == "efe-gmail-3"
    assert config.make_account_id("Efe.Lazut+news@Mail.Yandex.com", set()) == "efe-lazut-news-mail"
    assert config.make_account_id("weird", set()) == "weird"
