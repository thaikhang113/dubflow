"""Language definitions: dubbing targets and source-language code maps."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TargetLang:
    """Static spec of a dubbing target language.

    Vietnamese is the only supported dub target.
    """
    key: str              # short key: "vi"
    code: str             # BCP-47 code: "vi-VN"
    iso639_2: str         # ISO 639-2 code used for MP4 subtitle track metadata
    name: str             # English name used in prompts/hints
    text_field: str       # translated-text field in transcript JSON
    transcript_name: str  # translated transcript filename
    srt_name: str         # translated SRT filename
    audio_name: str       # merged dub audio filename
    folder_suffix: str    # suffix for timestamped work dirs


TARGETS: dict[str, TargetLang] = {
    "vi": TargetLang(
        key="vi",
        code="vi-VN",
        iso639_2="vie",
        name="Vietnamese",
        text_field="text_vi",
        transcript_name="transcript_vi.json",
        srt_name="transcript_vi.srt",
        audio_name="audio_vi_full.wav",
        folder_suffix="_vi",
    ),
}


def get_target(key: str) -> TargetLang:
    """Resolve a target language from a short key or BCP-47 code."""
    k = key.strip().lower()
    if k in TARGETS:
        return TARGETS[k]
    for t in TARGETS.values():
        if t.code.lower() == k:
            return t
    raise ValueError(f"Unknown target language: {key!r} (supported: {', '.join(TARGETS)})")


# Source-language shorthand → BCP-47 locale (for ASR of the *original* video)
SOURCE_LANG_MAP = {
    "en": "en-US",
    "vi": "vi-VN",
    "zh": "zh-CN",
    "en-US": "en-US",
    "vi-VN": "vi-VN",
    "zh-CN": "zh-CN",
    "zh-HK": "zh-HK",
    "zh-TW": "zh-TW",
}

# BCP-47 locale → Whisper language code
WHISPER_LANG_MAP = {
    "en-US": "en",
    "zh-CN": "zh",
    "zh-HK": "zh",
    "zh-TW": "zh",
    "vi-VN": "vi",
}


def resolve_source_lang(lang: str) -> str:
    """Normalize a source-language shorthand to a BCP-47 locale."""
    return SOURCE_LANG_MAP.get(lang, lang)
