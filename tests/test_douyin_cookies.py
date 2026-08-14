import pytest

from autodub.media.douyin_cookies import (
    load_douyin_cookies,
    save_douyin_cookies,
    validate_douyin_cookies,
)


COOKIE_TEXT = (
    "# Netscape HTTP Cookie File\n"
    ".douyin.com\tTRUE\t/\tFALSE\t0\tsessionid\tsecret\n"
    ".iesdouyin.com\tTRUE\t/\tFALSE\t0\tmsToken\tvalue\n"
)


def test_save_and_load_douyin_netscape_cookies(tmp_path):
    path = tmp_path / "douyin-cookies.txt"
    save_douyin_cookies(COOKIE_TEXT, str(path))

    cookies = load_douyin_cookies(str(path))
    assert {cookie.name for cookie in cookies} == {"sessionid", "msToken"}
    assert path.read_text(encoding="utf-8").startswith(
        "# Netscape HTTP Cookie File"
    )


def test_douyin_cookie_validator_rejects_other_domains():
    with pytest.raises(ValueError, match="Douyin"):
        validate_douyin_cookies(
            "# Netscape HTTP Cookie File\n"
            ".example.com\tTRUE\t/\tFALSE\t0\tbad\tvalue\n"
        )


def test_douyin_cookie_validator_rejects_missing_header():
    with pytest.raises(ValueError, match="Netscape"):
        validate_douyin_cookies(".douyin.com\tTRUE\t/\tFALSE\t0\ta\tb\n")


def test_douyin_cookie_validator_accepts_httponly_domain():
    text = (
        "# Netscape HTTP Cookie File\n"
        "#HttpOnly_.douyin.com\tTRUE\t/\tTRUE\t0\tsessionid\tsecret\n"
    )
    assert validate_douyin_cookies(text)
