"""Khoá hành vi: whitelist job remote phải nhận giọng-theo-nhân-vật.

Hai khoá được thêm vào danh sách trắng: "speaker_voices" (request) và
"translate_context_sentences" (settings). Thêm khoá là nới bề mặt API, nên
phải khoá CẢ HAI CHIỀU: khoá mới được nhận, khoá lạ vẫn bị từ chối. Nếu chỉ
kiểm chiều "được nhận" thì một ngày nào đó whitelist bị gỡ hết mà test vẫn
xanh.
"""
from __future__ import annotations

import pytest

from autodub.remote_worker import JobValidationError, submit_job


def test_job_remote_nhan_duoc_giong_theo_nhan_vat(tmp_path):
    """Request mang bảng giọng theo nhân vật phải qua được kiểm tra job."""
    job_id = submit_job(
        str(tmp_path),
        {
            "job_id": "job-speakers",
            "request": {
                "file_path": str(tmp_path / "input.mp4"),
                "speaker_voices": {"speaker_01": "Minh", "speaker_02": "Lan"},
            },
        },
    )

    assert job_id == "job-speakers"


def test_job_remote_nhan_duoc_cua_so_ngu_canh_dich(tmp_path):
    """Settings mang cửa sổ ngữ cảnh dịch phải qua được kiểm tra job."""
    job_id = submit_job(
        str(tmp_path),
        {
            "job_id": "job-context",
            "request": {"file_path": str(tmp_path / "input.mp4")},
            "settings": {"translate_context_sentences": 12},
        },
    )

    assert job_id == "job-context"


def test_whitelist_van_tu_choi_khoa_la(tmp_path):
    """Nới danh sách trắng không được làm hở đường cho khoá lạ."""
    with pytest.raises(JobValidationError):
        submit_job(
            str(tmp_path),
            {
                "job_id": "job-la",
                "request": {"file_path": "x.mp4", "tuy_chon_la": 1},
            },
        )

    with pytest.raises(JobValidationError):
        submit_job(
            str(tmp_path),
            {
                "job_id": "job-la-2",
                "request": {"file_path": "x.mp4"},
                "settings": {"khoa_la": "x"},
            },
        )


def test_ban_do_giong_rong_van_hop_le(tmp_path):
    """Bảng giọng rỗng là hành vi cũ (một giọng), không được bị chặn."""
    job_id = submit_job(
        str(tmp_path),
        {
            "job_id": "job-rong",
            "request": {"file_path": "x.mp4", "speaker_voices": {}},
        },
    )

    assert job_id == "job-rong"
