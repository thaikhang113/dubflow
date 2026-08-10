"""Tests for autodub.updates — version parsing and update detection."""
import pytest
from autodub.updates import is_newer, parse_version, check_for_update, UpdateInfo


# -- parse_version ---------------------------------------------------------

def test_parse_simple():
    assert parse_version("2.1") == (2, 1)


def test_parse_with_v_prefix():
    assert parse_version("v2.3") == (2, 3)


def test_parse_three_parts():
    assert parse_version("1.2.3") == (1, 2, 3)


def test_parse_empty():
    assert parse_version("") == (0,)


def test_parse_garbage():
    assert parse_version("abc") == (0,)


# -- is_newer --------------------------------------------------------------

def test_newer_minor():
    assert is_newer("2.2", "2.1") is True


def test_not_newer_same():
    assert is_newer("2.1", "2.1") is False


def test_not_newer_older():
    assert is_newer("2.0", "2.1") is False


def test_newer_with_v_prefix():
    assert is_newer("v3.0", "2.9") is True


def test_newer_patch():
    assert is_newer("2.1.1", "2.1.0") is True


def test_same_length_padding():
    # "2.1" vs "2.1.0" should be equal
    assert is_newer("2.1", "2.1.0") is False
    assert is_newer("2.1.0", "2.1") is False


# -- check_for_update (offline mock) ---------------------------------------

def test_check_no_update(monkeypatch):
    """API trả về cùng phiên bản → None."""
    import types
    fake_resp = types.SimpleNamespace(
        raise_for_status=lambda: None,
        json=lambda: {"tag_name": "v2.1", "html_url": "https://x", "body": ""},
    )
    import requests
    monkeypatch.setattr(requests, "get", lambda *a, **kw: fake_resp)
    result = check_for_update("owner/repo", "2.1")
    assert result is None


def test_check_has_update(monkeypatch):
    """API trả về phiên bản mới hơn → UpdateInfo."""
    import types
    fake_resp = types.SimpleNamespace(
        raise_for_status=lambda: None,
        json=lambda: {"tag_name": "v2.2", "html_url": "https://gh/releases",
                      "body": "Bug fixes"},
    )
    import requests
    monkeypatch.setattr(requests, "get", lambda *a, **kw: fake_resp)
    info = check_for_update("owner/repo", "2.1")
    assert info is not None
    assert info.version == "2.2"
    assert "gh" in info.url
    assert info.notes == "Bug fixes"


def test_check_invalid_repo(monkeypatch):
    """Kho không hợp lệ → None ngay, không gọi mạng."""
    import requests
    monkeypatch.setattr(requests, "get",
                        lambda *a, **kw: (_ for _ in ()).throw(
                            AssertionError("should not call")))
    assert check_for_update("", "2.1") is None
    assert check_for_update("nodash", "2.1") is None
