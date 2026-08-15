import threading

import pytest

from autodub.media import downloader


def test_extract_info_retries_bilibili_412(monkeypatch):
    calls = []

    class Ydl:
        def extract_info(self, url, download):
            calls.append((url, download))
            if len(calls) == 1:
                raise RuntimeError("Unable to download JSON metadata: HTTP Error 412")
            return {"id": "BV-test"}

    sleeps = []
    monkeypatch.setattr(downloader.time, "sleep", sleeps.append)

    result = downloader._extract_info_with_retry(Ydl(), "https://bilibili.test", attempts=2)

    assert result["id"] == "BV-test"
    assert len(calls) == 2
    assert sleeps == [2]


def test_extract_info_does_not_retry_invalid_video():
    class Ydl:
        def extract_info(self, _url, download=True):
            raise RuntimeError("video is private")

    with pytest.raises(RuntimeError):
        downloader._extract_info_with_retry(Ydl(), "https://example.test", attempts=3)


def test_douyin_download_receives_douyin_cookie_file(monkeypatch, tmp_path):
    calls = {}

    def fake_is_douyin(_url):
        return True

    def fake_download(url, output_dir, filename=None, cookies_file=None):
        calls["cookies_file"] = cookies_file
        return {"filepath": str(tmp_path / "video.mp4"), "title": ""}

    monkeypatch.setattr("autodub.media.douyin.is_douyin_url", fake_is_douyin)
    monkeypatch.setattr("autodub.media.douyin.download_douyin", fake_download)
    downloader.download_one(
        "https://v.douyin.com/example", str(tmp_path),
        cookies_file="bilibili.txt", douyin_cookies_file="douyin.txt")
    assert calls["cookies_file"] == "douyin.txt"

def test_download_video_reports_yt_dlp_progress(monkeypatch, tmp_path):
    events = []
    output = tmp_path / "video.mp4"

    class FakeYoutubeDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def extract_info(self, _url, download):
            assert download is True
            hook = self.opts["progress_hooks"][0]
            hook({
                "status": "downloading",
                "downloaded_bytes": 50,
                "total_bytes": 100,
                "speed": 25,
                "eta": 2,
            })
            output.write_bytes(b"video")
            hook({
                "status": "finished",
                "downloaded_bytes": 100,
                "total_bytes": 100,
            })
            return {
                "id": "abc",
                "ext": "mp4",
                "title": "",
                "requested_downloads": [{"filepath": str(output)}],
            }

    monkeypatch.setattr(downloader.yt_dlp, "YoutubeDL", FakeYoutubeDL)
    monkeypatch.setattr(
        "autodub.media.douyin.is_douyin_url", lambda _url: False)
    monkeypatch.setattr(
        "autodub.media.bilibili.canonical_url", lambda url: url)

    downloader.download_video(
        "https://example.com/video",
        str(tmp_path),
        progress=events.append,
    )

    assert events[0] == {
        "status": "downloading",
        "downloaded_bytes": 50,
        "total_bytes": 100,
        "speed_bytes_s": 25.0,
        "eta_s": 2,
        "percent": 50,
    }
    assert events[-1]["status"] == "finished"
    assert events[-1]["percent"] == 100


def test_download_video_aborts_yt_dlp_when_cancelled(monkeypatch, tmp_path):
    cancel_event = threading.Event()

    class FakeYoutubeDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def extract_info(self, _url, download):
            hook = self.opts["progress_hooks"][0]
            cancel_event.set()
            hook({
                "status": "downloading",
                "downloaded_bytes": 1,
                "total_bytes": 100,
            })
            raise AssertionError("cancel hook did not abort download")

    monkeypatch.setattr(downloader.yt_dlp, "YoutubeDL", FakeYoutubeDL)
    monkeypatch.setattr(
        "autodub.media.douyin.is_douyin_url", lambda _url: False)
    monkeypatch.setattr(
        "autodub.media.bilibili.canonical_url", lambda url: url)

    with pytest.raises(downloader.PipelineCancelled):
        downloader.download_video(
            "https://example.com/video",
            str(tmp_path),
            cancel_event=cancel_event,
        )


def test_download_stream_aborts_and_removes_partial_file(monkeypatch, tmp_path):
    from autodub.media import douyin
    from autodub.progress import PipelineCancelled

    cancel_event = threading.Event()
    partial = tmp_path / "video.mp4.part"

    class Response:
        headers = {"Content-Length": "100", "Content-Type": "video/mp4"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size):
            cancel_event.set()
            yield b"chunk"

    monkeypatch.setattr(
        douyin,
        "_requests_client",
        lambda _cookies=None: type(
            "Client", (), {"get": lambda *_args, **_kwargs: Response()})(),
    )

    with pytest.raises(PipelineCancelled):
        douyin._download_stream(
            "https://cdn.example/video.mp4",
            tmp_path / "video.mp4",
            cancel_event=cancel_event,
        )

    assert not partial.exists()
