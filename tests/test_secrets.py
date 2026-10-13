import keyring
import pytest
from keyring.backends import chainer, fail, null
from keyring.backend import KeyringBackend

from mailmcp import secrets_store
from mailmcp.errors import SecretStoreError


def test_roundtrip(memory_keyring):
    secrets_store.set_password("acc", "s3cret")
    assert secrets_store.get_password("acc") == "s3cret"
    assert memory_keyring.store[("mailmcp", "acc")] == "s3cret"
    secrets_store.delete_password("acc")
    with pytest.raises(SecretStoreError, match="No stored password for acc"):
        secrets_store.get_password("acc")


def test_delete_missing_is_ignored(memory_keyring):
    secrets_store.delete_password("never-existed")


def test_rejects_fail_backend():
    previous = keyring.get_keyring()
    keyring.set_keyring(fail.Keyring())
    try:
        with pytest.raises(SecretStoreError, match="keyring"):
            secrets_store.assert_secure_backend()
        with pytest.raises(SecretStoreError):
            secrets_store.set_password("a", "b")
    finally:
        keyring.set_keyring(previous)


def test_rejects_null_backend():
    previous = keyring.get_keyring()
    keyring.set_keyring(null.Keyring())
    try:
        with pytest.raises(SecretStoreError):
            secrets_store.assert_secure_backend()
    finally:
        keyring.set_keyring(previous)


def test_rejects_keyrings_alt_module_and_low_priority():
    class PlainFile(KeyringBackend):
        priority = 5  # type: ignore[assignment]

        def get_password(self, s, u): ...
        def set_password(self, s, u, p): ...
        def delete_password(self, s, u): ...

    PlainFile.__module__ = "keyrings.alt.file"
    assert secrets_store._backend_problem(PlainFile()) is not None

    class Weak(PlainFile):
        priority = 0  # type: ignore[assignment]

    Weak.__module__ = "somepkg.weak"
    assert "priority" in secrets_store._backend_problem(Weak())


def test_chainer_with_only_bad_backends_rejected(memory_keyring):
    class BadChain(chainer.ChainerBackend):
        backends = [fail.Keyring(), null.Keyring()]  # type: ignore[assignment]

    class GoodChain(chainer.ChainerBackend):
        backends = [fail.Keyring(), memory_keyring]  # type: ignore[assignment]

    assert secrets_store._backend_problem(BadChain()) is not None
    assert secrets_store._backend_problem(GoodChain()) is None


def test_accepts_memory_backend(memory_keyring):
    secrets_store.assert_secure_backend()
