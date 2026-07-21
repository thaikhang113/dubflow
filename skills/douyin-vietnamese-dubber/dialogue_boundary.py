"""Conservative, text-only dialogue boundary policy for TTS grouping.

The returned values are stable reason enums suitable for structured reports; the
caller must never include the source text in logs or reports merely to explain a
boundary.
"""
import re


TERMINAL_PUNCTUATION_RE = re.compile(r"(?:[。！？!?]|…|\.\.\.)$")
CHINESE_QUESTION_ENDING_RE = re.compile(
    r"(?:哪里|哪|谁|什么|怎么|为什么|吗|呢|几|多少|是否|有没有|可不可以)$"
)
VIETNAMESE_QUESTION_ENDING_RE = re.compile(
    r"(?:ở\s+đâu|là\s+ai|cái\s+gì|gì|tại\s+sao|vì\s+sao|"
    r"như\s+thế\s+nào|thế\s+nào|bao\s+nhiêu|khi\s+nào|"
    r"được\s+không|phải\s+không)$",
    re.IGNORECASE,
)
TRAILING_CLOSERS_RE = re.compile(r"[\"'”’»）)】\]〉》〕]+$")


def boundary_after(text):
    """Return a hard-boundary reason enum, or ``None`` for a continuation."""
    utterance = str(text or "").strip()
    if not utterance:
        return None
    utterance = TRAILING_CLOSERS_RE.sub("", utterance).rstrip()
    if TERMINAL_PUNCTUATION_RE.search(utterance):
        return "terminal_punctuation"
    if CHINESE_QUESTION_ENDING_RE.search(utterance):
        return "chinese_question_ending"
    if VIETNAMESE_QUESTION_ENDING_RE.search(utterance):
        return "vietnamese_question_ending"
    return None
