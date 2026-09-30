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


def test_build_ydl_opts_enables_fragment_concurrency(tmp_path):
    opts = downloader.build_ydl_opts(
        str(tmp_path), fragment_workers=4)
    assert opts["concurrent_fragment_downloads"] == 4
    assert opts["noplaylist"] is True

def test_download_video_uses_single_selected_bilibili_part(
    monkeypatch, tmp_path
):
    captured = {}
    output = tmp_path / "video.mp4"

    class FakeYoutubeDL:
        def __init__(self, opts):
            captured["opts"] = opts

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def extract_info(self, url, download):
            captured["url"] = url
            output.write_bytes(b"video")
            return {
                "id": "BV1DbC9B5E8a_p3",
                "ext": "mp4",
                "title": "",
                "requested_downloads": [{"filepath": str(output)}],
            }

    monkeypatch.setattr(downloader.yt_dlp, "YoutubeDL", FakeYoutubeDL)
    monkeypatch.setattr(
        "autodub.media.douyin.is_douyin_url", lambda _url: False)

    downloader.download_video(
        "https://www.bilibili.com/video/BV1DbC9B5E8a/"
        "?p=3&spm_id_from=search",
        str(tmp_path),
    )

    assert captured["url"] == "https://www.bilibili.com/video/BV1DbC9B5E8a?p=3"
    assert captured["opts"]["noplaylist"] is True


def test_download_stream_aborts_and_removes_partial_file(monkeypatch, tmp_path):
    from autodub.media import douyin
    from autodub.progress import PipelineCancelled

    cancel_event = threading.Event()
    partial = tmp_path / "video.mp4.part"

    class Response:
        headers = {"Content-Length": "100", "Content-Type": "video/mp4"}  # noqa: RUF012

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

def test_format_download_progress():
    from autodub.media.downloader import format_download_progress

    data = {
        "percent": 35.4,
        "total_bytes": int(2.8 * 1024**3),
        "speed_bytes_s": 14.5 * 1024**2,
        "eta_s": 128,
    }
    formatted = format_download_progress(data)
    assert "[download]" in formatted
    assert "35.4%" in formatted
    assert "2.80GiB" in formatted
    assert "14.5MiB/s" in formatted
    assert "ETA 02:08" in formatted


def test_narrator_acquire_progress():
    from autodub.progress import ProgressEvent
    from autodub_gui.log_text import Narrator

    narrator = Narrator()
    event = ProgressEvent(
        step="acquire",
        status="progress",
        detail="[download]  35.4% of ~2.80GiB at 14.5MiB/s ETA 02:08",
        current=35,
        total=100,
    )
    result = narrator.narrate(event)
    assert result is not None
    text, level, is_progress = result
    assert is_progress is True
    assert "[download]  35.4% of ~2.80GiB" in text


def test_transient_error_detection():
    import ssl
    import urllib.error
    from yt_dlp.utils import DownloadError

    # Standard network errors
    assert downloader.is_transient_download_error(ConnectionResetError("peer reset"))
    assert downloader.is_transient_download_error(TimeoutError("socket timeout"))
    assert downloader.is_transient_download_error(ssl.SSLEOFError("EOF in SSL"))

    # Windows socket errors
    win_timeout = urllib.error.URLError(
        "[WinError 10060] A connection attempt failed because the connected "
        "party did not properly respond after a period of time"
    )
    assert downloader.is_transient_download_error(win_timeout)

    win_reset = urllib.error.URLError(
        "[WinError 10054] An existing connection was forcibly closed by the remote host"
    )
    assert downloader.is_transient_download_error(win_reset)

    win_unreach = OSError(10065, "A socket operation was attempted to an unreachable host")
    win_unreach.winerror = 10065
    assert downloader.is_transient_download_error(win_unreach)

    # yt-dlp wrapped DownloadError
    dl_err = DownloadError(
        "ERROR: [BiliBili] Unable to download API page: "
        "<urlopen error [WinError 10060] A connection attempt failed>"
    )
    assert downloader.is_transient_download_error(dl_err)

    # Incomplete read / partial download
    assert downloader.is_transient_download_error(
        Exception("IncompleteRead(975 bytes read, 469233162 more expected)")
    )

    # Transient HTTP codes
    assert downloader.is_transient_download_error(
        Exception("HTTP Error 412: Precondition Failed")
    )
    assert downloader.is_transient_download_error(
        Exception("HTTP Error 429: Too Many Requests")
    )
    assert downloader.is_transient_download_error(
        Exception("HTTP Error 503: Service Unavailable")
    )

    # Non-transient errors must NOT be retried
    assert not downloader.is_transient_download_error(
        Exception("HTTP Error 404: Not Found")
    )
    assert not downloader.is_transient_download_error(
        Exception("HTTP Error 403: Forbidden")
    )
    assert not downloader.is_transient_download_error(
        Exception("video is private or unavailable")
    )


def test_extract_info_backoff_schedule(monkeypatch):
    calls = []
    sleeps = []

    class FailingYdl:
        def extract_info(self, url, download):
            calls.append(url)
            raise ConnectionResetError("Connection lost")

    monkeypatch.setattr(downloader.time, "sleep", sleeps.append)

    with pytest.raises(ConnectionResetError):
        downloader._extract_info_with_retry(
            FailingYdl(), "https://example.com", attempts=5
        )

    assert len(calls) == 5
    # Backoff schedule: 2s, 5s, 10s, 20s
    assert sleeps == [2, 5, 10, 20]


def test_is_partial_name():
    assert downloader._is_partial_name("video.mp4.part")
    assert downloader._is_partial_name("video.mp4.ytdl")
    assert downloader._is_partial_name("video.f100026.mp4")
    assert downloader._is_partial_name("BV12c9hBhExH.f30280.m4a")
    assert not downloader._is_partial_name("video.mp4")
    assert not downloader._is_partial_name("BV12c9hBhExH.mp4")


def test_configure_aria2c_opts(monkeypatch):
    opts = {}
    # When aria2c is available
    monkeypatch.setattr(downloader.shutil, "which", lambda cmd: "C:\\bin\\aria2c.exe" if cmd == "aria2c" else None)
    monkeypatch.delenv("DUBFLOW_DISABLE_ARIA2C", raising=False)

    enabled = downloader.configure_aria2c_opts(opts, max_connections=8)
    assert enabled is True
    assert opts["external_downloader"] == {"default": "aria2c"}
    assert "-s" in opts["external_downloader_args"]["aria2c"]
    assert "8" in opts["external_downloader_args"]["aria2c"]

    # When disabled via env var
    monkeypatch.setenv("DUBFLOW_DISABLE_ARIA2C", "1")
    opts_disabled = {}
    enabled_disabled = downloader.configure_aria2c_opts(opts_disabled)
    assert enabled_disabled is False
    assert "external_downloader" not in opts_disabled

    # When aria2c binary is not found
    monkeypatch.delenv("DUBFLOW_DISABLE_ARIA2C", raising=False)
    monkeypatch.setattr(downloader.shutil, "which", lambda _cmd: None)
    opts_missing = {}
    enabled_missing = downloader.configure_aria2c_opts(opts_missing)
    assert enabled_missing is False
    assert "external_downloader" not in opts_missing


