"""Tests for autodub.keystore — optional keyring integration."""
from unittest.mock import MagicMock, patch

import pytest

from autodub.keystore import (
    SENTINEL, available, delete_secret, get_secret, resolve, set_secret,
)


def _with_keyring(mod=None):
    """Patch sys.modules để keyring có hoặc không có."""
    import sys

    class _ctx:
        def __init__(self, fake_mod):
            self.fake = fake_mod

        def __enter__(self):
            if self.fake is None:
                sys.modules.setdefault("keyring", None)
                self._orig = sys.modules.get("keyring")
                sys.modules["keyring"] = None  # type: ignore[assignment]
            else:
                self._orig = sys.modules.get("keyring")
                sys.modules["keyring"] = self.fake
            return self.fake

        def __exit__(self, *_):
            if self._orig is None:
                sys.modules.pop("keyring", None)
            else:
                sys.modules["keyring"] = self._orig

    return _ctx(mod)


# -- available() -----------------------------------------------------------

def test_available_without_keyring(monkeypatch):
    monkeypatch.setattr("autodub.keystore._keyring", lambda: None)
    assert available() is False


def test_available_with_keyring(monkeypatch):
    monkeypatch.setattr("autodub.keystore._keyring", lambda: MagicMock())
    assert available() is True


# -- get_secret / set_secret / delete_secret --------------------------------

def test_get_secret_no_keyring(monkeypatch):
    monkeypatch.setattr("autodub.keystore._keyring", lambda: None)
    assert get_secret("GOOGLE_API_KEY") == ""


def test_get_secret_found(monkeypatch):
    ring = MagicMock()
    ring.get_password.return_value = "sk-abc123"
    monkeypatch.setattr("autodub.keystore._keyring", lambda: ring)
    assert get_secret("OPENROUTER_API_KEY") == "sk-abc123"


def test_get_secret_not_found(monkeypatch):
    ring = MagicMock()
    ring.get_password.return_value = None
    monkeypatch.setattr("autodub.keystore._keyring", lambda: ring)
    assert get_secret("MISSING_KEY") == ""


def test_set_secret_no_keyring(monkeypatch):
    monkeypatch.setattr("autodub.keystore._keyring", lambda: None)
    assert set_secret("OPENAI_API_KEY", "sk-x") is False


def test_set_secret_success(monkeypatch):
    ring = MagicMock()
    monkeypatch.setattr("autodub.keystore._keyring", lambda: ring)
    result = set_secret("OPENAI_API_KEY", "sk-x")
    assert result is True
    ring.set_password.assert_called_once()


def test_set_secret_empty_deletes(monkeypatch):
    ring = MagicMock()
    monkeypatch.setattr("autodub.keystore._keyring", lambda: ring)
    set_secret("OPENAI_API_KEY", "")
    # empty value → delete, not set
    ring.set_password.assert_not_called()


# -- resolve() -------------------------------------------------------------

def test_resolve_plain_value(monkeypatch):
    monkeypatch.setattr("autodub.keystore._keyring", lambda: None)
    assert resolve("GOOGLE_API_KEY", "plain-key-value") == "plain-key-value"


def test_resolve_sentinel_calls_get_secret(monkeypatch):
    ring = MagicMock()
    ring.get_password.return_value = "real-secret"
    monkeypatch.setattr("autodub.keystore._keyring", lambda: ring)
    assert resolve("GOOGLE_API_KEY", SENTINEL) == "real-secret"


def test_resolve_sentinel_no_keyring(monkeypatch):
    monkeypatch.setattr("autodub.keystore._keyring", lambda: None)
    assert resolve("GOOGLE_API_KEY", SENTINEL) == ""


def test_resolve_empty(monkeypatch):
    monkeypatch.setattr("autodub.keystore._keyring", lambda: None)
    assert resolve("GOOGLE_API_KEY", "") == ""
