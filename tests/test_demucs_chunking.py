"""Toán chia khúc + crossfade của demucs_worker — thuần numpy, không cần torch."""
import numpy as np

from autodub.media.demucs_worker import crossfade_into, plan_chunks


def test_short_file_single_chunk():
    assert plan_chunks(1000, 4000, 100) == [(0, 1000)]


def test_chunks_cover_everything_with_exact_overlap():
    chunk, overlap = 400, 50
    ranges = plan_chunks(2000, chunk, overlap)
    # Bắt đầu từ 0, kết thúc đúng cuối file
    assert ranges[0][0] == 0
    assert ranges[-1][1] == 2000
    # Hai khoảng kề nhau chồng lấn đúng `overlap` khung
    for (s1, e1), (s2, e2) in zip(ranges, ranges[1:]):
        assert e1 - s2 == overlap
        assert s2 > s1
    # Khoảng cuối luôn dài hơn phần chồng lấn (đủ dữ liệu để crossfade)
    assert ranges[-1][1] - ranges[-1][0] > overlap


def test_last_chunk_absorbs_remainder():
    # 1000 khung, khúc 400, chồng lấn 100 → hop 300: 0-400, 300-700, 600-1000
    assert plan_chunks(1000, 400, 100) == [(0, 400), (300, 700), (600, 1000)]


def test_crossfade_endpoints_and_monotonic_blend():
    tail = np.ones((2, 10), dtype=np.float32)          # khúc trước: toàn 1
    head = np.zeros((2, 30), dtype=np.float32)         # khúc sau: toàn 0
    out = crossfade_into(tail, head)
    assert out is head
    # Khung đầu nghiêng hẳn về khúc trước, khung cuối vùng blend về khúc sau
    assert out[0, 0] == 1.0
    assert out[0, 9] == 0.0
    # Dốc tuyến tính giảm dần đều
    assert all(out[0, i] > out[0, i + 1] for i in range(9))
    # Ngoài vùng chồng lấn giữ nguyên khúc sau
    assert np.all(out[:, 10:] == 0.0)


def test_crossfade_identical_signals_is_identity():
    """Hai khúc trùng nhau ở vùng chồng lấn → crossfade không đổi gì."""
    rng = np.random.default_rng(7)
    seg = rng.standard_normal((2, 20)).astype(np.float32)
    head = seg.copy()
    crossfade_into(seg.copy(), head)
    np.testing.assert_allclose(head, seg, atol=1e-6)


def test_crossfade_handles_mismatched_lengths():
    tail = np.ones((2, 5), dtype=np.float32)
    head = np.zeros((2, 3), dtype=np.float32)
    out = crossfade_into(tail, head)   # không được nổ index
    assert out.shape == (2, 3)
