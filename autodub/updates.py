"""Kiểm tra bản phát hành mới trên GitHub Releases.

Chỉ là phần logic thuần: gọi API công khai của GitHub (không cần đăng nhập),
so sánh số phiên bản và trả về kết quả. Phần giao diện (chạy nền, hiện thông
báo) nằm ở ``autodub_gui`` — tách ra để kiểm thử được không cần mạng.
"""
from __future__ import annotations

import hashlib
import os
import platform
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

_API_URL = "https://api.github.com/repos/{repo}/releases/latest"
_TIMEOUT_S = 10


@dataclass
class UpdateInfo:
    """Một bản phát hành mới hơn bản đang chạy."""

    version: str        # số phiên bản mới, ví dụ "2.2"
    url: str            # trang tải bản mới
    notes: str          # ghi chú phát hành (có thể trống)
    assets: tuple[dict, ...] = ()


def parse_version(text: str) -> tuple[int, ...]:
    """Đổi "v2.1" / "2.1.3" thành bộ số so sánh được; phần lạ coi là 0."""
    text = (text or "").strip().lstrip("vV")
    parts: list[int] = []
    for piece in text.split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) or (0,)


def is_newer(latest: str, current: str) -> bool:
    """``latest`` có mới hơn ``current`` không (bỏ qua tiền tố "v")."""
    a, b = parse_version(latest), parse_version(current)
    length = max(len(a), len(b))
    a += (0,) * (length - len(a))
    b += (0,) * (length - len(b))
    return a > b


def check_for_update(repo: str, current_version: str) -> UpdateInfo | None:
    """Hỏi GitHub xem có bản mới không. Trả về None nếu đang mới nhất.

    Lỗi mạng hay kho không tồn tại đều ném ra ngoài — nơi gọi tự quyết
    im lặng hay báo, tùy chỗ (kiểm tra nền thì im lặng, bấm tay thì báo).
    """
    import requests

    repo = (repo or "").strip().strip("/")
    if not repo or "/" not in repo:
        return None
    resp = requests.get(_API_URL.format(repo=repo), timeout=_TIMEOUT_S,
                        headers={"Accept": "application/vnd.github+json"})
    resp.raise_for_status()
    data = resp.json()
    tag = str(data.get("tag_name") or "").strip()
    if not tag or not is_newer(tag, current_version):
        return None
    return UpdateInfo(
        version=tag.lstrip("vV"),
        url=str(data.get("html_url") or f"https://github.com/{repo}/releases"),
        notes=str(data.get("body") or "").strip(),
        assets=tuple(
            {
                "name": str(asset.get("name") or ""),
                "url": str(asset.get("browser_download_url") or ""),
                "size": int(asset.get("size") or 0),
            }
            for asset in data.get("assets", ())
            if isinstance(asset, dict)
        ),
    )


def _asset(info: UpdateInfo, suffix: str) -> dict | None:
    for asset in info.assets:
        if asset.get("name", "").endswith(suffix):
            return asset
    return None


def platform_assets(info: UpdateInfo, system: str | None = None) -> tuple[dict, dict]:
    """Return (package, checksum) assets for current platform."""
    system = system or platform.system()
    if system == "Windows":
        package = (_asset(info, "-setup.exe")
                   or _asset(info, "-windows-x64.zip"))
        checksum = _asset(info, "SHA256SUMS-windows.txt")
    elif system == "Linux":
        package = (_asset(info, "_amd64.deb")
                   or _asset(info, "-amd64.deb"))
        checksum = _asset(info, "SHA256SUMS-linux.txt")
    else:
        raise ValueError(f"unsupported platform: {system}")
    if not package or not checksum:
        raise LookupError(f"release {info.version} has no {system} package")
    return package, checksum


def _checksum(text: str, filename: str) -> str:
    for line in text.splitlines():
        fields = line.strip().split()
        if len(fields) >= 2 and fields[-1] == filename:
            value = fields[0].lower()
            if len(value) == 64 and all(ch in "0123456789abcdef" for ch in value):
                return value
    raise ValueError(f"checksum missing for {filename}")


def download_verified(info: UpdateInfo, system: str | None = None,
                      destination: str | None = None,
                      progress: Callable[[int], None] | None = None) -> str:
    """Download platform package and verify SHA256 from release checksum."""
    import requests

    package, checksum_asset = platform_assets(info, system)
    response = requests.get(checksum_asset["url"], timeout=30)
    response.raise_for_status()
    expected = _checksum(response.text, package["name"])
    if destination is None:
        destination = tempfile.mkdtemp(prefix="dubflow-update-")
    os.makedirs(destination, exist_ok=True)
    path = os.path.join(destination, package["name"])
    digest = hashlib.sha256()
    with requests.get(package["url"], stream=True, timeout=60) as response:
        response.raise_for_status()
        total = int(response.headers.get("Content-Length") or package.get("size") or 0)
        downloaded = 0
        with open(path, "wb") as handle:
            for chunk in response.iter_content(1024 * 1024):
                if chunk:
                    digest.update(chunk)
                    handle.write(chunk)
                    downloaded += len(chunk)
                    if progress and total:
                        progress(min(99, int(downloaded * 100 / total)))
    if digest.hexdigest().lower() != expected:
        try:
            os.remove(path)
        except OSError:
            pass
        raise ValueError("downloaded update failed SHA256 verification")
    if progress:
        progress(100)
    return path


def launch_installer(package_path: str, pid: int | None = None) -> None:
    """Start platform updater and return; caller must quit app afterward."""
    package = Path(package_path).resolve()
    if platform.system() == "Linux" and package.suffix == ".deb":
        import subprocess
        command = ["dpkg", "-i", str(package)]
        if getattr(os, "geteuid", lambda: 1)() != 0:
            command.insert(0, "pkexec")
        subprocess.Popen(command)
        return
    if platform.system() != "Windows":
        raise ValueError("unsupported installer platform")

    if package.suffix.lower() == ".exe":
        import subprocess
        subprocess.Popen(
            [str(package), "/VERYSILENT", "/SUPPRESSMSGBOXES",
             "/NORESTART", "/CLOSEAPPLICATIONS"],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return

    root = package.parent / "dubflow-updater.cmd"
    install_root = Path(os.path.dirname(os.path.abspath(os.sys.executable)))
    root.write_text(
        "@echo off\n"
        "timeout /t 2 /nobreak >nul\n"
        f"powershell -NoProfile -ExecutionPolicy Bypass -Command "
        f"\"Expand-Archive -LiteralPath '{package}' -DestinationPath "
        f"'{package.parent / 'expanded'}' -Force; "
        f"Copy-Item -Path '{package.parent / 'expanded' / 'DubFlow' / '*'}' "
        f"-Destination '{install_root}' -Recurse -Force; "
        f"Start-Process '{install_root / 'DubFlow.exe'}'\"\n"
        "del \"%~f0\"\n",
        encoding="utf-8",
    )
    import subprocess
    subprocess.Popen(["cmd", "/c", str(root)],
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
