"""Tests for Vietnamese number normalization (autodub.text.vi_numbers)."""
from autodub.text.vi_numbers import normalize_vi_text, number_to_words


def test_basic_numbers():
    assert number_to_words(0) == "không"
    assert number_to_words(5) == "năm"
    assert number_to_words(15) == "mười lăm"
    assert number_to_words(21) == "hai mươi mốt"
    assert number_to_words(24) == "hai mươi tư"
    assert number_to_words(25) == "hai mươi lăm"
    assert number_to_words(105) == "một trăm lẻ năm"
    assert number_to_words(2759) == "hai nghìn bảy trăm năm mươi chín"


def test_millions():
    assert number_to_words(1299000) == "một triệu hai trăm chín mươi chín nghìn"


def test_grouped_thousands_collapse():
    assert "một triệu hai trăm chín mươi chín nghìn" in normalize_vi_text(
        "giá 1.299.000 đồng")


def test_product_code_read_digit_by_digit():
    out = normalize_vi_text("RTX 5060 Ti")
    assert "năm không sáu không" in out


def test_units():
    assert normalize_vi_text("8G") == "tám gigabyte"
    assert normalize_vi_text("32MB") == "ba mươi hai megabyte"
    assert normalize_vi_text("90%") == "chín mươi phần trăm"


def test_decimal():
    assert normalize_vi_text("4.0") == "bốn phẩy không"
    assert "ba phẩy năm gigahertz" in normalize_vi_text("3.5GHz")


def test_leading_zero_digit_by_digit():
    assert normalize_vi_text("0909") == "không chín không chín"


def test_text_without_digits_untouched():
    s = "xin chào các bạn, hôm nay trời đẹp"
    assert normalize_vi_text(s) == s
