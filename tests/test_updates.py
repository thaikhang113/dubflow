"""Tests for autodub.updates — version parsing and update detection."""
import pytest
from autodub.updates import (
    UpdateInfo,
    _checksum,
    check_for_update,
    is_newer,
    parse_version,
    platform_assets,
)


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


def test_platform_assets_prefers_windows_installer():
    info = UpdateInfo(
        "2.2",
        "https://github.com/x/y/releases/tag/v2.2",
        "",
        (
            {"name": "DubFlow-v2.2-windows-x64.zip"},
            {"name": "DubFlow-v2.2-windows-x64-setup.exe"},
            {"name": "SHA256SUMS-windows.txt"},
        ),
    )
    package, checksum = platform_assets(info, "Windows")
    assert package["name"].endswith("-setup.exe")
    assert checksum["name"] == "SHA256SUMS-windows.txt"


def test_platform_assets_prefers_deb():
    info = UpdateInfo(
        "2.2",
        "",
        "",
        (
            {"name": "DubFlow-v2.2-linux-x86_64.tar.gz"},
            {"name": "dubflow_2.2_amd64.deb"},
            {"name": "SHA256SUMS-linux.txt"},
        ),
    )
    package, _ = platform_assets(info, "Linux")
    assert package["name"].endswith(".deb")


def test_linux_update_rejects_tar_without_deb():
    info = UpdateInfo(
        "2.2",
        "",
        "",
        (
            {"name": "DubFlow-v2.2-linux-x86_64.tar.gz"},
            {"name": "SHA256SUMS-linux.txt"},
        ),
    )
    with pytest.raises(LookupError):
        platform_assets(info, "Linux")

def test_linux_installer_uses_apt_for_local_deb(monkeypatch, tmp_path):
    from autodub.updates import launch_installer

    package = tmp_path / "dubflow_2.2_amd64.deb"
    package.write_bytes(b"deb")
    calls = []

    monkeypatch.setattr("autodub.updates.platform.system", lambda: "Linux")
    monkeypatch.setattr("autodub.updates.os.geteuid", lambda: 1000,
                        raising=False)
    monkeypatch.setattr(
        "subprocess.Popen", lambda command: calls.append(command))

    launch_installer(str(package))

    assert calls == [["pkexec", "apt-get", "install", "-y", str(package)]]


def test_checksum_requires_matching_filename():
    assert _checksum("abc  other.zip\n" + "a" * 64 + "  app.deb", "app.deb") == "a" * 64
    with pytest.raises(ValueError):
        _checksum("a" * 64 + "  other.zip", "app.deb")


def test_download_verified_writes_and_reports_progress(monkeypatch, tmp_path):
    import hashlib
    import types

    payload = b"verified installer"
    digest = hashlib.sha256(payload).hexdigest()
    info = UpdateInfo(
        "2.2",
        "",
        "",
        (
            {"name": "dubflow_2.2_amd64.deb", "url": "https://x/app.deb", "size": len(payload)},
            {"name": "SHA256SUMS-linux.txt", "url": "https://x/sums.txt"},
        ),
    )

    class StreamResponse:
        headers = {"Content-Length": str(len(payload))}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def raise_for_status(self):
            return None

        def iter_content(self, _size):
            return [payload[:5], payload[5:]]

    checksum_response = types.SimpleNamespace(
        text=f"{digest}  dubflow_2.2_amd64.deb",
        raise_for_status=lambda: None,
    )

    def fake_get(url, **_kwargs):
        return checksum_response if url.endswith("sums.txt") else StreamResponse()

    import requests
    monkeypatch.setattr(requests, "get", fake_get)
    progress = []
    path = __import__("autodub.updates", fromlist=["download_verified"]).download_verified(
        info, "Linux", str(tmp_path), progress.append)
    assert open(path, "rb").read() == payload
    assert progress[-1] == 100


def test_download_verified_deletes_checksum_mismatch(monkeypatch, tmp_path):
    import types

    payload = b"tampered"
    info = UpdateInfo(
        "2.2",
        "",
        "",
        (
            {"name": "dubflow_2.2_amd64.deb", "url": "https://x/app.deb", "size": len(payload)},
            {"name": "SHA256SUMS-linux.txt", "url": "https://x/sums.txt"},
        ),
    )

    class StreamResponse:
        headers = {"Content-Length": str(len(payload))}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def raise_for_status(self):
            return None

        def iter_content(self, _size):
            return [payload]

    checksum_response = types.SimpleNamespace(
        text=f"{'0' * 64}  dubflow_2.2_amd64.deb",
        raise_for_status=lambda: None,
    )

    import requests
    monkeypatch.setattr(
        requests, "get",
        lambda url, **_kwargs: (
            checksum_response if url.endswith("sums.txt") else StreamResponse()))
    from autodub.updates import download_verified

    with pytest.raises(ValueError, match="SHA256"):
        download_verified(info, "Linux", str(tmp_path))
    assert not (tmp_path / "dubflow_2.2_amd64.deb").exists()
