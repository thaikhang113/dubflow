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
