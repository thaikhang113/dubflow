"""Cache giọng đọc phải nhớ GIỌNG của từng câu, không chỉ sự tồn tại của wav.

Lỗi cũ: đổi giọng rồi chạy tiếp thì mọi `seg_XXXXX.wav` cũ được dùng lại, nên
video vẫn mang giọng cũ dù cài đặt đã đổi. Bản đồ `.voice_map.json` buộc cổng
tái dùng phải so cả danh tính giọng.
"""
from __future__ import annotations

import json
import os
import wave

import pytest

from autodub.config import Settings
from autodub.languages import get_target
from autodub.pipeline import DubPipeline
from autodub.speech.tts import voices as voice_catalog
from autodub.utils import VOICE_MAP_NAME

TARGET = get_target("vi")


def _ghi_wav(path: str) -> None:
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 1600)


class _SynthGia:
    """Synth giả: ghi wav 0,1 s và ghi lại những câu đã đọc."""

    def __init__(self, voice: str) -> None:
        self.voice = voice
        self.calls: list[str] = []
        self.recommended_threads = 1

    def synthesize(self, text: str, output_path: str, target_duration=None):
        self.calls.append(text)
        _ghi_wav(output_path)
        return _KetQua(output_path)

    def close(self) -> None:
        pass


class _KetQua:
    def __init__(self, path: str) -> None:
        self._path = path

    def to_dict(self) -> dict:
        return {
            "path": self._path,
            "actual_duration": 0.1,
            "speed_adjusted": False,
            "rate_applied": "synth",
        }


def _doan(so_cau: int = 3) -> list[dict]:
    return [
        {"id": i, "start": float(i - 1), "end": float(i), "duration": 1.0,
         "text_vi": f"câu số {i}"}
        for i in range(1, so_cau + 1)
    ]


def _hai_giong(settings) -> tuple[str, str]:
    ten = [v.name for v in voice_catalog.catalog(settings)]
    if len(ten) < 2:
        pytest.skip("danh mục giọng có ít hơn 2 giọng")
    return ten[0], ten[1]


@pytest.fixture
def moi_truong(tmp_path):
    settings = Settings()
    seg_dir = tmp_path / "data" / "segments"
    seg_dir.mkdir(parents=True)
    return settings, DubPipeline(settings), str(seg_dir)


def _doc_ban_do(seg_dir: str) -> dict:
    with open(f"{seg_dir}/{VOICE_MAP_NAME}", encoding="utf-8") as f:
        return json.load(f)


def test_cung_giong_thi_dung_lai_clip_cu(moi_truong):
    settings, pipeline, seg_dir = moi_truong
    giong, _ = _hai_giong(settings)
    doan = _doan()

    lan1 = _SynthGia(giong)
    pipeline._synthesize_segments(TARGET, giong, doan, seg_dir, synth=lan1)
    assert len(lan1.calls) == 3

    lan2 = _SynthGia(giong)
    ket_qua = pipeline._synthesize_segments(TARGET, giong, doan, seg_dir,
                                            synth=lan2)
    assert lan2.calls == []
    assert [r["rate_applied"] for r in ket_qua] == ["cached"] * 3


def test_doi_giong_thi_doc_lai_toan_bo(moi_truong):
    settings, pipeline, seg_dir = moi_truong
    giong_a, giong_b = _hai_giong(settings)
    doan = _doan()

    pipeline._synthesize_segments(TARGET, giong_a, doan, seg_dir,
                                  synth=_SynthGia(giong_a))

    lan2 = _SynthGia(giong_b)
    ket_qua = pipeline._synthesize_segments(TARGET, giong_b, doan, seg_dir,
                                            synth=lan2)
    assert len(lan2.calls) == 3, "đổi giọng phải đọc lại, không dùng clip giọng cũ"
    assert all(r["rate_applied"] == "synth" for r in ket_qua)
    assert _doc_ban_do(seg_dir) == {"1": giong_b, "2": giong_b, "3": giong_b}


def test_thieu_ban_do_giong_thi_coi_nhu_cache_cu(moi_truong):
    settings, pipeline, seg_dir = moi_truong
    giong, _ = _hai_giong(settings)
    doan = _doan()

    pipeline._synthesize_segments(TARGET, giong, doan, seg_dir,
                                  synth=_SynthGia(giong))
    # Dự án cũ (trước bản đồ giọng): wav còn nhưng không biết giọng nào đọc.
    os.remove(os.path.join(seg_dir, VOICE_MAP_NAME))

    lan2 = _SynthGia(giong)
    pipeline._synthesize_segments(TARGET, giong, doan, seg_dir, synth=lan2)
    assert len(lan2.calls) == 3


def test_doi_giong_mot_cau_thi_chi_doc_lai_cau_do(moi_truong, monkeypatch):
    settings, pipeline, seg_dir = moi_truong
    giong_chinh, giong_phu = _hai_giong(settings)
    doan = _doan()

    pipeline._synthesize_segments(TARGET, giong_chinh, doan, seg_dir,
                                  synth=_SynthGia(giong_chinh))

    # Câu 2 đổi sang giọng phụ: nhánh serial tạo synth qua get_synthesizer.
    tao: dict[str, _SynthGia] = {}

    def _get(target, cfg, voice=None, num_workers=None):
        return tao.setdefault(voice, _SynthGia(voice or ""))

    monkeypatch.setattr("autodub.speech.tts.get_synthesizer", _get)
    doan[1]["voice"] = giong_phu
    pipeline._synthesize_segments(TARGET, giong_chinh, doan, seg_dir)
    assert _doc_ban_do(seg_dir)["2"] == giong_phu
    assert _doc_ban_do(seg_dir)["1"] == giong_chinh

    # Bỏ giọng riêng: chỉ câu 2 phải đọc lại bằng giọng chính.
    lan_cuoi = _SynthGia(giong_chinh)
    doan[1].pop("voice")
    ket_qua = pipeline._synthesize_segments(TARGET, giong_chinh, doan, seg_dir,
                                            synth=lan_cuoi)
    assert lan_cuoi.calls == ["câu số 2"]
    assert [r["rate_applied"] for r in ket_qua] == ["cached", "synth", "cached"]


def test_ensure_render_mode_xoa_ca_ban_do_giong(moi_truong):
    settings, pipeline, seg_dir = moi_truong
    giong, _ = _hai_giong(settings)
    doan = _doan()
    pipeline._synthesize_segments(TARGET, giong, doan, seg_dir,
                                  synth=_SynthGia(giong))
    # Giả lập cache của scheme cũ.
    with open(f"{seg_dir}/.render_mode", "w", encoding="utf-8") as f:
        f.write("per_fragment_v1")
    work_dir = os.path.dirname(os.path.dirname(seg_dir))

    pipeline._ensure_render_mode(work_dir, seg_dir)

    assert not [f for f in os.listdir(seg_dir) if f.endswith(".wav")]
    assert not os.path.exists(os.path.join(seg_dir, VOICE_MAP_NAME))
