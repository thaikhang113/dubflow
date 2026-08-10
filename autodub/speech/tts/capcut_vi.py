"""Bộ tổng hợp giọng CapCut — gọi API, không cần model trên máy.

Engine thứ hai bên cạnh VieNeu. Người dùng chọn giọng nào thì
:func:`autodub.speech.tts.get_synthesizer` tự định tuyến; hai engine độc
lập, không engine nào dự phòng cho engine kia.

Đây là engine ONLINE: mất mạng thì không đọc được. Đổi lại, máy chưa cài
VieNeu vẫn lồng tiếng được ngay.
"""
from __future__ import annotations

import os
import subprocess
import threading
import time

from autodub.speech.tts.base import TTSResult, write_silence
from autodub.utils import setup_logging

logger = setup_logging("autodub.tts.capcut")

#: Số câu đọc song song. Đây là I/O chờ mạng nên không tranh CPU với Demucs
#: hay Whisper, nhưng CapCut có bộ chống lạm dụng: bắn quá dày thì máy chủ
#: chặn thẳng định danh máy (``shark block``) chứ không chỉ từ chối một câu.
#: 3 luồng là mức đã chạy sạch qua nhiều lượt đo — đủ nhanh mà không liều.
RECOMMENDED_THREADS = 3

#: Khoảng cách tối thiểu giữa hai lần gửi, tính chung cho MỌI luồng. Van an
#: toàn cho lúc các câu ngắn trả về gần như tức thì và ba luồng dồn cục.
MIN_GAP_S = 0.8

#: Số lần thử lại một câu khi mạng chập chờn, và thời gian chờ giữa các lần.
RETRIES = 3
BACKOFF_S = (1.0, 2.0, 4.0)

#: Số lần đổi định danh liên tiếp mà vẫn bị chặn thì bỏ cuộc. Đổi được rồi
#: đọc trôi một câu là bộ đếm về 0 — video dài bị chặn vài lần vẫn chạy hết,
#: nhưng chặn liên hồi (vấn đề không nằm ở định danh) thì dừng sớm.
MAX_ROTATIONS = 2

#: Trần thời gian: chờ máy chủ tạo xong, tải file, và chạy ffmpeg cho MỘT câu.
TASK_TIMEOUT_S = 120.0
DOWNLOAD_TIMEOUT_S = 60
FFMPEG_TIMEOUT_S = 120

OFFLINE_HINT = ("Giọng CapCut cần kết nối mạng. Kiểm tra mạng rồi chạy lại, "
                "hoặc chọn một giọng offline (VieNeu) ở ô chọn giọng.")

BLOCKED_HINT = ("Máy chủ CapCut đang chặn máy này (shark block). Nghỉ khoảng "
                "15-30 phút rồi chạy lại, giảm số luồng giọng đọc trong Cài "
                "đặt, hoặc chọn một giọng offline (VieNeu) để lồng tiếng ngay.")

_THROTTLE_LOCK = threading.Lock()
_next_slot = 0.0

_DEVICE_LOCK = threading.Lock()
_rotations = 0
_profile: dict | None = None


def _current_profile() -> dict:
    """Hồ sơ thiết bị dùng chung cho mọi luồng trong phiên chạy này."""
    global _profile
    with _DEVICE_LOCK:
        if _profile is None:
            from autodub.speech.tts import capcut_catalog
            _profile = capcut_catalog.device_profile()
        return _profile


def _note_success() -> None:
    """Đọc trôi một câu nghĩa là định danh hiện tại lành — cho lại lượt đổi."""
    global _rotations
    if _rotations:
        with _DEVICE_LOCK:
            _rotations = 0


def _rotate_profile(seen: dict) -> dict | None:
    """Đổi định danh máy sau khi bị chặn. None nghĩa là hết lượt đổi.

    ``seen`` là hồ sơ luồng gọi đang cầm: nếu một luồng khác đã đổi trước rồi
    thì trả luôn hồ sơ mới, không đốt thêm một lượt đổi nữa.
    """
    global _profile, _rotations
    with _DEVICE_LOCK:
        if _profile is not None and _profile is not seen:
            return _profile
        if _rotations >= MAX_ROTATIONS:
            return None
        from autodub.speech.tts import capcut_catalog
        _rotations += 1
        _profile = capcut_catalog.rotate_device()
        logger.warning("CapCut chặn định danh máy — đã đổi sang định danh mới "
                       f"(lần {_rotations}/{MAX_ROTATIONS}).")
        return _profile


def _throttle() -> None:
    """Giữ nhịp gửi chung cho mọi luồng, không để ba luồng dồn vào một lúc."""
    global _next_slot
    with _THROTTLE_LOCK:
        now = time.monotonic()
        wait = _next_slot - now
        _next_slot = max(now, _next_slot) + MIN_GAP_S
    if wait > 0:
        time.sleep(wait)


def _is_shark_block(error: Exception) -> bool:
    """Máy chủ chặn định danh máy, khác hẳn lỗi mạng — thử lại là vô ích."""
    text = str(error).lower()
    return "shark block" in text or "'ret': '-6'" in text or '"ret": "-6"' in text


class CapCutSynthesizer:
    """Đọc từng câu bằng API CapCut rồi chuyển sang WAV cho pipeline."""

    recommended_threads = RECOMMENDED_THREADS

    def __init__(self, settings, voice_name: str):
        from autodub.speech.tts import capcut_catalog
        from autodub.speech.tts.capcut_api import CapCutClient

        entry = capcut_catalog.lookup(voice_name)
        if entry is None:
            raise ValueError(f"Không có giọng CapCut tên «{voice_name}»")
        self.settings = settings
        self.voice_name = voice_name
        self._voice_type = entry["voice_type"]
        self._resource_id = entry["resource_id"]
        self._device = _current_profile()
        self._client = CapCutClient(device=self._device)

    # -- gọi máy chủ ------------------------------------------------------

    def _reload_device(self, used: dict) -> bool:
        """Nhận định danh mới sau khi ``used`` bị chặn. False là hết đường."""
        from autodub.speech.tts.capcut_api import CapCutClient

        profile = _rotate_profile(used)
        if profile is None:
            return False
        self.close()
        self._device = profile
        self._client = CapCutClient(device=profile)
        return True

    def _fetch_mp3(self, text: str) -> bytes:
        """MP3 do máy chủ đọc ra. Thử lại khi mạng lỗi; hết lượt thì ném."""
        last_error: Exception | None = None
        for attempt in range(RETRIES):
            used = self._device
            try:
                _throttle()
                task = self._client.generate_speech(
                    texts=text, voice=self._voice_type,
                    resource_id=self._resource_id, wait=True,
                    timeout=TASK_TIMEOUT_S)
                url = task.get("speech_url")
                if not url:
                    raise RuntimeError(f"Máy chủ không trả link audio: {task}")
                resp = self._client.session.get(url,
                                                timeout=DOWNLOAD_TIMEOUT_S)
                resp.raise_for_status()
                if not resp.content:
                    raise RuntimeError("Máy chủ trả file audio rỗng")
                _note_success()
                return resp.content
            except Exception as e:  # noqa: BLE001 — lỗi nào cũng đáng thử lại
                last_error = e
                if _is_shark_block(e):
                    # Bị chặn thì gửi lại y hệt chỉ tổ đào sâu thêm: phải đổi
                    # định danh máy rồi mới thử tiếp, hết lượt đổi thì dừng.
                    if not self._reload_device(used):
                        raise RuntimeError(BLOCKED_HINT) from e
                    continue
                if attempt < RETRIES - 1:
                    logger.warning(
                        f"CapCut lỗi (lần {attempt + 1}/{RETRIES}): {e}")
                    time.sleep(BACKOFF_S[attempt])
        if last_error is not None and _is_shark_block(last_error):
            raise RuntimeError(BLOCKED_HINT) from last_error
        raise RuntimeError(f"Không đọc được câu bằng giọng CapCut sau "
                           f"{RETRIES} lần thử: {last_error}. {OFFLINE_HINT}")

    # -- chuyển định dạng -------------------------------------------------

    @staticmethod
    def _to_wav(mp3_bytes: bytes, output_path: str) -> None:
        """MP3 → WAV mono 44.1 kHz — cả pipeline chỉ làm việc với WAV."""
        from autodub.resources import FFMPEG_SLOTS

        tmp_mp3 = output_path + ".capcut.tmp.mp3"
        with open(tmp_mp3, "wb") as f:
            f.write(mp3_bytes)
        try:
            with FFMPEG_SLOTS:
                result = subprocess.run(
                    ["ffmpeg", "-y", "-i", tmp_mp3, "-ac", "1", "-ar", "44100",
                     output_path],
                    capture_output=True, encoding="utf-8", errors="replace",
                    timeout=FFMPEG_TIMEOUT_S,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if result.returncode != 0 or not os.path.isfile(output_path):
                raise RuntimeError("ffmpeg không chuyển được audio CapCut "
                                   f"sang WAV: {(result.stderr or '')[-300:]}")
        finally:
            if os.path.exists(tmp_mp3):
                os.remove(tmp_mp3)

    # -- giao diện Synthesizer -------------------------------------------

    def synthesize(
        self,
        text: str,
        output_path: str,
        target_duration: float | None = None,
    ) -> TTSResult:
        """Đọc một câu ở tốc độ tự nhiên.

        ``target_duration`` nhận vào cho khớp giao diện engine rồi bỏ qua —
        giống VieNeu, việc co giãn thời lượng do VIDEO_SPEED/VOICE_SPEED lo
        đồng loạt sau bước TTS.
        """
        from autodub.media.audio import wav_duration_s
        from autodub.text.vi_numbers import normalize_vi_text

        output_path = os.path.abspath(output_path)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        text = normalize_vi_text(text.strip())
        if not text.strip(".,!?;: "):
            # Dòng trống (transcript sửa tay) — clip im lặng, cùng lý do như
            # VieNeu: một dòng rỗng không được làm đổ cả video.
            return write_silence(output_path)

        self._to_wav(self._fetch_mp3(text), output_path)
        duration = wav_duration_s(output_path) or 0.0
        return TTSResult(
            path=output_path,
            actual_duration=round(duration, 3),
            speed_adjusted=False,
            rate_applied="1.0x",
        )

    def close(self) -> None:
        """Đóng session HTTP khi pipeline chạy xong."""
        session = getattr(self._client, "session", None)
        if session is not None:
            session.close()
