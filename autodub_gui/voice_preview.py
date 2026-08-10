"""Nghe thử giọng đọc, dùng chung cho Cài đặt, Tạo dự án và Trình chỉnh sửa.

Giọng lấy từ thư viện (voices/) đã có sẵn đoạn ghi âm gốc — bấm Nghe thử là
phát thẳng đoạn đó, vang lên NGAY không phải chờ tổng hợp.

Giọng không có tệp ghi âm (giọng gắn sẵn trong model, giọng tự học chỉ còn
vector) thì câu mẫu được tổng hợp MỘT lần rồi lưu thành .wav trong thư mục
đệm; từ đó về sau bấm Nghe thử cũng phát ngay.
"""
from __future__ import annotations

import os
import re
import threading

from PySide6.QtCore import QObject, QThread, QUrl, Signal

try:
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
    HAS_MEDIA = True
except ImportError:      # thiếu phần đa phương tiện thì ẩn nút, ứng dụng vẫn chạy
    HAS_MEDIA = False

# Câu mẫu ngắn để giọng nào cũng tạo xong trong vài giây.
PREVIEW_TEXT = "Xin chào, đây là giọng đọc bạn đang chọn cho video."

#: Nơi giữ các câu mẫu đã tổng hợp. Đổi PREVIEW_TEXT thì tăng số phiên bản
#: để mọi tệp cũ tự bị bỏ qua.
_CACHE_VERSION = 1


def _cache_dir() -> str:
    return os.path.join(os.path.expanduser("~"), ".voxdub_cache", "previews")


def _safe_name(voice: str) -> str:
    """Tên tệp an toàn cho một tên giọng có dấu và khoảng trắng."""
    return re.sub(r"[^0-9A-Za-z]+", "_", voice or "voice").strip("_") or "voice"


def cached_path(voice: str) -> str:
    """Đường dẫn tệp câu mẫu của một giọng trong thư mục đệm."""
    return os.path.join(_cache_dir(),
                        f"v{_CACHE_VERSION}_{_safe_name(voice)}.wav")


def _library_wav(voice: str) -> str:
    """Đoạn ghi âm gốc của một giọng thư viện, hoặc chuỗi rỗng nếu không có.

    Giọng trong ``voices/`` được học từ chính tệp .wav này, nên phát nó lên
    là nghe đúng chất giọng — không cần tổng hợp gì cả.
    """
    try:
        from autodub.speech.tts.voice_library import scan

        name = (voice or "").strip()
        return next((v.wav for v in scan() if v.name == name), "")
    except Exception:  # noqa: BLE001 — thư viện hỏng thì rơi về tổng hợp
        return ""


class _Synthesizer(QThread):
    """Tạo câu mẫu ở luồng nền để cửa sổ không bị đứng."""

    def __init__(self, parent, cache: dict, cache_lock, settings, voice: str,
                 out_path: str):
        super().__init__(parent)
        self._cache = cache
        self._cache_lock = cache_lock
        self._settings = settings
        self._voice = voice
        self._out = out_path
        self.error = ""

    def run(self) -> None:
        try:
            with self._cache_lock:
                synth = self._cache.get(self._voice)
            if synth is None:
                from autodub.languages import get_target
                from autodub.speech.tts import get_synthesizer

                # Nạp NGOÀI lock (mất vài giây) rồi mới ghi vào sổ — giữ lock
                # xuyên qua get_synthesizer sẽ chặn cả cleanup ở luồng GUI.
                synth = get_synthesizer(get_target("vi"), self._settings,
                                        voice=self._voice)
                with self._cache_lock:
                    self._cache[self._voice] = synth
            os.makedirs(os.path.dirname(self._out), exist_ok=True)
            synth.synthesize(PREVIEW_TEXT, self._out)
        except Exception as e:  # noqa: BLE001 — hiện nguyên nhân cho người dùng
            self.error = f"{type(e).__name__}: {e}"


class VoicePreview(QObject):
    """Phát câu mẫu của một giọng; tổng hợp lần đầu, các lần sau phát thẳng.

    Mỗi lúc chỉ chạy một lượt nghe thử, để hai lượt không tranh nhau CPU.
    """

    status_changed = Signal(str)     # dòng chữ mô tả việc đang làm
    finished = Signal(bool)          # đã tạo xong và bắt đầu phát hay chưa

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._synths: dict = {}
        # Luồng _Synthesizer ghi sổ này, luồng GUI lặp nó trong cleanup():
        # không có lock thì gặp "dictionary changed size during iteration".
        self._synths_lock = threading.Lock()
        self._thread: QThread | None = None
        self._player = None
        self._audio = None

    def is_busy(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def available(self) -> bool:
        """Máy có phát được âm thanh trong ứng dụng không."""
        return HAS_MEDIA

    def play(self, settings, voice: str) -> None:
        """Phát mẫu giọng: có tệp sẵn thì phát ngay, chưa có mới tổng hợp."""
        if self.is_busy():
            return
        problem = self._blocking_problem(settings, voice)
        if problem:
            self.status_changed.emit(problem)
            self.finished.emit(False)
            return

        # Giọng thư viện: phát thẳng đoạn ghi âm gốc — tức thì, không chờ.
        library = _library_wav(voice)
        if library:
            self.status_changed.emit("Đang phát…")
            self._play_file(library)
            self.finished.emit(True)
            return

        out_path = cached_path(voice)
        if os.path.isfile(out_path) and os.path.getsize(out_path) > 0:
            self.status_changed.emit("Đang phát…")
            self._play_file(out_path)
            self.finished.emit(True)
            return

        self.status_changed.emit(
            f"Đang tạo câu mẫu bằng giọng «{voice}»… Chỉ lần đầu phải chờ, "
            "các lần sau sẽ phát ngay.")
        worker = _Synthesizer(self, self._synths, self._synths_lock,
                              settings, voice, out_path)
        worker.finished.connect(lambda: self._on_ready(worker, out_path))
        self._thread = worker
        worker.start()

    @staticmethod
    def _blocking_problem(settings, voice: str) -> str:
        """Lý do không nghe thử được, hoặc chuỗi rỗng nếu mọi thứ sẵn sàng."""
        if not HAS_MEDIA:
            return "Máy này không phát được âm thanh trong ứng dụng."
        if not (voice or "").strip():
            return "Hãy chọn một giọng trước khi nghe thử."
        # Giọng CapCut đọc qua mạng nên nghe thử được ngay; chỉ giọng offline
        # mới cần model VieNeu trên máy.
        from autodub.speech.tts import voices as voice_catalog

        if voice_catalog.is_capcut_voice(voice):
            return ""
        if not settings.vieneu_configured():
            from autodub.speech.tts import NOT_INSTALLED_HINT
            return NOT_INSTALLED_HINT
        return ""

    def _on_ready(self, worker: _Synthesizer, path: str) -> None:
        self._thread = None
        if worker.error:
            # Tệp viết dở không được nằm lại trong thư mục đệm, không thì
            # lần nghe thử sau sẽ phát ra một đoạn hỏng.
            try:
                if os.path.isfile(path):
                    os.remove(path)
            except OSError:
                pass
            self.status_changed.emit(
                f"Không tạo được câu mẫu: {worker.error[:160]}")
            self.finished.emit(False)
            return
        self.status_changed.emit("Đang phát…")
        self._play_file(path)
        self.finished.emit(True)

    def _play_file(self, path: str) -> None:
        if not HAS_MEDIA:
            return
        if self._player is None:
            self._player = QMediaPlayer()
            self._audio = QAudioOutput()
            self._player.setAudioOutput(self._audio)
        player = self._player
        player.stop()
        player.setSource(QUrl())      # nhả khóa tệp cũ trước khi mở tệp mới
        player.setSource(QUrl.fromLocalFile(path))

        def _on_state(state) -> None:
            if state == QMediaPlayer.PlaybackState.StoppedState:
                self.status_changed.emit("")
                try:
                    player.playbackStateChanged.disconnect(_on_state)
                except RuntimeError:
                    pass

        player.playbackStateChanged.connect(_on_state)
        player.play()

    def cleanup(self) -> None:
        """Đóng các tiến trình giọng đọc, gọi khi ứng dụng thoát."""
        if self._player is not None:
            self._player.stop()
            self._player.setSource(QUrl())
        # Chụp ảnh trong lock, đóng ngoài lock: close() của VieNeu chờ tiến
        # trình con thoát, giữ lock suốt lúc đó sẽ treo luồng tổng hợp.
        with self._synths_lock:
            synths = list(self._synths.values())
            self._synths.clear()
        for synth in synths:
            close = getattr(synth, "close", None)
            if close is not None:
                try:
                    close()
                except Exception:  # noqa: BLE001 — đang thoát, bỏ qua lỗi dọn dẹp
                    pass
