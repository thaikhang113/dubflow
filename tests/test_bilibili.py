from autodub.media.bilibili import (
    canonical_url,
    has_login_cookies,
    save_netscape_cookies,
)


def test_canonical_url_strips_tracking_query():
    assert canonical_url(
        "https://www.bilibili.com/video/BV1ATDoYAENJ/?vd_source=x&spm_id_from=y"
    ) == "https://www.bilibili.com/video/BV1ATDoYAENJ"

def test_canonical_url_preserves_selected_part():
    assert canonical_url(
        "https://www.bilibili.com/video/BV1DbC9B5E8a/"
        "?p=3&vd_source=x&spm_id_from=y"
    ) == "https://www.bilibili.com/video/BV1DbC9B5E8a?p=3"


def test_cookie_validator_requires_auth_markers(tmp_path):
    path = tmp_path / "cookies.txt"
    path.write_text(
        "# Netscape HTTP Cookie File\n"
        ".bilibili.com\tTRUE\t/\tFALSE\t0\tSESSDATA\tvalue\n"
        ".bilibili.com\tTRUE\t/\tFALSE\t0\tDedeUserID\t123\n"
        ".bilibili.com\tTRUE\t/\tFALSE\t0\tbili_jct\tcsrf\n",
        encoding="utf-8",
    )
    assert has_login_cookies(str(path))


def test_save_netscape_cookies_rejects_non_bilibili_domains(tmp_path):
    path = tmp_path / "cookies.txt"
    text = (
        "# Netscape HTTP Cookie File\n"
        ".example.com\tTRUE\t/\tFALSE\t0\tSESSDATA\tvalue\n"
    )
    try:
        save_netscape_cookies(text, str(path))
    except ValueError as exc:
        assert "Bilibili" in str(exc)
    else:
        raise AssertionError("invalid cookie domain was accepted")

def test_save_netscape_cookies_rejects_lookalike_domain(tmp_path):
    path = tmp_path / "cookies.txt"
    text = (
        "# Netscape HTTP Cookie File\n"
        ".notbilibili.com\tTRUE\t/\tFALSE\t0\tSESSDATA\tvalue\n"
    )
    try:
        save_netscape_cookies(text, str(path))
    except ValueError:
        pass
    else:
        raise AssertionError("lookalike cookie domain was accepted")

def test_save_netscape_cookies_accepts_cookie_editor_line_format(tmp_path):
    path = tmp_path / "cookies.txt"
    text = (
        "# Netscape HTTP Cookie File\n"
        ".bilibili.com\nTRUE\n/\nFALSE\n0\nSESSDATA\nsession\n"
        ".bilibili.com\nTRUE\n/\nFALSE\n0\nDedeUserID\n123\n"
        ".bilibili.com\nTRUE\n/\nFALSE\n0\nbili_jct\ncsrf\n"
    )
    save_netscape_cookies(text, str(path))
    assert has_login_cookies(str(path))
    assert "\tSESSDATA\tsession\n" in path.read_text(encoding="utf-8")

def test_save_netscape_cookies_accepts_cookie_editor_httponly_domain(tmp_path):
    path = tmp_path / "cookies.txt"
    text = (
        "# Netscape HTTP Cookie File\n"
        "#HttpOnly_.bilibili.com\nTRUE\n/\nTRUE\n0\nSESSDATA\nsession\n"
        ".bilibili.com\nTRUE\n/\nFALSE\n0\nDedeUserID\n123\n"
        ".bilibili.com\nTRUE\n/\nTRUE\n0\nbili_jct\ncsrf\n"
    )
    save_netscape_cookies(text, str(path))
    assert has_login_cookies(str(path))


def test_patch_bilibili_extractor_installs():
    from autodub.media.bilibili import patch_bilibili_extractor
    patch_bilibili_extractor()
    import yt_dlp  # noqa: F401
    from yt_dlp.extractor.bilibili import BiliBiliIE
    # Verify patch exists on BiliBiliIE
    assert hasattr(BiliBiliIE, "_search_json")


def test_canonical_url_handles_av_id():
    assert canonical_url(
        "https://www.bilibili.com/video/av170001?p=2&spm_id=123"
    ) == "https://www.bilibili.com/video/av170001?p=2"


def test_bilibili_wbi_fallback_mock(monkeypatch):
    from autodub.media.bilibili import patch_bilibili_extractor
    patch_bilibili_extractor()
    import yt_dlp
    from yt_dlp.extractor.bilibili import BiliBiliIE

    ie = BiliBiliIE(yt_dlp.YoutubeDL({"quiet": True}))
    recorded = {}

    def fake_download_json(url, video_id, note="", query=None, headers=None, fatal=False):
        recorded["url"] = url
        recorded["video_id"] = video_id
        recorded["query"] = query
        return {
            "code": 0,
            "data": {
                "View": {"bvid": "BV1Test", "title": "Test Title", "cid": 12345},
                "Card": {"card": {"name": "Test UP"}},
                "Tags": [{"tag_name": "Game"}],
            },
        }

    monkeypatch.setattr(ie, "_download_json", fake_download_json)
    monkeypatch.setattr(ie, "_sign_wbi", lambda q, vid: dict(q, w_rid="mock_hash"))

    # Test fallback triggers when regex does not match window.__INITIAL_STATE__
    webpage = "<html><body>no initial state here</body></html>"
    res = ie._search_json(r"window\.__INITIAL_STATE__\s*=", webpage, "initial state", "1Test")
    assert res is not None
    assert res["videoData"]["bvid"] == "BV1Test"
    assert res["videoData"]["title"] == "Test Title"
    assert res["upData"]["name"] == "Test UP"
    assert recorded["video_id"] == "1Test"
    assert recorded["query"]["bvid"] == "BV1Test"

    # Test with numeric aid
    res_aid = ie._search_json(r"window\.__INITIAL_STATE__\s*=", webpage, "initial state", "170001")
    assert res_aid is not None
    assert recorded["query"]["aid"] == "170001"


