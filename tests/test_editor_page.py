"""Test trình chỉnh sửa: bảng giọng theo nhân vật."""

import json
from types import SimpleNamespace

from autodub.editor import SPEAKER_VOICES_KEY
from autodub.pipeline import (
    SPEAKER_MAP_NAME,
    _apply_speaker_voices,
    _clean_speaker_voices,
    _speaker_map_payload,
    _write_speaker_map,
)
from autodub.speech.diarization import speaker_segment_counts


def _real_voice_names() -> list[str]:
    from autodub.speech import voice_catalog

    try:
        names = [voice.name for voice in voice_catalog.catalog()]
    except Exception:
        return []
    return [name for name in names if name]


def test_clean_speaker_voices_giữ_nguyên_hành_vi_khi_rỗng():
    assert _clean_speaker_voices(None) == {}
    assert _clean_speaker_voices("") == {}
    assert _clean_speaker_voices([]) == {}
    assert _clean_speaker_voices({"speaker_01": "  "}) == {}
    assert _clean_speaker_voices({"  speaker_01  ": "  Minh  "}) == {
        "speaker_01": "Minh",
    }


def test_apply_speaker_voices_bật_thì_gán_tắt_thì_giữ_nguyên():
    segments = [
        {"id": 1, "speaker_id": "speaker_01", "text": "a"},
        {"id": 2, "speaker_id": "speaker_02", "text": "b"},
        {"id": 3, "speaker_id": "speaker_01", "text": "c"},
    ]

    # Bảng rỗng: trả về CHÍNH danh sách cũ, không sao chép — hành vi cũ
    # (một giọng cho cả video) phải không đổi một byte nào.
    assert _apply_speaker_voices(segments, {}) is segments

    assigned = _apply_speaker_voices(segments, {"speaker_01": "Minh"})
    assert [item.get("voice") for item in assigned] == ["Minh", None, "Minh"]
    assert segments[0].get("voice") is None


def test_apply_speaker_voices_giọng_gán_tay_trên_câu_thắng_bảng_chung():
    segments = [
        {"id": 1, "speaker_id": "speaker_01", "voice": "Lan"},
    ]

    assigned = _apply_speaker_voices(segments, {"speaker_01": "Minh"})

    assert assigned[0]["voice"] == "Lan"


def test_write_speaker_map_ghi_tệp_và_đếm_đúng_số_câu(tmp_path):
    work_dir = str(tmp_path / "project")
    (tmp_path / "project").mkdir()
    segments = [
        {"id": 1, "speaker_id": "speaker_01", "voice": "Minh"},
        {"id": 2, "speaker_id": "speaker_01", "voice": "Minh"},
        {"id": 3, "speaker_id": "speaker_02"},
    ]
    target = SimpleNamespace(code="vi")

    path = _write_speaker_map(
        work_dir, segments, {"speaker_01": "Minh"}, "Gốc", target)

    assert path.endswith(SPEAKER_MAP_NAME)
    payload = json.loads(open(path, encoding="utf-8").read())
    assert payload["default_voice"] == "Gốc"
    assert payload["target"] == "vi"
    by_speaker = {s["speaker_id"]: s for s in payload["speakers"]}
    assert by_speaker["speaker_01"]["voice"] == "Minh"
    assert by_speaker["speaker_01"]["assigned"] is True
    assert by_speaker["speaker_01"]["segments"] == 2
    assert by_speaker["speaker_02"]["assigned"] is False
    assert by_speaker["speaker_02"]["segments"] == 1


def test_speaker_map_payload_đếm_lại_khi_không_truyền_counts():
    segments = [
        {"id": 1, "speaker_id": "speaker_02"},
        {"id": 2, "speaker_id": "speaker_01"},
        {"id": 3, "speaker_id": "speaker_01"},
    ]
    target = SimpleNamespace(code="vi")

    payload = _speaker_map_payload(segments, {}, "Gốc", target)

    assert [s["speaker_id"] for s in payload["speakers"]] == [
        "speaker_01", "speaker_02",
    ]
    assert payload["speakers"][0]["segments"] == 2
    assert payload["speakers"][0]["assigned"] is False

    """Hỗ trợ: tìm tệp bảng giọng mà pipeline ghi trong thư mục dự án."""


def _render_opts_path(work_dir: str) -> str:
    from autodub.editor import RENDER_OPTS_NAME
    from autodub.workdir import data_path

    return data_path(work_dir, RENDER_OPTS_NAME)


def _find_speaker_map_path(work_dir: str, name: str) -> str:
    from autodub.workdir import data_path

    return data_path(work_dir, name, create_dir=True)


class _FakeValues:
    """Thay cho export_panel.values() trong trình chỉnh sửa."""

    def __init__(self, values: dict):
        self._values = dict(values)

    def values(self) -> dict:
        return dict(self._values)


class _FakeSpeakerPanel:
    """Thay cho SpeakerPanel: chỉ cần đúng phần lưu/đọc đang kiểm."""

    def __init__(self, mapping: dict):
        self._mapping = dict(mapping)

    def speaker_voices(self) -> dict:
        return dict(self._mapping)

    def reload(self, settings=None) -> None:
        pass

    def set_speakers(self, speakers, default_voice: str) -> None:
        self._speakers = list(speakers)
        self._default = default_voice

    def set_speaker_voices(self, mapping) -> None:
        self._mapping = dict(mapping or {})




def test_hai_cụm_nhân_vật_nhận_được_hai_giọng_khác_nhau():
    """Hai cụm diarization phải ra hai giọng khác nhau, không dùng chung."""
    from autodub.speech.diarization import assign_speakers

    embeddings = [
        [1.0, 0.0],
        [0.99, 0.05],
        [0.0, 1.0],
        [0.05, 0.99],
    ]
    segments = [
        {"id": index, "start": float(index), "end": index + 1.0,
         "text": "câu"}
        for index in range(len(embeddings))
    ]
    from autodub.speech.diarization import cluster_embeddings
    labels = cluster_embeddings(embeddings, threshold=0.8)
    with_speakers = assign_speakers(segments, labels)

    speakers = sorted({s["speaker_id"] for s in with_speakers})
    assert len(speakers) == 2

    voices = {speakers[0]: "Giọng A", speakers[1]: "Giọng B"}
    assigned = _apply_speaker_voices(with_speakers, voices)

    heard = [s["voice"] for s in assigned]
    assert heard == ["Giọng A", "Giọng A", "Giọng B", "Giọng B"]
    assert heard[0] != heard[2]


def test_trang_chỉnh_sửa_đọc_được_bảng_giọng_và_ghi_lại(tmp_path):
    from autodub_gui.pages.editor_page import EditorPage

    work_dir = str(tmp_path / "project")
    (tmp_path / "project").mkdir()
    panel = _FakeSpeakerPanel({"speaker_01": "Minh"})
    page = SimpleNamespace(
        _work_dir=work_dir,
        speaker_panel=panel,
        audio_panel=_FakeValues({}),
        background_panel=_FakeValues({}),
        voice_panel=_FakeValues({}),
        export_panel=_FakeValues({"subtitle_mode": "none"}),
        _save_timeline_state=lambda: None,
    )

    EditorPage._save_render_opts(page)

    opts = json.loads(
        open(_render_opts_path(work_dir), encoding="utf-8").read())
    assert opts[SPEAKER_VOICES_KEY] == {"speaker_01": "Minh"}

    # Bỏ gán hết thì khoá phải biến mất, không để lại bảng rỗng trong tệp.
    panel.speaker_voices = dict
    EditorPage._save_render_opts(page)
    opts = json.loads(
        open(_render_opts_path(work_dir), encoding="utf-8").read())
    assert SPEAKER_VOICES_KEY not in opts


def test_trang_chỉnh_sửa_đọc_bảng_giọng_do_pipeline_ghi(tmp_path):
    from autodub_gui.pages.editor_page import EditorPage

    work_dir = str(tmp_path / "project")
    (tmp_path / "project").mkdir()
    data_dir = tmp_path / "project"
    data_dir.mkdir(exist_ok=True)
    payload = {
        "version": 1,
        "default_voice": "Giọng gốc",
        "speakers": [
            {"speaker_id": "speaker_01", "voice": "",
             "assigned": False, "segments": 4},
            {"speaker_id": "speaker_02", "voice": "",
             "assigned": False, "segments": 1},
        ],
    }
    page = SimpleNamespace(_work_dir=work_dir)

    found = _find_speaker_map_path(work_dir, SPEAKER_MAP_NAME)
    with open(found, "w", encoding="utf-8") as stream:
        json.dump(payload, stream)

    read_back = EditorPage._read_speaker_map(page)

    assert read_back == payload


def test_trang_chỉnh_sửa_chịu_được_bảng_giọng_hỏng(tmp_path):
    from autodub_gui.pages.editor_page import EditorPage

    work_dir = str(tmp_path / "project")
    (tmp_path / "project").mkdir()
    found = _find_speaker_map_path(work_dir, SPEAKER_MAP_NAME)
    with open(found, "w", encoding="utf-8") as stream:
        stream.write("khong phai json")
    page = SimpleNamespace(_work_dir=work_dir)

    assert EditorPage._read_speaker_map(page) == {}


def test_speaker_segment_counts_bỏ_qua_câu_không_có_nhân_vật():
    counts = speaker_segment_counts([
        {"speaker_id": "speaker_01"},
        {"id": 2},
        {"speaker_id": ""},
    ])

    assert counts == {"speaker_01": 1}

# -- Đổi giọng theo nhân vật rồi bấm Xuất video (t13) -------------------


class _Signal:
    """Tín hiệu Qt giả: chỉ cần đủ để mã nối dây gọi vào."""

    def connect(self, slot) -> None:
        pass


def _export_page(*, applied, current, confirm):
    """Dựng trang giả cho luồng xuất và ghi lại các câu hỏi đã hỏi.

    ``applied`` là bảng giọng đã được đọc lại gần nhất, ``current`` là
    bảng đang hiện trên giao diện, ``confirm`` là câu trả lời cho hộp
    thoại cảnh báo. Worker được thay bằng đồ giả để hàm xuất chạy hết
    mà không mở tiến trình nào.
    """
    from autodub_gui.pages.editor_page import EditorPage

    asked = []
    tabs = []
    started = []

    def _ask(parent, title, message, **kwargs):
        asked.append({'title': title, 'message': message, **kwargs})
        return confirm, False

    class _Worker:
        log = _Signal()
        finished = _Signal()
        finished_ok = _Signal()
        failed = _Signal()
        cancelled = _Signal()
        progress = _Signal()

        def __init__(self, *args, **kwargs):
            started.append(self)

        def start(self) -> None:
            pass

        def cancel(self) -> None:
            pass

    class _Log:
        @staticmethod
        def reset_log() -> None:
            pass

        @staticmethod
        def append_log(line: str) -> None:
            pass

        @staticmethod
        def setVisible(value: bool) -> None:
            pass

    class _Narrator:
        @staticmethod
        def reset() -> None:
            pass

    # export_panel.subtitle là một THUỘC TÍNH (LabeledCombo), không phải
    # phương thức — nên phải gán đối tượng chứ không phải hàm tĩnh.
    class _ExportPanel:
        subtitle = SimpleNamespace(current_key=lambda: 'none')

        @staticmethod
        def set_running(value: bool) -> None:
            pass

        @staticmethod
        def set_status(text: str) -> None:
            pass

    class _VoicePanel:
        @staticmethod
        def project_voice() -> str:
            return 'Giọng chung'

        @staticmethod
        def has_pending_voice_change() -> bool:
            return False

    page = SimpleNamespace(
        _work_dir='du-an-gia',
        _project=SimpleNamespace(title='Dự án thử'),
        speaker_panel=_FakeSpeakerPanel(current),
        _speaker_voices_applied=dict(applied),
        voice_panel=_VoicePanel(),
        background_panel=_FakeValues({'bg_mode': 'none', 'bg_duck_db': -18}),
        export_panel=_ExportPanel(),
        log=_Log(),
        _narrator=_Narrator(),
        _dirty_ids=set(),
        _structural_edit=False,
        _blur_regions=[],
        _subtitle_style=None,
        _busy_warn=lambda: False,
        _flush_edits=lambda: None,
        _render_settings=lambda: 'cai-dat',
        target_key=lambda: 'final',
        _show_tab=lambda key: tabs.append(key),
        set_status=lambda text: None,
        release_video=lambda: 0.0,
    )
    # Các khe nối tín hiệu của worker xuất: chỉ cần tồn tại để nối dây.
    for name in ('_on_export_done', '_on_export_failed',
                 '_on_export_cancelled', '_on_progress_log'):
        setattr(page, name, lambda *args, **kwargs: None)
    page.has_unapplied_speaker_voices = (
        lambda: EditorPage.has_unapplied_speaker_voices(page))
    return page, asked, tabs, started, _ask, _Worker


def _run_export(page, monkeypatch, ask, worker_cls):
    """Chạy EditorExportMixin._export() với hộp thoại và worker giả."""
    from autodub_gui.pages import editor_export
    from autodub_gui.ui import modal

    from autodub_gui import workers as gui_workers

    # _export() nhập RebuildWorker ngay trong thân hàm, nên phải thay ở
    # chính mô-đun nguồn chứ không phải mô-đun editor_export.
    monkeypatch.setattr(modal.ConfirmDialog, 'ask', staticmethod(ask))
    monkeypatch.setattr(gui_workers, 'RebuildWorker', worker_cls)
    monkeypatch.setattr(
        editor_export, 'REGISTRY',
        SimpleNamespace(start_job=lambda *args, **kwargs: None))
    editor_export.VoiceAndExportMixin._export(page)


def test_đổi_giọng_nhân_vật_rồi_xuất_thì_cảnh_báo_trước(monkeypatch):
    """Đổi giọng một nhân vật rồi bấm Xuất video phải hỏi trước."""
    page, asked, tabs, started, ask, worker = _export_page(
        applied={'speaker_01': 'Minh'},
        current={'speaker_01': 'Lan'},
        confirm=False,
    )

    _run_export(page, monkeypatch, ask, worker)

    assert len(asked) == 1, 'phải cảnh báo đúng một lần'
    assert asked[0]['title'] == 'Giọng nhân vật mới chưa được áp dụng'
    assert asked[0]['kind'] == 'warning'
    assert 'đọc lại' in asked[0]['message']
    assert asked[0]['confirm_label'] == 'Cứ xuất với giọng cũ'


def test_huỷ_cảnh_báo_thì_không_xuất_và_về_thẻ_giọng_đọc(monkeypatch):
    """Chọn huỷ ở cảnh báo: không xuất video, quay về thẻ Giọng đọc."""
    page, asked, tabs, started, ask, worker = _export_page(
        applied={'speaker_01': 'Minh'},
        current={'speaker_01': 'Lan'},
        confirm=False,
    )

    _run_export(page, monkeypatch, ask, worker)

    assert started == [], 'huỷ thì không được dựng worker xuất nào'
    assert tabs == ['voice'], 'phải đưa người dùng về thẻ Giọng đọc'


def test_xác_nhận_cảnh_báo_thì_vẫn_xuất_bình_thường(monkeypatch):
    """Chọn xác nhận: cảnh báo không được chặn cứng việc xuất."""
    page, asked, tabs, started, ask, worker = _export_page(
        applied={'speaker_01': 'Minh'},
        current={'speaker_01': 'Lan'},
        confirm=True,
    )

    _run_export(page, monkeypatch, ask, worker)

    assert len(asked) == 1
    assert len(started) == 1, 'xác nhận thì phải chạy worker xuất'
    assert tabs == [], 'đã xác nhận thì không đổi thẻ'


def test_bảng_khớp_bản_đọc_lại_thì_không_cảnh_báo(monkeypatch):
    """Bảng giọng đã khớp bản đọc lại gần nhất: không hỏi gì."""
    page, asked, tabs, started, ask, worker = _export_page(
        applied={'speaker_01': 'Minh'},
        current={'speaker_01': 'Minh'},
        confirm=True,
    )

    _run_export(page, monkeypatch, ask, worker)

    assert asked == []
    assert len(started) == 1


def test_đổi_rồi_đổi_ngược_về_giọng_cũ_thì_không_cảnh_báo():
    """Đổi giọng rồi đổi ngược về giá trị cũ: coi như chưa đổi."""
    from autodub_gui.pages.editor_page import EditorPage

    panel = _FakeSpeakerPanel({'speaker_01': 'Minh'})
    page = SimpleNamespace(
        speaker_panel=panel,
        _speaker_voices_applied=None,
    )
    EditorPage.mark_speaker_voices_applied(page)  # mốc so sánh: Minh

    # Người dùng đổi sang Lan rồi đổi ngược lại Minh.
    panel.set_speaker_voices({'speaker_01': 'Lan'})
    assert EditorPage.has_unapplied_speaker_voices(page) is True
    panel.set_speaker_voices({'speaker_01': 'Minh'})
    assert EditorPage.has_unapplied_speaker_voices(page) is False


def test_dự_án_không_có_nhân_vật_thì_luồng_xuất_y_hệt_trước(monkeypatch):
    """Không có nhân vật nào: bảng rỗng, luồng xuất không đổi."""
    page, asked, tabs, started, ask, worker = _export_page(
        applied={},
        current={},
        confirm=True,
    )

    _run_export(page, monkeypatch, ask, worker)

    assert asked == [], 'dự án không có nhân vật thì không hỏi gì'
    assert len(started) == 1


def test_đọc_lại_giọng_nhân_vật_xong_thì_hết_cảnh_báo():
    """«Lưu tất cả và đọc lại» xong phải cập nhật mốc đã áp dụng."""
    from autodub_gui.pages import editor_export
    from autodub_gui.pages.editor_page import EditorPage

    panel = _FakeSpeakerPanel({'speaker_01': 'Lan'})
    page = SimpleNamespace(
        speaker_panel=panel,
        _speaker_voices_applied={'speaker_01': 'Minh'},
        _dirty_ids={7},
        _structural_edit=True,
        _refresh_banner=lambda: None,
        restore_video=lambda *args, **kwargs: None,
        _resynth_resume_pos=1.0,
        _resynth_covers_voice=True,
        voice_panel=SimpleNamespace(
            mark_voice_applied=lambda: None,
            picker=SimpleNamespace(voice=lambda: 'Giọng chung'),
            finish_progress=lambda *args, **kwargs: None,
        ),
    )
    page._pin_project_voice = lambda voice: None
    page.mark_speaker_voices_applied = (
        lambda: EditorPage.mark_speaker_voices_applied(page))
    page.has_unapplied_speaker_voices = (
        lambda: EditorPage.has_unapplied_speaker_voices(page))

    editor_export.VoiceAndExportMixin._on_resynth_done(page, [7])

    assert page._dirty_ids == set()
    assert page.has_unapplied_speaker_voices() is False

