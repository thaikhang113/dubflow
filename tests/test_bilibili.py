from autodub.media.bilibili import canonical_url, has_login_cookies


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
