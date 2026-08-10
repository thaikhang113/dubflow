"""Danh mục giọng đọc: gộp nguồn, lọc, và chọn giọng an toàn.

Rủi ro lớn nhất của việc chọn giọng theo TÊN là chọn phải một cái tên không
có thật — tiến trình con sẽ chết với "unknown voice" sau khi người dùng đã
chờ xong bước nghe và dịch. Các bài kiểm thử ở đây khóa chặt điều đó lại.
"""
from __future__ import annotations

import json

import pytest

from autodub.config import Settings
from autodub.speech.tts import voice_library, voices


@pytest.fixture
def settings(tmp_path):
    """Cấu hình trỏ vào một thư mục model rỗng, tách khỏi máy thật."""
    return Settings(vieneu_model_dir=str(tmp_path / "vieneu"))


def write_custom(settings, presets: dict) -> None:
    path = settings.vieneu_custom_voices_path()
    import os
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"presets": presets}, f, ensure_ascii=False)


# ------------------------------------------------------------- danh mục --- #

def test_builtin_voices_are_always_available(settings):
    # Không còn builtin — catalog rỗng khi chưa có custom_voices.json
    assert voices.BUILTIN == ()
    # Khi có custom voices thì catalog hoạt động bình thường
    write_custom(settings, {
        voices.DEFAULT_VOICE: {"gender": "male", "source": "library"},
    })
    names = {v.name for v in voices.catalog(settings)}
    assert voices.DEFAULT_VOICE in names


def test_custom_voices_come_first_and_win_on_name_clash(settings):
    write_custom(settings, {
        "Trúc Ly": {"gender": "female", "country": "us", "source": "custom"},
        "Riêng": {"gender": "male", "region": "nam"},
    })
    catalog = voices.catalog(settings)
    assert [v.name for v in catalog[:2]] == ["Trúc Ly", "Riêng"]
    # Tên trùng chỉ còn MỘT mục, và là mục của người dùng.
    truc_ly = [v for v in catalog if v.name == "Trúc Ly"]
    assert len(truc_ly) == 1
    assert truc_ly[0].country == "us"


def test_source_decides_the_custom_badge(settings):
    write_custom(settings, {
        "Tự thêm": {"gender": "male"},
        "Từ thư viện": {"gender": "male", "source": "library"},
    })
    by_name = {v.name: v for v in voices.catalog(settings)}
    assert by_name["Tự thêm"].custom is True
    assert "Giọng bạn thêm" in by_name["Tự thêm"].label
    assert by_name["Từ thư viện"].custom is False
    assert "Giọng bạn thêm" not in by_name["Từ thư viện"].label


def test_capcut_catalog_is_available_without_any_local_install(settings):
    """22 giọng CapCut đọc từ Voice.json trong gói — không cần VieNeu, không mạng."""
    cap = [v for v in voices.catalog(settings) if v.is_capcut]
    assert len(cap) == 22
    assert {v.gender for v in cap} == {"male", "female"}
    for voice in cap:
        assert voice.custom is False
        assert "CapCut" in voice.label
        assert voices.source_group(voice) == "capcut"
        assert voices.is_capcut_voice(voice.name) is True


def test_offline_voices_are_never_mistaken_for_capcut(settings):
    write_custom(settings, {
        "Thư viện": {"gender": "male", "source": "library"},
        "Riêng": {"gender": "male"},
    })
    by_name = {v.name: v for v in voices.catalog(settings)}
    for name in ("Thư viện", "Riêng"):
        assert by_name[name].is_capcut is False
        assert "CapCut" not in by_name[name].label
        assert voices.source_group(by_name[name]) == "offline"
        assert voices.is_capcut_voice(name) is False


def test_stale_cloned_capcut_presets_do_not_shadow_the_api_voices(settings):
    """Máy cũ còn 16 giọng clone source="capcut" trùng tên với giọng API.

    Preset cũ phải bị bỏ hẳn, nếu không nó đứng trước và chắn mất giọng API
    — người dùng bấm "Thanh Lan" sẽ chạy VieNeu chứ không phải CapCut.
    """
    write_custom(settings, {"Thanh Lan": {"gender": "female",
                                          "source": "capcut"}})
    matches = [v for v in voices.catalog(settings) if v.name == "Thanh Lan"]
    assert len(matches) == 1
    assert matches[0].description  # mục từ Voice.json, không phải preset cũ


def test_query_capcut_finds_capcut_voices(settings):
    """Gõ "capcut" vào ô tìm kiếm phải ra đúng bộ giọng CapCut (khớp label)."""
    write_custom(settings, {"Hoàng Nam": {"gender": "male",
                                          "source": "library"}})
    names = {v.name for v in _matching(settings, query="capcut")}
    assert "Hoàng Nam" not in names
    assert names == {v.name for v in voices.catalog(settings) if v.is_capcut}


# ---------------------------------------------------------------- lọc ---- #

def _matching(settings, **filters):
    """Danh sách giọng lọt qua bộ lọc — đúng cách giao diện đang lọc."""
    return [v for v in voices.catalog(settings) if v.matches(**filters)]


def test_filters_narrow_the_list(settings):
    write_custom(settings, {
        "Hoàng Nam": {"gender": "male", "region": "bac", "source": "library"},
        "Mai Anh": {"gender": "female", "region": "bac", "source": "library"},
        "Gia Bảo": {"gender": "male", "region": "nam", "source": "library"},
    })
    male_north = _matching(settings, gender="male", region="bac")
    assert male_north
    for voice in male_north:
        assert voice.gender == "male" and voice.region == "bac"


def test_empty_filter_means_no_filtering(settings):
    assert len(_matching(settings)) == len(voices.catalog(settings))


def test_country_filter(settings):
    write_custom(settings, {"Emma": {"gender": "female", "country": "us"}})
    names = [v.name for v in _matching(settings, country="us")]
    assert names == ["Emma"]


def test_query_matches_the_visible_label(settings):
    write_custom(settings, {
        "Trúc Ly": {"gender": "female", "source": "library"},
        "Hoàng Nam": {"gender": "male", "source": "library"},
    })
    names = [v.name for v in _matching(settings, query="trúc")]
    assert "Trúc Ly" in names


# ------------------------------------------------------------- resolve --- #

def test_resolve_prefers_the_requested_name(settings):
    write_custom(settings, {
        "Mai Anh": {"gender": "female", "source": "library"},
        voices.DEFAULT_VOICE: {"gender": "male", "source": "library"},
    })
    assert voices.resolve(settings, "Mai Anh") == "Mai Anh"


def test_resolve_falls_back_to_the_configured_default(settings):
    write_custom(settings, {
        "Ngọc Linh": {"gender": "female", "source": "library"},
        voices.DEFAULT_VOICE: {"gender": "male", "source": "library"},
    })
    s = Settings(vieneu_model_dir=settings.vieneu_model_dir,
                 vieneu_voice="Ngọc Linh")
    assert voices.resolve(s, None) == "Ngọc Linh"


def test_resolve_never_returns_an_unknown_name(settings):
    """Tên lạ phải rơi về một giọng CÓ THẬT, không được trả lại nguyên trạng."""
    write_custom(settings, {
        voices.DEFAULT_VOICE: {"gender": "male", "source": "library"},
    })
    picked = voices.resolve(settings, "Không Hề Tồn Tại")
    assert picked in {v.name for v in voices.catalog(settings)}


def test_resolve_ignores_an_unknown_configured_default(settings):
    write_custom(settings, {
        voices.DEFAULT_VOICE: {"gender": "male", "source": "library"},
    })
    s = Settings(vieneu_model_dir=settings.vieneu_model_dir,
                 vieneu_voice="Giọng Ma")
    assert voices.resolve(s, None) == voices.DEFAULT_VOICE


def test_broken_custom_file_does_not_break_the_catalog(settings):
    """File hỏng không được làm sập catalog — chỉ mất phần giọng offline."""
    import os
    path = settings.vieneu_custom_voices_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("{ hỏng")
    catalog = voices.catalog(settings)   # không ném lỗi
    assert all(v.is_capcut for v in catalog)


def test_resolve_falls_back_to_capcut_when_nothing_offline_is_installed(
        settings):
    """Máy chưa cài VieNeu vẫn phải chọn được một giọng có thật (CapCut)."""
    picked = voices.resolve(settings, None)
    assert voices.is_capcut_voice(picked)


# ------------------------------------------------------------ thư viện --- #

def _manifest(tmp_path, entries: list[dict]) -> str:
    folder = tmp_path / "bo_giong"
    folder.mkdir(parents=True, exist_ok=True)
    for entry in entries:
        (folder / entry["file_name"]).write_bytes(b"RIFF fake wav")
    with open(folder / voice_library.MANIFEST_NAME, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False)
    return str(tmp_path)


def test_library_scan_reads_the_manifest(tmp_path):
    root = _manifest(tmp_path, [
        {"file_name": "vn_male_01_Hoàng_Nam.wav", "display_name": "Hoàng Nam",
         "gender": "male", "country": "vn"},
        {"file_name": "us_female_01_Emma.wav", "display_name": "Emma",
         "gender": "female", "language": "en"},
    ])
    found = voice_library.scan(root)
    assert [v.name for v in found] == ["Hoàng Nam", "Emma"]
    assert found[0].country == "vn"
    # Không ghi country thì suy ra từ ngôn ngữ.
    assert found[1].country == "us"


def test_library_skips_entries_whose_file_is_missing(tmp_path):
    root = _manifest(tmp_path, [
        {"file_name": "co_that.wav", "display_name": "Có Thật"},
    ])
    import os
    os.remove(os.path.join(root, "bo_giong", "co_that.wav"))
    assert voice_library.scan(root) == []


def test_library_infers_a_name_from_the_file_name(tmp_path):
    root = _manifest(tmp_path, [{"file_name": "vn_male_01_Gia_Bảo.wav"}])
    assert [v.name for v in voice_library.scan(root)] == ["Gia Bảo"]


def test_library_batch_item_marks_the_source(tmp_path):
    root = _manifest(tmp_path, [
        {"file_name": "a.wav", "display_name": "A", "gender": "male"}])
    item = voice_library.scan(root)[0].to_batch_item()
    assert item["source"] == "library"
    assert item["name"] == "A" and item["gender"] == "male"


def test_missing_library_folder_is_not_an_error(tmp_path):
    assert voice_library.scan(str(tmp_path / "khong-co")) == []
