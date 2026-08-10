"""Bộ tạo giọng đọc tiếng Việt — hai engine: VieNeu (offline) và CapCut (API).

``get_synthesizer(target, settings, voice)`` trả về bộ tạo giọng cho MỘT tên
giọng cụ thể (xem :mod:`autodub.speech.tts.voices`). Người dùng không chọn
"engine" mà chọn thẳng TÊN giọng; tên thuộc bộ CapCut thì đi đường API, còn
lại chạy VieNeu trên máy. Hai engine độc lập — không engine nào dự phòng cho
engine kia.
"""
from __future__ import annotations

from autodub.config import ConfigError, Settings
from autodub.languages import TargetLang
from autodub.speech.tts import voices as voice_catalog
from autodub.speech.tts.base import Synthesizer, TTSResult
from autodub.utils import setup_logging

logger = setup_logging("autodub.tts")

__all__ = ["Synthesizer", "TTSResult", "get_synthesizer", "SynthCache",
           "NOT_INSTALLED_HINT"]

NOT_INSTALLED_HINT = (
    "Chưa cài bộ giọng VieNeu. Chạy một lần: py scripts/setup_vieneu.py"
)


class SynthCache:
    """Dùng lại một bộ tạo giọng cho mỗi TÊN GIỌNG xuyên suốt nhiều video.

    Chạy hàng loạt N video mà tạo mới mỗi lần thì phải nạp model N lần. Bộ nhớ
    đệm này phát lại đúng phiên bản đã khởi động sẵn cho cùng một giọng, và
    đóng tất cả ở một chỗ khi cả lô chạy xong.
    """

    def __init__(self):
        self._cache: dict[str, Synthesizer] = {}

    def get(self, target: TargetLang, settings: Settings,
            voice: str | None = None) -> Synthesizer:
        name = voice_catalog.resolve(settings, voice)
        synth = self._cache.get(name)
        if synth is None:
            synth = get_synthesizer(target, settings, name)
            self._cache[name] = synth
        return synth

    def close(self) -> None:
        # Đóng từng bộ một: một lỗi khi đóng không được làm rò rỉ các bộ khác.
        for synth in self._cache.values():
            close = getattr(synth, "close", None)
            if close is not None:
                try:
                    close()
                except Exception as e:
                    logger.warning(f"Lỗi khi đóng bộ tạo giọng ({e}) — bỏ qua")
        self._cache.clear()


def get_synthesizer(
    target: TargetLang,
    settings: Settings,
    voice: str | None = None,
    num_workers: int | None = None,
) -> Synthesizer:
    """Bộ tạo giọng ứng với tên giọng đang chọn.

    ``num_workers`` ghi đè số tiến trình con — dùng cho giọng phụ (một vài
    câu gán giọng riêng) để không nhân đôi RAM theo cả nhóm worker. Giọng
    CapCut bỏ qua tham số này (số luồng do ``recommended_threads`` quyết).
    """
    voice_name = voice_catalog.resolve(settings, voice)

    if voice_catalog.is_capcut_voice(voice_name):
        from autodub.speech.tts.capcut_vi import CapCutSynthesizer

        logger.info(f"Dùng giọng CapCut «{voice_name}» (qua mạng)")
        return CapCutSynthesizer(settings, voice_name=voice_name)

    # Chỉ nhánh offline mới cần VieNeu — kiểm tra ở đây chứ không phải đầu
    # hàm, nếu không máy chưa cài VieNeu sẽ bị chặn oan cả giọng CapCut.
    if not settings.vieneu_configured():
        raise ConfigError(NOT_INSTALLED_HINT)

    from autodub.speech.tts.vieneu_vi import VieNeuSynthesizer

    workers = num_workers or min(settings.parallel_workers,
                                 settings.vieneu_max_workers)
    logger.info(f"Dùng giọng VieNeu «{voice_name}» ({workers} luồng, CPU)")
    return VieNeuSynthesizer(settings, voice_name=voice_name,
                             num_workers=workers)
