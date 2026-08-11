from autodub.media.bilibili import (
    canonical_url, has_login_cookies, save_netscape_cookies,
)


def test_canonical_url_strips_tracking_query():
    assert canonical_url(
        "https://www.bilibili.com/video/BV1ATDoYAENJ/?vd_source=x&spm_id_from=y"
    ) == "https://www.bilibili.com/video/BV1ATDoYAENJ"


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
