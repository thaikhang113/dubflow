"""Kiểm thử THẬT bảng giọng theo nhân vật trong Trình chỉnh sửa.

Vì sao có tệp này: bộ test cũ dùng một SpeakerPanel GIẢ (_FakeSpeakerPanel) nên
không hề dựng lớp thật. Hệ quả là lỗi trong lớp thật vẫn cho test xanh. Ở đây
dựng panel thật trong Qt offscreen và kiểm hành vi thật — bộ test này đã bắt
được hai lỗi thật của SpeakerPanel (xem chú thích trong editor_panels.py).
"""
from __future__ import annotations

import pytest

from autodub_gui.pages.editor_panels import SpeakerPanel, speaker_map_speakers


@pytest.fixture
def qt_app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture
def panel(qt_app):
    """Panel thật, đã nạp danh mục giọng của máy."""
    p = SpeakerPanel()
    p.reload()
    yield p
    p.deleteLater()


NHAN_VAT = [
    {"speaker_id": "speaker_01", "voice": "", "segments": 12},
    {"speaker_id": "speaker_02", "voice": "", "segments": 3},
]


def _mot_giong_that(panel) -> str:
    """Một tên giọng CÓ THẬT trong danh mục của máy này.

    Dùng tên động thay vì viết cứng: danh mục đọc từ voices/ nên đổi theo máy,
    và một tên bịa sẽ khiến set_key không tìm thấy lựa chọn — đó là lỗi của
    test, không phải của panel.
    """
    if not panel._voices:
        pytest.skip("máy này không có danh mục giọng để kiểm thử")
    return panel._voices[0]


def test_dung_duoc_panel_that_va_hien_khi_co_nhan_vat(panel):
    """Lớp thật phải dựng được và hiện ra khi có nhân vật."""
    panel.set_speakers(NHAN_VAT, "Giọng chung")

    assert len(panel._combos) == 2
    assert panel.isVisible(), "có nhân vật thì bảng phải hiện"


def test_nhan_vat_de_nguyen_giong_chung_thi_khong_duoc_ghi(panel):
    """Mặc định mọi nhân vật đọc giọng chung: bảng ghim phải RỖNG.

    Đây là điều giữ nguyên hành vi cũ (một giọng cho cả video): nếu nhân vật
    chưa được gán mà vẫn lọt vào bảng, tệp cấu hình phình ra và lần chạy sau
    tưởng người dùng đã chọn giọng riêng.
    """
    panel.set_speakers(NHAN_VAT, "Giọng chung")

    assert panel.speaker_voices() == {}


def test_gan_giong_cho_mot_nhan_vat_chi_ghi_nhan_vat_do(panel):
    """Gán giọng cho speaker_02 thì speaker_01 vẫn không xuất hiện."""
    giong = _mot_giong_that(panel)
    panel.set_speakers(NHAN_VAT, "Giọng chung")
    panel._combos["speaker_02"].set_key(giong)

    assert panel.speaker_voices() == {"speaker_02": giong}


def test_ghi_lai_ban_do_da_luu_len_cac_o_chon(panel):
    """Mở lại dự án: bảng đã ghim phải hiện đúng trên các ô chọn."""
    giong = _mot_giong_that(panel)
    panel.set_speakers(NHAN_VAT, "Giọng chung")
    panel.set_speaker_voices({"speaker_01": giong})

    assert panel.speaker_voices() == {"speaker_01": giong}


def test_doi_giong_roi_doi_nguoc_ve_giong_chung_thi_bang_rong_lai(panel):
    """Chọn giọng rồi bỏ chọn: bảng phải trở về rỗng, không giữ rác."""
    giong = _mot_giong_that(panel)
    panel.set_speakers(NHAN_VAT, "Giọng chung")
    panel._combos["speaker_01"].set_key(giong)
    assert panel.speaker_voices() == {"speaker_01": giong}

    panel._combos["speaker_01"].set_key("")
    assert panel.speaker_voices() == {}


def test_khong_co_nhan_vat_thi_bang_tu_an(panel):
    """Dự án chưa nhận diện nhân vật: bảng ẩn, không có dòng nào."""
    panel.set_speakers([], "Giọng chung")

    assert panel._combos == {}
    assert not panel.isVisible()
    assert panel.speaker_voices() == {}


def test_giong_da_ghim_qua_set_speakers_van_giu_duoc_ten(panel):
    """Giọng đã ghim mà máy này không có trong danh mục vẫn phải giữ tên.

    Xảy ra khi mở dự án tạo ở máy khác có giọng tự học. Âm thầm rơi về giọng
    chung là mất thông tin của người dùng. Đi qua set_speakers (đường nạp lúc
    mở dự án) — đây là ca đã bắt được lỗi thứ tự _options/_voice_key.
    """
    panel.set_speakers([{"speaker_id": "speaker_01", "voice": "GiongLa"}],
                       "Giọng chung")

    assert panel.speaker_voices() == {"speaker_01": "GiongLa"}


def test_giong_la_ghim_qua_render_opts_cung_giu_duoc_ten(panel):
    """Cùng ca trên nhưng đi qua set_speaker_voices (đường render_opts)."""
    panel.set_speakers(NHAN_VAT, "Giọng chung")
    panel.set_speaker_voices({"speaker_02": "GiongLa"})

    assert panel.speaker_voices() == {"speaker_02": "GiongLa"}


def test_speaker_map_speakers_doc_tep_hop_le():
    """Đọc speaker_map.json: lấy đúng danh sách nhân vật và giọng chung."""
    payload = {
        "version": 1,
        "default_voice": "Minh",
        "speakers": [
            {"speaker_id": "speaker_01", "voice": "Minh", "segments": 12},
            {"speaker_id": "speaker_02", "voice": "Lan", "segments": 3},
        ],
    }

    rows, default_voice = speaker_map_speakers(payload)

    assert default_voice == "Minh"
    assert len(rows) == 2


@pytest.mark.parametrize("payload", [
    None,
    "chuoi",
    [],
    123,
    {},
    {"speakers": "khong-phai-list"},
    {"speakers": [{"khong_co_id": 1}]},
])
def test_speaker_map_speakers_tep_hong_tra_rong(payload):
    """Tệp thiếu/hỏng không được làm gãy trình sửa — trả rỗng."""
    rows, default_voice = speaker_map_speakers(payload)

    assert rows == []
    assert default_voice == ""
