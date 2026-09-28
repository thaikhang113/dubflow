"""Install the optional video-subtitle-remover backend."""
from __future__ import annotations

import hashlib
import http.client
import json
import os
import shutil
import stat
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_ROOT = os.environ.get("DUBFLOW_DATA_DIR", ROOT)
VENV = os.path.join(DATA_ROOT, ".venv-vsr")
PYTHON = os.path.join(
    VENV, "Scripts" if os.name == "nt" else "bin",
    "python.exe" if os.name == "nt" else "python",
)
MODEL_DIR = os.path.join(DATA_ROOT, "models", "video-subtitle-remover")
SOURCE_DIR = os.path.join(MODEL_DIR, "source")
MARKER = os.path.join(MODEL_DIR, "installed_ok.json")
SUPPORTED_PYTHON = ((3, 10), (3, 11), (3, 12))
ARCHIVE_URL = (
    "https://github.com/YaoFANGUK/video-subtitle-remover/"
    "archive/refs/tags/1.1.1.zip"
)
ARCHIVE_SHA256 = (
    "7ce750c2b75a41d9f6e81cb8c4b2753a6788d69cc42352f2b8273c91ed191baf"
)

def _verify_archive(path: str | Path) -> None:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != ARCHIVE_SHA256:
        raise RuntimeError("VSR archive checksum mismatch")

def _download_archive(
    url: str,
    destination: str | Path,
    *,
    log=print,
    attempts: int = 3,
    timeout: int = 60,
) -> None:
    """Download a checksum-pinned archive with timeout, progress, and retries."""
    if attempts < 1:
        raise ValueError("attempts must be at least one")
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    part_path = destination.with_name(destination.name + ".part")
    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            log(f"Đang tải source VSR (lần {attempt}/{attempts})...")
            request = urllib.request.Request(
                url, headers={"User-Agent": "DubFlow-Setup/1.0"})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                total = int(response.headers.get("Content-Length") or 0)
                downloaded = 0
                last_reported = 0
                with part_path.open("wb") as handle:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        handle.write(chunk)
                        downloaded += len(chunk)
                        if downloaded - last_reported >= 16 * 1024 * 1024:
                            if total:
                                log(
                                    f"Đang tải VSR: {downloaded // (1024 * 1024)} / "
                                    f"{total // (1024 * 1024)} MB")
                            else:
                                log(f"Đã tải VSR: {downloaded // (1024 * 1024)} MB")
                            last_reported = downloaded
                    handle.flush()
                    os.fsync(handle.fileno())
            if total and downloaded != total:
                raise OSError(
                    f"Tải chưa đủ dữ liệu ({downloaded}/{total} byte).")
            log(f"Đã tải VSR: {downloaded // (1024 * 1024)} MB; đang kiểm tra SHA256...")
            _verify_archive(part_path)
            os.replace(part_path, destination)
            return
        except (OSError, RuntimeError, ValueError, http.client.HTTPException) as exc:
            last_error = exc
            try:
                part_path.unlink(missing_ok=True)
            except OSError:
                pass
            if attempt < attempts:
                log(f"Tải VSR lỗi ({exc}); sẽ thử lại.")
                time.sleep(min(2 ** (attempt - 1), 4))

    raise RuntimeError(
        f"Không tải được source VSR sau {attempts} lần thử: {last_error}") from last_error


def _safe_extract(handle: zipfile.ZipFile, destination: str | Path) -> None:
    root = Path(destination).resolve()
    root.mkdir(parents=True, exist_ok=True)
    entries: list[tuple[zipfile.ZipInfo, Path]] = []
    for member in handle.infolist():
        name = member.filename.replace("\\", "/")
        parts = PurePosixPath(name).parts
        if (
            not name
            or PurePosixPath(name).is_absolute()
            or ".." in parts
            or (parts and ":" in parts[0])
            or stat.S_ISLNK(member.external_attr >> 16)
        ):
            raise RuntimeError(f"unsafe ZIP member: {member.filename!r}")
        target = (root / Path(*parts)).resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise RuntimeError(f"unsafe ZIP member: {member.filename!r}") from exc
        entries.append((member, target))

    for member, target in entries:
        if member.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with handle.open(member) as source, target.open("wb") as output:
            shutil.copyfileobj(source, output)


def log(message: str) -> None:
    print(f"[setup-vsr] {message}", flush=True)


def validate_python_version(version: tuple[int, int]) -> None:
    if version not in SUPPORTED_PYTHON:
        supported = ", ".join(
            f"{major}.{minor}" for major, minor in SUPPORTED_PYTHON)
        raise RuntimeError(
            f"VSR cần Python {supported}; đang dùng "
            f"{version[0]}.{version[1]}.")


def main() -> int:
    validate_python_version(sys.version_info[:2])
    if not os.path.isfile(PYTHON):
        log("Tạo virtualenv VSR ...")
        subprocess.run([sys.executable, "-m", "venv", VENV], check=True)
    os.makedirs(MODEL_DIR, exist_ok=True)
    if not os.path.isdir(SOURCE_DIR):
        archive = os.path.join(MODEL_DIR, "source.zip")
        _download_archive(ARCHIVE_URL, archive, log=log)
        extracted = os.path.join(MODEL_DIR, "extract")
        os.makedirs(extracted, exist_ok=True)
        with zipfile.ZipFile(archive) as handle:
            _safe_extract(handle, extracted)
        roots = [os.path.join(extracted, name) for name in os.listdir(extracted)]
        source = next((path for path in roots if os.path.isdir(path)), "")
        if not source:
            raise RuntimeError("Không tìm thấy source VSR sau khi tải.")
        shutil.move(source, SOURCE_DIR)
        os.remove(archive)
        shutil.rmtree(extracted, ignore_errors=True)
    requirements = os.path.join(SOURCE_DIR, "requirements.txt")
    if os.path.isfile(requirements):
        log("Cài dependency VSR ...")
        subprocess.run(
            [PYTHON, "-m", "pip", "install", "--retries", "3",
             "--timeout", "30", "-r", requirements],
            check=True,
            timeout=1800,
        )
        subprocess.run(
            [PYTHON, "-m", "pip", "check"], check=True, timeout=120,
        )
    with open(MARKER, "w", encoding="utf-8") as handle:
        json.dump({
            "ok": True,
            "backend": "video-subtitle-remover",
            "version": "1.1.1",
            "source": SOURCE_DIR,
        }, handle, indent=2)
    log("XONG — VSR sẵn sàng.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
