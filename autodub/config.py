"""Cấu hình ứng dụng — đọc từ biến môi trường / tệp ``.env``.

An toàn với giao diện: nạp module này (hay gọi ``Settings.load()``) không bao
giờ làm thoát tiến trình. API Key chỉ được kiểm tra vào lúc một bước thật
sự cần tới, qua :meth:`Settings.require`, và lỗi thiếu cấu hình là
:class:`ConfigError` để giao diện bắt và hiển thị tử tế.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

from autodub.utils import app_root


class ConfigError(Exception):
    """Ném ra khi một mục cấu hình bắt buộc còn trống ngay lúc cần dùng."""


def _auto_vieneu_workers() -> int:
    """Số tiến trình giọng đọc mặc định — theo RAM trống và số nhân CPU.

    Mỗi tiến trình VieNeu chiếm ~1.5 GB RAM. Máy 8 GB mà chạy 3 tiến trình
    (4.5 GB) cộng Demucs + giao diện là tràn bộ nhớ, hệ điều hành swap và
    MỌI THỨ chậm đi — 3 luồng lúc đó còn chậm hơn 1 luồng. VIENEU_MAX_WORKERS
    trong .env khai báo tường minh luôn thắng giá trị tự tính này.
    """
    from autodub.sysinfo import available_ram_gb

    cores = os.cpu_count() or 4
    by_cpu = max(1, cores // 2)

    avail = available_ram_gb()
    # ~1.5 GB/tiến trình, chừa ~3 GB cho giao diện + Demucs + hệ điều hành.
    # Công thức này giữ nguyên số luồng của máy 6-10 GB như trước, nhưng máy
    # khỏe (24-32 GB, nhiều nhân) không còn bị kẹp ở 3 nữa — TTS là bước lâu
    # nhất nên trần thấp làm mất phần lớn hiệu năng sẵn có.
    if avail is None:          # không đọc được RAM — giữ mặc định an toàn
        by_ram = 3
    else:
        by_ram = max(1, int((avail - 3.0) // 1.5))

    workers = max(1, min(_VIENEU_WORKER_CEILING, by_ram, by_cpu))
    if workers < _VIENEU_WORKER_CEILING:
        _log_governor_once(workers, avail, cores)
    return workers


#: Trần cho số tiến trình giọng đọc tự tính. Trên mức này lợi ích giảm nhanh
#: (tranh nhân CPU giữa các tiến trình ONNX) mà RAM vẫn tăng tuyến tính.
_VIENEU_WORKER_CEILING = 6


_governor_logged = False


def _log_governor_once(workers: int, avail: float | None, cores: int) -> None:
    """Báo MỘT lần mỗi phiên khi tự hạ số luồng giọng đọc (tránh spam log
    vì Settings.load() được giao diện gọi lại mỗi lần lưu cài đặt)."""
    global _governor_logged
    if _governor_logged:
        return
    _governor_logged = True
    from autodub.utils import setup_logging

    ram_txt = f"{avail:.1f} GB RAM trống" if avail is not None else "RAM không rõ"
    setup_logging("autodub.config").info(
        f"Máy này ({ram_txt}, {cores} nhân) — chạy {workers} luồng giọng đọc "
        f"để không tràn bộ nhớ. Đặt VIENEU_MAX_WORKERS trong .env nếu muốn khác."
    )




def _one_of(value: str, allowed: tuple[str, ...], default: str) -> str:
    """Chuẩn hóa một mục kiểu danh sách, sai chính tả thì lấy giá trị mặc định.

    Gõ nhầm trong .env không được phép làm sập giao diện, nên hàm này dễ tính.
    """
    v = value.strip().lower()
    return v if v in allowed else default


# Mức chất lượng — MỘT nút vặn (QUALITY_PRESET) đặt sẵn giá trị mặc định cho
# các mục chi tiết bên dưới. Biến môi trường khai báo tường minh luôn thắng.
_PRESETS: dict[str, dict[str, str]] = {
    # Nhanh: ưu tiên tốc độ, chấp nhận chất lượng thấp hơn.
    "fast": {
        "whisper_model": "medium",
        "hq_background": "false",
        "translate_analysis": "false",
        "translate_review": "false",
        "karaoke_alignment": "false",
    },
    # Cân bằng (mặc định): mọi cải tiến chất lượng chính, chi phí vừa phải.
    "balanced": {
        "whisper_model": "auto",
        "hq_background": "true",
        "translate_analysis": "true",
        "translate_review": "true",
        "karaoke_alignment": "true",
    },
    # Chất lượng cao: chấp nhận chậm — ASR lớn, đủ mọi lượt kiểm tra.
    "quality": {
        "whisper_model": "auto",
        "hq_background": "true",
        "translate_analysis": "true",
        "translate_review": "true",
        "karaoke_alignment": "true",
    },
}

@dataclass
class Settings:
    # Mức chất lượng: một nút vặn đặt mặc định hợp lý cho các mục chi tiết
    # ("fast" | "balanced" | "quality"). Biến môi trường riêng vẫn ghi đè.
    quality_preset: str = "balanced"

    # --- Nghe và chép lời (ASR) -------------------------------------------
    # Whisper chạy trên máy, miễn phí. Model lớn hơn = đúng hơn nhưng chậm hơn.
    # "auto" = large-v3 khi có CUDA, medium khi chỉ có CPU.
    whisper_model: str = "auto"
    # Bộ nhận dạng: "whisper" (mặc định, mọi ngôn ngữ) | "paraformer" (chuyên
    # tiếng Trung, chạy CPU/ONNX trong .venv-asr — cài bằng
    # scripts/setup_paraformer.py; tự quay về Whisper khi chưa cài).
    asr_engine: str = "paraformer"
    asr_venv_python: str = ""       # mặc định: <app>/.venv-asr/Scripts/python.exe
    paraformer_model_dir: str = ""  # mặc định: <app>/models/paraformer-zh
    asr_num_threads: int = 4
    # Beam size của Whisper (1–10). 5 là mặc định của thư viện — giữ nguyên
    # chất lượng. Máy CPU yếu có thể hạ (vd 1) để nhanh gấp 2–3 lần, đổi lại
    # kém chính xác hơn một chút — đây là lựa chọn CHỦ ĐỘNG, không tự hạ.
    whisper_beam_size: int = 5
    # Whisper chạy trong venv riêng (.venv-whisper) khi đã cài
    # scripts/setup_whisper.py — faster-whisper + ctranslate2 không cần bundle
    # trong exe, giảm ~112 MB. Khi venv chưa có, app tự dùng faster-whisper
    # đã cài trong môi trường hiện tại (dev) hoặc báo lỗi nếu thiếu (exe).
    whisper_venv_python: str = ""   # mặc định: <app>/.venv-whisper/Scripts/python.exe
    whisper_model_dir: str = ""     # mặc định: <app>/models/whisper (cache HuggingFace)

    # --- OCR phụ đề cứng (PaddleOCR, tùy chọn) ------------------------------
    ocr_enabled: bool = True
    ocr_venv_python: str = ""
    ocr_model_dir: str = ""
    ocr_device: str = "auto"  # "auto" | "gpu" | "cpu"
    ocr_min_confidence: float = 0.80
    ocr_max_region_area: float = 0.25
    ocr_subtitle_y_min: float = 0.65
    ocr_sample_interval: float = 1.0

    # --- Giọng đọc tiếng Việt (VieNeu — bộ giọng DUY NHẤT) -----------------
    # Chạy trong venv riêng (.venv-vieneu) qua tiến trình con — cài một lần
    # bằng scripts/setup_vieneu.py. Chạy CPU/ONNX nên không tốn VRAM và không
    # tranh card đồ họa với Whisper/Demucs.
    vieneu_venv_python: str = ""   # mặc định: <app>/.venv-vieneu/Scripts/python.exe
    vieneu_model_dir: str = ""     # mặc định: <app>/models/vieneu
    #: Tên giọng mặc định cho dự án mới (xem autodub.speech.tts.voices).
    vieneu_voice: str = ""
    vieneu_style: str = "tu_nhien"   # "tu_nhien" | "tin_tuc" | "doc_truyen"
    vieneu_clone_enabled: bool = False
    vieneu_clone_source: str = "video"  # "video" | "file"
    vieneu_clone_reference_audio: str = ""
    vieneu_clone_min_seconds: float = 1.0
    vieneu_clone_max_seconds: float = 8.0
    # Số tiến trình con chạy song song (~1.5 GB RAM mỗi cái). Chạy trên CPU
    # nên tăng số luồng là nhanh lên gần như tuyến tính, tới khi hết nhân.
    vieneu_max_workers: int = 3

    # Hiệu năng: số luồng cho các bước nặng (gửi việc cho bộ giọng, nhóm
    # ffmpeg atempo, dịch qua mạng). Tự tính theo CPU lúc nạp cấu hình;
    # PARALLEL_WORKERS trong .env là lối thoát hiểm cho người biết việc.
    parallel_workers: int = 4

    # HAI nút vặn thời lượng — không tự căn, không cắt, không nén từng câu.
    # Giọng luôn đọc ở voice_speed; video luôn chạy ở video_speed. Tiếng Việt
    # dài hơn tiếng Trung khoảng 20% nên VIDEO_SPEED≈0.82 cho bản lồng tiếng
    # đủ chỗ thở. Còn chồng tiếng thì hạ video_speed (hoặc tăng voice_speed)
    # rồi chạy lại — giọng đọc đã có sẵn nên chạy lại rất nhanh.
    video_speed: float = 1.0    # 1.0 = giữ nguyên; 0.82 = video dài thêm 22%
    voice_speed: float = 1.0    # áp cố định cho mọi câu (0.5–2.0)

    # Ngân sách dịch (số ký tự trên mỗi giây khung thời gian). Số nhỏ hơn ép
    # bản dịch ngắn lại nên ít tràn hơn.
    translate_cps_budget: float = 12.5

    # --- Chất lượng âm thanh ----------------------------------------------
    # Nhạc nền chất lượng cao: rút thêm original_audio_hq.wav 44.1 kHz stereo
    # riêng cho Demucs + bản trộn cuối (bản 16 kHz mono chỉ dành cho ASR).
    hq_background: bool = True
    # Chuẩn hóa âm lượng + fade từng câu (EBU R128 loudnorm, highpass 80 Hz,
    # fade 15 ms). Tắt = giữ nguyên bản thô từ bộ giọng.
    voice_postprocess: bool = True
    voice_target_lufs: float = -16.0
    # Nhạc nền tự nhỏ đi khi có giọng và hồi lại ở khoảng lặng. 0 = tắt.
    bg_duck_voice_db: float = -7.0
    # Chống chồng tiếng "mềm": câu dài hơn khung thì DỒN TRỄ các câu sau vào
    # khoảng lặng kế tiếp (có trần tổng), tuyệt đối không đổi tốc độ đọc từng
    # câu. Chỉ khi kịch trần mới nén nhẹ và đều, với trần thấp.
    soft_timing_fit: bool = True
    timing_max_drift_s: float = 1.5     # trần dồn trễ tích lũy
    timing_min_gap_s: float = 0.12      # khoảng thở tối thiểu giữa hai câu
    timing_max_atempo: float = 1.1      # trần nén bất khả kháng (mỗi câu)

    # --- Ngữ cảnh dịch do người dùng cung cấp (đều không bắt buộc) ---------
    translate_domain: str = ""       # chủ đề, vd "review công nghệ"
    translate_context: str = ""      # mô tả tự do (nhiều dòng)
    translate_pronouns: str = ""     # quy ước xưng hô, vd "mình – các bạn"
    translate_glossary: str = ""     # thuật ngữ cố định, mỗi dòng "gốc = dịch"
    translate_style_notes: str = ""  # yêu cầu thêm về giọng văn
    # Tiêu đề video gốc — KHÔNG nạp từ .env: pipeline tự bơm mỗi lượt chạy
    # (đọc data/video_meta.json do downloader ghi) vào bản sao Settings để
    # prompt dịch/phân tích biết video nói về gì ngay từ tiêu đề.
    translate_video_title: str = ""

    # --- Dịch hai lượt ----------------------------------------------------
    # Lượt 0 "hiểu video": trước khi dịch, gửi toàn bộ lời thoại gốc để rút ra
    # tóm tắt + nhân vật/xưng hô + thuật ngữ, rồi tự bơm vào ngữ cảnh dịch
    # (mục người dùng điền tay luôn được ưu tiên hơn).
    translate_analysis: bool = True
    # Lượt rà soát: sau khi dịch, soát các câu nghi vấn (vượt ngân sách nhiều,
    # còn ký tự CJK, quá ngắn so với câu gốc) rồi dịch lại đúng các câu đó.
    translate_review: bool = True

    # --- Chung ------------------------------------------------------------
    default_source_lang: str = "zh-CN"
    audio_sample_rate: int = 16000
    output_dir: str = "./output"
    vietnamese_output_dir: str = ""
    # Tự dọn tệp trung gian ngay khi xuất video xong. Tắt mặc định vì dọn
    # rồi thì không sửa từng câu hay xuất lại dự án đó được nữa.
    auto_clean_intermediates: bool = False

    # --- Cập nhật và hỗ trợ -----------------------------------------------
    # Kho GitHub chứa bản phát hành (dạng "chủ/kho") — dùng để báo bản mới.
    update_repo: str = "ttthanh2044/voxdub"
    # Đường dẫn biểu mẫu nhận báo lỗi và góp ý từ người dùng.
    support_url: str = "https://github.com/ttthanh2044/voxdub/issues"

    # Liên kết video mặc định (dùng khi giao diện/chạy hàng loạt không đưa nguồn)
    video_url: str = ""

    # --- Nội dung đăng bài ------------------------------------------------
    # Tạo tiêu đề/mô tả/hashtag sau mỗi lần lồng tiếng (máy chủ viết).
    # Tắt = bỏ hẳn bước này (và không tốn Vox).
    generate_metadata: bool = True

    # --- Dịch tự động -----------------------------------------------------
    # Mô hình, lời nhắc và API key đều nằm trên máy chủ VoxDub — app chỉ gửi
    # câu thoại và ngữ cảnh. Hai nút vặn dưới đây là thứ duy nhất còn lại ở
    # phía máy khách vì chúng quyết định cách CHIA VIỆC, không phải cách dịch.
    translate_enabled: bool = True
    # Số câu mỗi lượt gửi lên máy chủ (trần cứng phía máy chủ là 120).
    translate_batch_size: int = 20
    translation_endpoint: str = ""
    translation_api_key: str = ""
    translation_model: str = ""
    bilibili_cookies_file: str = ""

    # --- Phụ đề -----------------------------------------------------------
    # Kiểu mặc định: "none" | "soft" (tệp rời) | "burn" (ghi thẳng vào hình)
    subtitle_mode: str = "none"
    #: Bộ kiểu chữ dựng sẵn (xem autodub.media.subtitle.PRESETS).
    subtitle_preset: str = "clean"
    subtitle_position: str = "bottom"   # "bottom" | "middle" | "top"
    subtitle_font: str = "Arial"
    subtitle_font_size: int = 22
    subtitle_margin_v: int = 40         # khoảng cách tới mép (điểm ảnh ASS)
    subtitle_outline: int = 2           # độ dày viền chữ
    subtitle_shadow: int = 0            # độ đổ bóng
    subtitle_bold: bool = True
    subtitle_color: str = "#FFFFFF"
    subtitle_outline_color: str = "#000000"
    # Nền sau chữ: "none" (chỉ viền) | "box" (khối nền đặc kiểu CapCut)
    subtitle_box: str = "none"
    subtitle_box_color: str = "#000000"
    subtitle_box_opacity: int = 60      # 0–100, chỉ có nghĩa khi box = "box"
    # Số CHỮ mỗi hàng do người dùng chốt. 0 = tự xuống dòng theo bề rộng chuẩn.
    subtitle_line_words: int = 0
    subtitle_max_lines: int = 2
    subtitle_all_caps: bool = False

    # --- Phụ đề theo cụm chữ (nhảy theo giọng đọc, chỉ chế độ ghi vào hình) -
    # "sentence" (cả câu) | "karaoke" (cụm chữ .ass)
    subtitle_display: str = "sentence"
    karaoke_words_per_cue: int = 3      # 1-5 chữ mỗi cụm
    karaoke_effect: str = "pop"         # "pop" | "fade" | "karaoke" | "none"
    karaoke_highlight_color: str = "#FFD54A"
    # Khớp mốc chữ THẬT bằng Whisper nghe lại giọng đọc (~30-60s/video).
    # Tắt = ước lượng theo âm tiết (nhanh, kém chính xác hơn một chút).
    karaoke_alignment: bool = True

    # ------------------------------------------------------------------ #

    @classmethod
    def load(cls, env_file: str | None = None, override: bool = False) -> "Settings":
        """Dựng Settings từ môi trường (sau khi nạp ``.env``).

        ``override=True`` đọc lại .env đè lên biến môi trường đã đặt — giao
        diện dùng để nạp nóng cài đặt ngay sau khi lưu tệp.
        """
        if env_file:
            load_dotenv(env_file, override=override)
        else:
            # Luôn là tệp .env nằm cạnh ứng dụng (thư mục chứa exe khi đã
            # đóng gói) — không phụ thuộc thư mục người dùng đang đứng.
            load_dotenv(os.path.join(app_root(), ".env"), override=override)

        def env(key: str, default: str = "", *aliases: str) -> str:
            for k in (key, *aliases):
                value = os.environ.get(k)
                if value is not None:
                    return value
            return default

        def env_int(key: str, default: str) -> int:
            try:
                return int(float(env(key, default)))
            except ValueError:
                return int(float(default))

        def env_float(key: str, default: str) -> float:
            try:
                return float(env(key, default))
            except ValueError:
                return float(default)

        def env_dir(key: str, default: str) -> str:
            """Mục thư mục; đường dẫn tương đối neo vào thư mục ứng dụng."""
            value = env(key, default).strip()
            if value and not os.path.isabs(value):
                value = os.path.normpath(os.path.join(app_root(), value))
            return value

        def env_multiline(key: str) -> str:
            """Mục nhiều dòng, lưu trên một dòng .env với ký tự \\n."""
            return env(key).replace("\\n", "\n").strip()

        def env_bool(key: str, default: str) -> bool:
            return env(key, default).strip().lower() in ("1", "true", "yes")

        # Mức chất lượng: nền mặc định cho các mục chi tiết. Biến môi trường
        # tường minh vẫn thắng (env() đọc chúng trước khi dùng tới preset).
        preset = _one_of(env("QUALITY_PRESET", "balanced"),
                         ("fast", "balanced", "quality"), "balanced")
        _p = _PRESETS[preset]

        # Tự tính số luồng theo CPU: một nửa số nhân logic, kẹp trong 2–8.
        auto_workers = str(min(8, max(2, (os.cpu_count() or 4) // 2)))

        return cls(
            quality_preset=preset,
            whisper_model=env("WHISPER_MODEL", _p["whisper_model"]),
            asr_engine=_one_of(env("ASR_ENGINE", "paraformer"),
                               ("whisper", "paraformer"), "paraformer"),
            asr_venv_python=env("ASR_VENV_PYTHON"),
            paraformer_model_dir=env("PARAFORMER_MODEL_DIR"),
            asr_num_threads=max(1, min(16, env_int("ASR_NUM_THREADS", "4"))),
            whisper_beam_size=max(1, min(10, env_int("WHISPER_BEAM_SIZE", "5"))),
            ocr_enabled=env_bool("OCR_ENABLED", "true"),
            ocr_venv_python=env("OCR_VENV_PYTHON"),
            ocr_model_dir=env("OCR_MODEL_DIR"),
            ocr_device=_one_of(env("OCR_DEVICE", "auto"),
                               ("auto", "gpu", "cpu"), "auto"),
            ocr_min_confidence=min(0.99, max(0.5,
                env_float("OCR_MIN_CONFIDENCE", "0.80"))),
            ocr_max_region_area=min(0.8, max(0.02,
                env_float("OCR_MAX_REGION_AREA", "0.25"))),
            ocr_subtitle_y_min=min(0.95, max(0.0,
                env_float("OCR_SUBTITLE_Y_MIN", "0.65"))),
            ocr_sample_interval=min(10.0, max(0.5,
                env_float("OCR_SAMPLE_INTERVAL", "1.0"))),
            vieneu_venv_python=env("VIENEU_VENV_PYTHON"),
            vieneu_model_dir=env("VIENEU_MODEL_DIR"),
            vieneu_voice=env("VIENEU_VOICE", "").strip(),
            vieneu_style=_one_of(env("VIENEU_STYLE", "tu_nhien"),
                                 ("tu_nhien", "tin_tuc", "doc_truyen"),
                                 "tu_nhien"),
            vieneu_clone_enabled=env_bool("VIENEU_CLONE_ENABLED", "false"),
            vieneu_clone_source=_one_of(env("VIENEU_CLONE_SOURCE", "video"),
                                        ("video", "file"), "video"),
            vieneu_clone_reference_audio=env("VIENEU_CLONE_REFERENCE_AUDIO").strip(),
            vieneu_clone_min_seconds=min(8.0, max(1.0,
                env_float("VIENEU_CLONE_MIN_SECONDS", "1.0"))),
            vieneu_clone_max_seconds=min(8.0, max(1.0,
                env_float("VIENEU_CLONE_MAX_SECONDS", "8.0"))),
            # Người dùng đặt tay thì tôn trọng; chưa đặt thì tự tính theo
            # RAM trống + số nhân (xem _auto_vieneu_workers).
            vieneu_max_workers=max(1, min(8, env_int(
                "VIENEU_MAX_WORKERS",
                "3" if env("VIENEU_MAX_WORKERS")
                else str(_auto_vieneu_workers())))),
            parallel_workers=max(1, min(16, env_int("PARALLEL_WORKERS",
                                                    auto_workers))),
            video_speed=min(1.0, max(0.5, env_float("VIDEO_SPEED", "1.0"))),
            voice_speed=min(2.0, max(0.5, env_float("VOICE_SPEED", "1.0"))),
            translate_cps_budget=env_float("TRANSLATE_CPS_BUDGET", "12.5"),
            hq_background=env_bool("HQ_BACKGROUND", _p["hq_background"]),
            voice_postprocess=env_bool("VOICE_POSTPROCESS", "true"),
            voice_target_lufs=env_float("VOICE_TARGET_LUFS", "-16.0"),
            bg_duck_voice_db=min(0.0, max(-24.0,
                env_float("BG_DUCK_VOICE_DB", "-7.0"))),
            soft_timing_fit=env_bool("SOFT_TIMING_FIT", "true"),
            timing_max_drift_s=min(5.0, max(0.0,
                env_float("TIMING_MAX_DRIFT_S", "1.5"))),
            timing_min_gap_s=min(1.0, max(0.0,
                env_float("TIMING_MIN_GAP_S", "0.12"))),
            timing_max_atempo=min(1.3, max(1.0,
                env_float("TIMING_MAX_ATEMPO", "1.1"))),
            translate_analysis=env_bool("TRANSLATE_ANALYSIS",
                                        _p["translate_analysis"]),
            translate_review=env_bool("TRANSLATE_REVIEW",
                                      _p["translate_review"]),
            translate_domain=env("TRANSLATE_DOMAIN").strip(),
            translate_context=env_multiline("TRANSLATE_CONTEXT"),
            translate_pronouns=env("TRANSLATE_PRONOUNS").strip(),
            translate_glossary=env_multiline("TRANSLATE_GLOSSARY"),
            translate_style_notes=env_multiline("TRANSLATE_STYLE_NOTES"),
            default_source_lang=env("DEFAULT_SOURCE_LANG", "zh-CN"),
            audio_sample_rate=env_int("AUDIO_SAMPLE_RATE", "16000"),
            output_dir=env_dir("OUTPUT_DIR", "./output"),
            vietnamese_output_dir=env_dir("VIETNAMESE_OUTPUT_DIR", ""),
            auto_clean_intermediates=env_bool("AUTO_CLEAN_INTERMEDIATES",
                                              "false"),
            update_repo=env("UPDATE_REPO",
                            "ttthanh2044/voxdub").strip(),
            support_url=env("SUPPORT_URL",
                            "https://github.com/ttthanh2044/voxdub/issues").strip(),
            video_url=env("VIDEO_URL"),
            generate_metadata=env("GENERATE_METADATA", "true").strip().lower()
                              not in ("0", "false", "no"),
            translate_enabled=env("TRANSLATE_ENABLED", "true").strip().lower()
                              not in ("0", "false", "no"),
            translate_batch_size=max(1, min(40,
                env_int("TRANSLATE_BATCH_SIZE", "20"))),
            translation_endpoint=env("TRANSLATION_ENDPOINT").strip(),
            translation_api_key=env("TRANSLATION_API_KEY").strip(),
            translation_model=env("TRANSLATION_MODEL").strip(),
            bilibili_cookies_file=env("BILIBILI_COOKIES_FILE").strip(),
            subtitle_mode=_one_of(env("SUBTITLE_MODE", "none"),
                                  ("none", "soft", "burn"), "none"),
            subtitle_preset=env("SUBTITLE_PRESET", "clean").strip() or "clean",
            subtitle_position=_one_of(env("SUBTITLE_POSITION", "bottom"),
                                      ("bottom", "middle", "top"), "bottom"),
            subtitle_font=env("SUBTITLE_FONT", "Arial"),
            subtitle_font_size=env_int("SUBTITLE_FONT_SIZE", "22"),
            subtitle_margin_v=env_int("SUBTITLE_MARGIN_V", "40"),
            subtitle_outline=env_int("SUBTITLE_OUTLINE", "2"),
            subtitle_shadow=max(0, min(8, env_int("SUBTITLE_SHADOW", "0"))),
            subtitle_bold=env_bool("SUBTITLE_BOLD", "true"),
            subtitle_color=env("SUBTITLE_COLOR", "#FFFFFF"),
            subtitle_outline_color=env("SUBTITLE_OUTLINE_COLOR", "#000000"),
            subtitle_box=_one_of(env("SUBTITLE_BOX", "none"),
                                 ("none", "box"), "none"),
            subtitle_box_color=env("SUBTITLE_BOX_COLOR", "#000000"),
            subtitle_box_opacity=max(0, min(100,
                env_int("SUBTITLE_BOX_OPACITY", "60"))),
            subtitle_line_words=max(0, min(12,
                env_int("SUBTITLE_LINE_WORDS", "0"))),
            subtitle_max_lines=max(1, min(4,
                env_int("SUBTITLE_MAX_LINES", "2"))),
            subtitle_all_caps=env_bool("SUBTITLE_ALL_CAPS", "false"),
            subtitle_display=_one_of(env("SUBTITLE_DISPLAY", "sentence"),
                                     ("sentence", "karaoke"), "sentence"),
            karaoke_words_per_cue=max(1, min(5,
                env_int("KARAOKE_WORDS_PER_CUE", "3"))),
            karaoke_effect=_one_of(env("KARAOKE_EFFECT", "pop"),
                                   ("pop", "fade", "karaoke", "none"), "pop"),
            karaoke_highlight_color=env("KARAOKE_HIGHLIGHT_COLOR",
                                        "#FFD54A").strip() or "#FFD54A",
            karaoke_alignment=env_bool("KARAOKE_ALIGNMENT",
                                       _p["karaoke_alignment"]),
        )

    # --- Kiểm tra cấu hình -------------------------------------------------

    def require(self, *fields: str) -> None:
        """Ném ConfigError nếu một trong các mục được nêu còn trống."""
        missing = [f for f in fields if not getattr(self, f)]
        if missing:
            env_names = ", ".join(f.upper() for f in missing)
            raise ConfigError(
                f"Thiếu cấu hình bắt buộc: {env_names}. "
                f"Điền vào trang Cài đặt (hoặc tệp .env) rồi chạy lại."
            )

    # --- Phụ đề ------------------------------------------------------------

    def subtitle_style(self) -> dict:
        """Kiểu phụ đề truyền cho ffmpeg/libass.

        Đây là "đường ống" DUY NHẤT đưa lựa chọn phụ đề từ Cài đặt qua
        pipeline tới trình chỉnh sửa (render_opts.json).
        """
        return {
            "preset": self.subtitle_preset,
            "position": self.subtitle_position,
            "font": self.subtitle_font,
            "font_size": self.subtitle_font_size,
            "margin_v": self.subtitle_margin_v,
            "outline": self.subtitle_outline,
            "shadow": self.subtitle_shadow,
            "bold": self.subtitle_bold,
            "color": self.subtitle_color,
            "outline_color": self.subtitle_outline_color,
            "box": self.subtitle_box,
            "box_color": self.subtitle_box_color,
            "box_opacity": self.subtitle_box_opacity,
            "line_words": self.subtitle_line_words,
            "max_lines": self.subtitle_max_lines,
            "all_caps": self.subtitle_all_caps,
            "display": self.subtitle_display,
            "words_per_cue": self.karaoke_words_per_cue,
            "effect": self.karaoke_effect,
            "highlight_color": self.karaoke_highlight_color,
        }

    # --- Đường dẫn của các bộ chạy riêng ------------------------------------

    def asr_venv_python_path(self) -> str:
        """Trình thông dịch Python của venv dành riêng cho Paraformer."""
        if self.asr_venv_python:
            return self.asr_venv_python
        exe = "Scripts/python.exe" if os.name == "nt" else "bin/python"
        return os.path.join(app_root(), ".venv-asr", *exe.split("/"))

    def paraformer_model_dir_path(self) -> str:
        """Thư mục chứa model Paraformer + silero-VAD (+ chấm câu)."""
        if self.paraformer_model_dir:
            return self.paraformer_model_dir
        return os.path.join(app_root(), "models", "paraformer-zh")

    def paraformer_configured(self) -> bool:
        """venv ASR và dấu hiệu cài đặt xong đều có mặt hay chưa."""
        return (os.path.isfile(self.asr_venv_python_path())
                and os.path.isfile(os.path.join(self.paraformer_model_dir_path(),
                                                "installed_ok.json")))

    def whisper_venv_python_path(self) -> str:
        """Trình thông dịch Python của venv dành riêng cho Whisper."""
        if self.whisper_venv_python:
            return self.whisper_venv_python
        exe = "Scripts/python.exe" if os.name == "nt" else "bin/python"
        return os.path.join(app_root(), ".venv-whisper", *exe.split("/"))

    def whisper_model_dir_path(self) -> str:
        """Thư mục cache model Whisper (HuggingFace)."""
        if self.whisper_model_dir:
            return self.whisper_model_dir
        return os.path.join(app_root(), "models", "whisper")

    def whisper_venv_configured(self) -> bool:
        """venv Whisper đã cài và có marker hay chưa."""
        return (os.path.isfile(self.whisper_venv_python_path())
                and os.path.isfile(os.path.join(self.whisper_model_dir_path(),
                                                "installed_ok.json")))

    def ocr_venv_python_path(self) -> str:
        if self.ocr_venv_python:
            return self.ocr_venv_python
        exe = "Scripts/python.exe" if os.name == "nt" else "bin/python"
        return os.path.join(app_root(), ".venv-ocr", *exe.split("/"))

    def ocr_model_dir_path(self) -> str:
        if self.ocr_model_dir:
            return self.ocr_model_dir
        return os.path.join(app_root(), "models", "ocr")

    def ocr_configured(self) -> bool:
        return (self.ocr_enabled
                and os.path.isfile(self.ocr_venv_python_path())
                and os.path.isfile(os.path.join(self.ocr_model_dir_path(),
                                                "installed_ok.json")))

    def vieneu_venv_python_path(self) -> str:
        """Trình thông dịch Python của venv dành riêng cho VieNeu."""
        if self.vieneu_venv_python:
            return self.vieneu_venv_python
        exe = "Scripts/python.exe" if os.name == "nt" else "bin/python"
        return os.path.join(app_root(), ".venv-vieneu", *exe.split("/"))

    def vieneu_model_dir_path(self) -> str:
        """Thư mục chứa các tệp model VieNeu đã tải về."""
        if self.vieneu_model_dir:
            return self.vieneu_model_dir
        return os.path.join(app_root(), "models", "vieneu")

    def vieneu_custom_voices_path(self) -> str:
        """Tệp JSON chứa giọng người dùng tự thêm.

        Nằm trong models/vieneu cạnh ứng dụng (không nằm trong gói mã) nên
        cập nhật ứng dụng không làm mất giọng đã học.
        """
        return os.path.join(self.vieneu_model_dir_path(), "custom_voices.json")

    def vieneu_configured(self) -> bool:
        """venv VieNeu và dấu hiệu cài đặt xong đều có mặt hay chưa."""
        return (os.path.isfile(self.vieneu_venv_python_path())
                and os.path.isfile(os.path.join(self.vieneu_model_dir_path(),
                                                "installed_ok.json")))

    def vi_output_dir(self) -> str:
        """Thư mục kết quả: VIETNAMESE_OUTPUT_DIR hoặc OUTPUT_DIR/VN."""
        if self.vietnamese_output_dir:
            return self.vietnamese_output_dir
        return os.path.join(self.output_dir, "VN")

    def resolved_whisper_model(self, cuda_available: bool) -> str:
        """Tên model Whisper thật khi chọn "auto" (large-v3 GPU / medium CPU).

        large-v3 int8 cần khoảng 3 GB VRAM — vẫn vừa card 6 GB vì ASR chạy
        một mình trên card (Demucs xong, giọng đọc chạy CPU). Trên CPU thì
        large-v3 chậm gấp nhiều lần medium nên "auto" chỉ nâng khi có CUDA.
        """
        if self.whisper_model.strip().lower() != "auto":
            return self.whisper_model
        return "large-v3" if cuda_available else "medium"
