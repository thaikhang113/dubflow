"""Kiểm tra _Prefetcher — bộ tải trước video kế tiếp trong hàng đợi batch.

Trước đây lớp này chưa có test nào: đường E2E thật có chạy nó, nhưng không có
gìn giữ hành vi. Đây là nơi dễ hỏng nhất của batch vì nó vừa đụng mạng, vừa đụng
dọn tệp, vừa phải không được làm hỏng lượt đang chạy.
"""
from __future__ import annotations

import json
import os

import pytest

from autodub.batch import BatchItem, _Prefetcher
from autodub.workdir import data_path


def _fake_download(monkeypatch, path: str, *, title: str = "Tieu de"):
    """Thay download_video: ghi video gia + data/video_meta.json nhu that."""
    calls: list[str] = []

    def fake(url, output_dir, **_kw):
        calls.append(url)
        os.makedirs(output_dir, exist_ok=True)
        dest = os.path.join(output_dir, "video.mp4")
        with open(dest, "wb") as handle:
            handle.write(b"video")
        from autodub.utils import save_json_atomic

        save_json_atomic({"title": title, "uploader": "kenh"},
                         data_path(output_dir, "video_meta.json",
                                   create_dir=True))
        return dest

    import autodub.media.downloader as downloader

    monkeypatch.setattr(downloader, "download_video", fake)
    return calls


def test_start_skips_local_files(tmp_path):
    """Item đã là tệp trên máy thì không có gì để tải trước."""
    p = _Prefetcher(str(tmp_path))
    try:
        p.start(0, BatchItem(file_path=str(tmp_path / "a.mp4")))
        p.start(1, BatchItem())
        assert p._futures == {}
    finally:
        p.cleanup()


def test_take_returns_downloaded_path_and_meta(tmp_path, monkeypatch):
    calls = _fake_download(monkeypatch, "x")
    p = _Prefetcher(str(tmp_path))
    try:
        p.start(1, BatchItem(url="https://example.com/1"))
        path = p.take(1, timeout=30)
        assert path and os.path.isfile(path)
        assert calls == ["https://example.com/1"]
        assert p._futures == {}, "future phai duoc pop sau khi take"
    finally:
        p.cleanup()


def test_take_without_prefetch_returns_none(tmp_path):
    p = _Prefetcher(str(tmp_path))
    try:
        assert p.take(5) is None
    finally:
        p.cleanup()


def test_download_failure_degrades_to_none(tmp_path, monkeypatch):
    """Mạng lỗi chỉ làm mất lợi ích tải trước — không làm hỏng cả batch."""
    import autodub.media.downloader as downloader

    def boom(url, output_dir, **_kw):
        raise RuntimeError("network down")

    monkeypatch.setattr(downloader, "download_video", boom)
    p = _Prefetcher(str(tmp_path))
    try:
        p.start(1, BatchItem(url="https://example.com/bad"))
        assert p.take(1, timeout=30) is None
    finally:
        p.cleanup()


def test_adopt_moves_video_and_meta_into_work_dir(tmp_path):
    work = tmp_path / "project"
    (work / "data").mkdir(parents=True)
    staged = tmp_path / "_prefetch" / "1"
    staged.mkdir(parents=True)
    video = staged / "video.mp4"
    video.write_bytes(b"video")
    meta_dir = staged / "data"
    meta_dir.mkdir()
    (meta_dir / "video_meta.json").write_text('{"title": "Tieu de"}',
                                              encoding="utf-8")

    _Prefetcher.adopt(str(video), str(work))

    assert (work / "video.mp4").is_file()
    assert not video.exists(), "file da don thi khong duoc con sot"
    with open(data_path(str(work), "video_meta.json"), encoding="utf-8") as f:
        assert json.load(f)["title"] == "Tieu de"


def test_adopt_keeps_existing_meta_in_work_dir(tmp_path):
    """Pipeline da chep san video_meta.json thi don file video, dung de lap."""
    work = tmp_path / "project"
    (work / "data").mkdir(parents=True)
    existing = data_path(str(work), "video_meta.json", create_dir=True)
    with open(existing, "w", encoding="utf-8") as f:
        json.dump({"title": "giu lai"}, f)

    staged = tmp_path / "_prefetch" / "2"
    staged.mkdir(parents=True)
    video = staged / "video.mp4"
    video.write_bytes(b"video")
    meta = staged / "data" / "video_meta.json"
    meta.parent.mkdir()
    meta.write_text('{"title": "de"}', encoding="utf-8")

    _Prefetcher.adopt(str(video), str(work))

    assert (work / "video.mp4").is_file()
    with open(existing, encoding="utf-8") as f:
        assert json.load(f)["title"] == "giu lai"


def test_adopt_is_silent_when_target_missing(tmp_path):
    _Prefetcher.adopt(str(tmp_path / "khong_ton_tai.mp4"), str(tmp_path))


def test_cleanup_drops_pending_work(tmp_path, monkeypatch):
    _fake_download(monkeypatch, "x")
    p = _Prefetcher(str(tmp_path))
    p.start(1, BatchItem(url="https://example.com/1"))
    p.cleanup()
    assert p._futures == {}
    # Sau khi don, take khong con gi de cho -> tra None de video tu tai lai.
    assert p.take(1, timeout=1) is None


def test_cleanup_removes_empty_prefetch_root(tmp_path):
    p = _Prefetcher(str(tmp_path))
    os.makedirs(os.path.join(str(tmp_path), "_prefetch"), exist_ok=True)
    p.cleanup()
    assert not os.path.isdir(os.path.join(str(tmp_path), "_prefetch"))


def test_prefetch_executor_caps_concurrency(tmp_path, monkeypatch):
    """Dem song song bi gioi han, khong mo 8 luong tai cung luc."""
    import threading
    import time

    import autodub.media.downloader as downloader

    live = {"now": 0, "max": 0}
    lock = threading.Lock()

    def slow(url, output_dir, **_kw):
        with lock:
            live["now"] += 1
            live["max"] = max(live["max"], live["now"])
        time.sleep(0.2)
        with lock:
            live["now"] -= 1
        raise RuntimeError("no")

    monkeypatch.setattr(downloader, "download_video", slow)
    p = _Prefetcher(str(tmp_path), max_workers=2)
    try:
        for i in range(8):
            p.start(i, BatchItem(url=f"https://example.com/{i}"))
        for i in range(8):
            p.take(i, timeout=30)
    finally:
        p.cleanup()
    assert live["max"] <= 2, f"mo {live['max']} luong tai trong khi tran 2"
