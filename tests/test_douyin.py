from autodub.media import douyin
from autodub.media.douyin_cookies import save_douyin_cookies


def test_share_info_rejects_embedded_different_video(monkeypatch):
    class Response:
        text = (
            '<script>window._ROUTER_DATA = {"loaderData":{"x":'
            '{"videoInfoRes":{"item_list":[{"aweme_id":"999",'
            '"video":{"play_addr":{"uri":"wrong"}}}]}}}}</script>'
        )

        def raise_for_status(self):
            pass

    monkeypatch.setattr(douyin.requests, "get", lambda *args, **kwargs: Response())
    assert douyin._fetch_share_info("123") is None


def test_transient_error_classifier():
    assert douyin._is_transient_error("502 Bad Gateway")
    assert douyin._is_transient_error("timed out")
    assert not douyin._is_transient_error("video is private")


def test_requests_client_loads_douyin_cookie_file(tmp_path):
    path = tmp_path / "douyin-cookies.txt"
    save_douyin_cookies(
        "# Netscape HTTP Cookie File\n"
        ".douyin.com\tTRUE\t/\tFALSE\t0\tsessionid\tsecret\n",
        str(path),
    )
    client = douyin._requests_client(str(path))
    assert client.cookies.get("sessionid") == "secret"


def test_modern_stream_capture_accepts_mp4_cdn_request():
    captured = []

    class Page:
        def on(self, event, callback):
            assert event in {"request", "response"}
            captured.append(callback)

    streams = douyin._capture_playwright_streams(Page())
    captured[0](type("Request", (), {
        "url": "https://v3.douyinvod.com/stream.mp4?br=8000"
    })())
    assert streams["progressive"] == [
        "https://v3.douyinvod.com/stream.mp4?br=8000"
    ]


def test_video_signature_rejects_html():
    assert douyin._is_video_signature(b"\x00\x00\x00\x18ftypisom")
    assert not douyin._is_video_signature(b"<html><head>")
