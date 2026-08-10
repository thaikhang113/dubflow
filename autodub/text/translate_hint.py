"""Write TRANSLATE_PENDING.txt with instructions for both Claude Code users
and casual users (no API key, no CLI tools — use ChatGPT / Gemini web UI).

The pipeline writes this file when the translation step is reached and the
expected translated transcript JSON does not yet exist on disk. The file is
a self-contained set of instructions: the user picks Path A (Claude Code) or
Path B (web AI), produces the translated JSON, and runs ``--resume`` to
continue.
"""
import os

from autodub.languages import TargetLang
from autodub.utils import setup_logging

logger = setup_logging("autodub.translate_hint")

# Spoken Vietnamese pace used to compute per-segment character budgets.
# Default when no Settings value is supplied — overridable per run via
# TRANSLATE_CPS_BUDGET (settings.translate_cps_budget). ~12.5 chars/sec
# forces concise translations; comfortable pace is 12, the 1.3x ceiling 15.
CHARS_PER_SECOND_BUDGET = 12.5

# Terminal marks a spoken sentence may end with; anything else gets a period.
_TERMINAL = (".", "!", "?", "…", ":")


def effective_cps(settings, video_slowdown_pending: bool = True) -> float:
    """Ngân sách ký tự/giây THẬT sau hai nút vặn tốc độ.

    Dịch và review chạy TRÊN TIMELINE GỐC, nhưng video sẽ được làm chậm còn
    ``video_speed`` (mỗi khe dài thêm 1/video_speed) và giọng đọc chạy ở
    ``voice_speed`` (đọc được nhiều chữ hơn mỗi giây). Không nhân sẵn hai
    hệ số này vào budget thì review cờ oan hàng loạt câu "quá dài" dù sau
    khi chậm video chúng vừa khít (vd VIDEO_SPEED=0.82 → budget thật
    12.5/0.82 ≈ 15.2 ký tự/giây).

    ``video_slowdown_pending=False`` dành cho các bước chạy SAU khi video
    đã làm chậm (quality report): timestamps lúc đó đã nằm trên timeline
    kéo dài, nhân thêm 1/video_speed nữa là đếm trùng.
    """
    if settings is None:
        return CHARS_PER_SECOND_BUDGET
    cps = float(getattr(settings, "translate_cps_budget", 0)
                or CHARS_PER_SECOND_BUDGET)
    cps *= float(getattr(settings, "voice_speed", 1.0) or 1.0)
    if video_slowdown_pending:
        video = float(getattr(settings, "video_speed", 1.0) or 1.0)
        cps /= max(0.5, min(1.0, video))
    return cps


def annotate_slots(segments: list[dict], tail_slack: float = 2.0) -> list[dict]:
    """Attach ``seg["slot"]`` — the REAL time available for the spoken clip.

    The dub places each clip at its original ``start``, so the true budget is
    the time until the NEXT clip starts (own duration plus any trailing
    silence), not the segment's own duration. The last segment has no
    successor; give it its duration plus ``tail_slack``. A floor of 0.3 s
    guards against out-of-order or broken timestamps producing zero/negative
    slots (which would starve the translation of any character budget).

    Mutates the segments in place and returns the same list.
    """
    for i, seg in enumerate(segments):
        if i + 1 < len(segments):
            slot = float(segments[i + 1]["start"]) - float(seg["start"])
        else:
            slot = float(seg.get("duration", 0) or 0) + tail_slack
        seg["slot"] = round(max(0.3, slot), 3)
    return segments


def ensure_terminal_punct(text: str) -> str:
    """Normalise a translated line for TTS: single spaces + terminal punctuation.

    Every spoken sentence must end on a full stop-class mark so the voice
    drops its pitch and pauses naturally instead of running into the next
    clip. Trailing commas/dashes (mid-sentence intonation) are replaced.
    """
    text = " ".join(text.split())
    text = text.rstrip(",;-–— ")
    if text and not text.endswith(_TERMINAL):
        text += "."
    return text


def payload_segment(seg: dict, cps_budget: float = CHARS_PER_SECOND_BUDGET) -> dict:
    """Fields sent to the translator for one segment, plus its character budget.

    ``max_chars`` gives the model a concrete number instead of only prose
    pacing rules — translations that fit need no atempo compression later.
    The budget follows the segment's ``slot`` (real time until the next clip
    starts, see :func:`annotate_slots`); ``duration`` is the fallback for
    transcripts produced before slots existed. ``cps_budget`` comes from
    ``settings.translate_cps_budget`` in the pipeline paths.

    Chỉ gửi ``id``/``text``/``duration``: ``start``/``end`` không giúp gì cho
    việc dịch (model chỉ cần biết câu dài bao nhiêu giây) mà nhân với hàng
    nghìn câu là hàng chục nghìn token vô ích mỗi video.
    """
    out = {k: seg[k] for k in ("id", "text", "duration") if k in seg}
    window = float(seg.get("slot") or seg.get("duration", 0) or 0)
    if window > 0:
        # Floor of 12 keeps ultra-short segments translatable at all.
        out["max_chars"] = max(12, int(window * cps_budget))
    return out


def context_payload(all_segments: list[dict], batch_start_index: int,
                    target: TargetLang | None = None, n: int = 3) -> list[dict]:
    """The ``n`` segments right before a batch, as read-only context.

    Batches are translated independently, so without this the model loses the
    conversational thread at every batch boundary (pronouns and terminology
    drift). Each entry carries the source ``text``; if a translation already
    exists on the segment, it is included so
    the model can also match the established wording.
    """
    ctx: list[dict] = []
    for seg in all_segments[max(0, batch_start_index - n):batch_start_index]:
        item = {"id": seg.get("id"), "text": seg.get("text", "")}
        if target is not None and seg.get(target.text_field):
            item[target.text_field] = seg[target.text_field]
        ctx.append(item)
    return ctx


def context_note(target: TargetLang) -> str:
    """User-prompt sentence explaining the read-only context block."""
    return ('The "context" array holds the lines IMMEDIATELY BEFORE this '
            'batch — use them ONLY to understand the flow and keep '
            f'pronouns/terminology consistent (a "{target.text_field}" field '
            'there shows wording already used). Do NOT translate them and do '
            'NOT include them in the output.\n\n')


def build_style_rules(target: TargetLang, domain: str = "general") -> str:
    """Universal Vietnamese Spoken-Style Translation Rules (Single Source of Truth).
    Optimized for LLM execution and Text-to-Speech (TTS) readiness.
    """
    return f"""### ROLE & TONE
- **Target Audience & Tone**: Casual, direct, engaging YouTube/TikTok creator style. Clear and concise, skip unnecessary filler.
- **Pronouns**: Use friendly, natural Vietnamese pronouns (Bạn / mình / các bạn). Avoid over-formal or excessively vulgar/slangy pronouns (never mày/tao, never ông/bà unless explicitly instructed).
- **Domain Context**: {domain} — adapt wording, jargon and idioms to what THIS video is actually about (phim ngắn, vlog, nấu ăn, game, công nghệ, làm đẹp...). NEVER import terminology or examples from an unrelated domain.

### PURE NATURAL VIETNAMESE (CRITICAL RULE)
- **Native Phrasing**: "{target.text_field}" MUST sound like a native Vietnamese speaker talking naturally — 100% Vietnamese words combined with standard Latin brand names. NEVER leave Chinese characters or raw foreign text.
- **Translate Meaning, NOT Words**: ALWAYS translate the underlying intent/meaning. Avoid literal word-for-word translation. A literal rendering that sounds awkward or foreign ("dịch thô / Hán Việt gượng ép") is strictly WRONG:
  * Slang/Internet Idioms: Express the actual concept in the everyday Vietnamese of the video's own domain.
  * NEVER produce half-translated mixes (half Sino-Vietnamese/Vietnamese, half foreign). Translate what the term MEANS in natural Vietnamese.

### NAMES & BRAND NAMES
- **Brands / Products**: Retain the standard LATIN names the Vietnamese community already uses (e.g., Samsung, iPhone, Nike).
- **Chinese Person Names (Dramas/Vlogs)**: Convert to Pinyin (e.g., 王伟 → Wang Wei) unless it's a historical/wuxia context where Sino-Vietnamese (Hán Việt) is standard. Nicknames (e.g., 小白, 老张) are rendered by MEANING as a natural Vietnamese nickname, never half-transliterated.
- **Korean Person Names**: Convert to standard Revised Romanization.
- **Model/Version Codes**: Keep Latin letters and digits intact in the text.

### NUMBERS & UNITS (TEXT-TO-SPEECH OPTIMIZED)
Since this text will be read aloud by a TTS voice, format all numbers as SPOKEN VIETNAMESE WORDS:
- **Quantities & Currency**: 90% → "chín mươi phần trăm", 25元 → "hai mươi lăm tệ", 50ml → "năm mươi mililit".
- **Codes read digit-by-digit**: where a Vietnamese speaker would read digits individually (phone numbers, room numbers, product codes), spell them digit by digit.

### MISCELLANEOUS & FORMATTING
- **Sino-Vietnamese Words**: Use only extremely common everyday Sino-Vietnamese words (e.g., "kiểm sát viên" is fine, but prefer natural spoken terms over archaic ones).
- **Chinese Particles**: Completely remove Chinese discourse/modal particles (啊, 呢, 嘛, 吧).
- **Bleeped/Censored Segments**: If the text contains ONLY punctuation, symbols, or bleeps (e.g., "**", "..."): Translate it into a short Vietnamese spoken exclamation like "Hả.", "Ôi.", or "Chờ chút." 
  * CRITICAL: NEVER output an empty string, pure punctuation, or "..." (TTS engines will crash or reject pure punctuation)."""

def _pace(target: TargetLang, cps_budget: float = CHARS_PER_SECOND_BUDGET) -> str:
    return f"Vietnamese: ~{cps_budget:g} chars/sec natural spoken pace"


def build_user_context_block(settings) -> str:
    """User-supplied context from the Settings tab ("Ngữ cảnh video").

    Returns "" when nothing is filled in — the prompt stays generic. Accepts
    any object with the translate_* attributes (duck-typed so manual paths
    without a Settings instance can pass None).
    """
    if settings is None:
        return ""
    lines: list[str] = []
    title = getattr(settings, "translate_video_title", "").strip()
    domain = getattr(settings, "translate_domain", "").strip()
    context = getattr(settings, "translate_context", "").strip()
    pronouns = getattr(settings, "translate_pronouns", "").strip()
    glossary = getattr(settings, "translate_glossary", "").strip()
    style = getattr(settings, "translate_style_notes", "").strip()
    if title:
        lines.append(f"- **Original video title**: {title}")
    if domain:
        lines.append(f"- **Video topic/domain**: {domain}")
    if context:
        lines.append("- **Background provided by the channel owner** "
                     "(use it to resolve ambiguous phrases, jargon and "
                     "references):\n  " + context.replace("\n", "\n  "))
    if pronouns:
        lines.append(
            f"- **Pronoun convention (MANDATORY)**: {pronouns} — use EXACTLY "
            "this addressing style for speaker/audience in EVERY segment, "
            "consistently across the whole video. This OVERRIDES the default "
            "pronoun rule below.")
    if glossary:
        lines.append(
            "- **Fixed terminology (MANDATORY)** — whenever the source term "
            "appears, use exactly the given translation:\n  "
            + glossary.replace("\n", "\n  "))
    if style:
        lines.append(f"- **Extra style requirements**: {style}")
    if not lines:
        return ""
    return ("### USER-PROVIDED VIDEO CONTEXT (HIGHEST PRIORITY)\n"
            "The channel owner supplied this context about the video. It "
            "overrides any conflicting generic rule below.\n"
            + "\n".join(lines) + "\n\n")


def _output_format_block(target: TargetLang, compact: bool) -> str:
    """Đoạn OUTPUT FORMAT — phải KHỚP với định dạng nơi gọi thật sự nhận.

    ``compact=True``: đường API (schema ép ``{"segments": [{id, text_vi}]}``)
    — mô tả đúng format đó; bảo model "giữ nguyên mọi trường gốc" trong khi
    schema cấm là tự mâu thuẫn, model yếu sẽ loạn.
    ``compact=False``: đường dịch tay (file dán từ web AI) — người dùng lưu
    nguyên mảng làm transcript nên PHẢI giữ đủ start/end/duration.
    """
    out_field = target.text_field
    if compact:
        return f"""### OUTPUT FORMAT (STRICT)
- Return EXACTLY ONE valid JSON object: {{"segments": [...]}} — same length, order and `id`s as the input.
- Each output segment has EXACTLY two fields: `id` (copied from input) and `"{out_field}"` (the final {target.name} translation of that segment's `text`). Do NOT repeat `text`, `duration` or any other input field.
- Every `"{out_field}"` value MUST end with terminal punctuation: `.`, `!`, `?` or `…`. If the sentence has no natural ending mark, append a period. NEVER end on a comma, a dash, or nothing.
- Output strictly valid JSON ONLY — DO NOT use markdown code blocks, fences, or introductory/ending commentary."""
    return f"""### OUTPUT FORMAT (STRICT)
- Return EXACTLY ONE valid JSON array with the exact same length, order, and `id`s as the input.
- Preserve every original field (`id`, `text`, `start`, `end`, `duration`).
- ADD one new string field per segment: `"{out_field}"`.
- `"{out_field}"` must contain the final {target.name} translation of the `text` field.
- Every `"{out_field}"` value MUST end with terminal punctuation: `.`, `!`, `?` or `…`. If the sentence has no natural ending mark, append a period. NEVER end on a comma, a dash, or nothing.
- Output strictly valid JSON ONLY — DO NOT use markdown code blocks, fences, or introductory/ending commentary."""


def build_translation_prompt(target: TargetLang, source_lang: str,
                             domain: str = "general",
                             cps_budget: float = CHARS_PER_SECOND_BUDGET,
                             settings=None,
                             compact_output: bool = True) -> str:
    """The full translation instruction block (STRICT format + style + pacing + consistency).
    Shared across manual and automatic pipelines to ensure identical translation output quality.

    ``compact_output``: True cho đường API (đầu ra ``{"segments": [{id,
    text_vi}]}`` theo schema), False cho đường dịch tay (mảng đầy đủ giữ
    nguyên timing để lưu thẳng làm transcript).
    """
    out_field = target.text_field
    user_domain = getattr(settings, "translate_domain", "").strip() if settings else ""
    if user_domain:
        domain = user_domain
    input_fields = ("`id`, `text`, `duration` (seconds) and usually `max_chars`"
                    if compact_output else
                    "`id`, `text`, `start`, `end`, and `duration` (in seconds)")
    return f"""You are an expert translator specializing in ASR (Automatic Speech Recognition) transcripts for video dubbing.
Your task is to translate an ASR transcript from {source_lang} to {target.name}.

You will receive a JSON array of segments. Each segment contains: {input_fields}.

{build_user_context_block(settings)}{_output_format_block(target, compact_output)}

### STYLE & TRANSLATION RULES
{build_style_rules(target, domain=domain)}

### FIDELITY TO THE ORIGINAL (CRITICAL)
- **Faithful, not free**: translate the FULL meaning of every segment — do NOT add ideas, do NOT drop ideas, do NOT invent content that is not in the source. Conciseness comes from tighter phrasing, never from cutting meaning.
- **Reading comprehension first**: before translating a segment, read the surrounding segments (and the `context` block if present) to understand what is actually being said. When the source line is ambiguous, pick the reading that fits the flow of the neighbouring lines — never translate a line in isolation against its context.
- **Register**: keep the original's register — a joke stays a joke, a technical explanation stays precise, an insult keeps its bite (within the pronoun rules).

### PROSODY & EMPHASIS (MATCH THE ORIGINAL DELIVERY)
Each segment is ONE spoken utterance, dubbed as its own audio clip at its own timestamp. The voice actor can only reproduce the original delivery if your text carries it:
- **Sentence type**: keep the original's intent — a question stays a question (`?`), an exclamation/shout stays one (`!`), a trailing/unfinished thought uses `…`.
- **Emphasis**: if the original stresses a word or idea, carry that stress with natural Vietnamese emphasis words (e.g. "chính", "đúng là", "cực kỳ", "thật sự") — never with CAPS or symbols.
- **Pauses**: place commas exactly where the speaker would take a breath or pause for effect. The TTS voice pauses at commas — a missing comma flattens the delivery, a wrong one breaks the flow.
- **One segment = one utterance**: NEVER merge content across segments and NEVER split one segment into multiple sentences unless the original clearly contains multiple sentences. Each translation must stand alone when read out loud, exactly like the original line does.

### DURATION-AWARE LENGTH & PACING (CRITICAL FOR TTS)
- Each segment includes a `duration` (in seconds) and usually a `max_chars` character budget. `max_chars` is computed from the REAL time window this clip has before the next line starts — the generated translation is read aloud by a Text-to-Speech engine inside exactly that window.
- **HARD LIMIT**: when a segment provides `max_chars`, `"{out_field}"` MUST NOT exceed that many characters (spaces included). Exceeding the budget forces the voice to be sped up or CUT OFF mid-sentence in the final video — rephrase more concisely until it fits: cut filler words first, then use shorter synonyms.
- Spoken pace guideline for {target.name}: {_pace(target, cps_budget)}.
- **Short segments (< 4s)**: Use the shortest possible natural phrasing. Omit unnecessary words or filler.
- **Medium segments (4-8s)**: Use natural casual speech, favoring concise synonyms.
- **Long segments (> 8s)**: Express ideas clearly without artificial bloating. Keep it tight.
- *Rule of thumb*: When choosing between two valid translations, ALWAYS pick the SHORTER one.

### CONSISTENCY
- Maintain consistent translations for recurring character names, terminology, jargon, and pronoun registers throughout the entire transcript.

### FINAL QUALITY CHECK (PER SEGMENT)
Before outputting, verify every single segment against these four rules:
1. Does this sound like how a native Vietnamese content creator would ACTUALLY say it out loud in spoken speech?
2. Are all numbers/units converted into spoken Vietnamese text, with ZERO raw foreign characters or literal word-for-word transliterations?
3. Does it end with `.`, `!`, `?` or `…`, fit within `max_chars`, and carry the same emphasis and pauses as the original line?
4. Is it FAITHFUL to the original meaning — nothing added, nothing dropped, ambiguities resolved by context — and does it follow the user-provided pronouns/terminology if any were given?

If a segment fails any check, rewrite it into natural spoken Vietnamese before returning the final JSON.
"""


def write_hint(work_dir: str, target: TargetLang, source_lang: str,
               settings=None, refund_note: str = "") -> str:
    """Create ``<work_dir>/TRANSLATE_PENDING.txt`` and return its path.

    Viết cho NGƯỜI DÙNG PHỔ THÔNG: tiếng Việt, 3 bước, không thuật ngữ dev.
    Prompt gửi cho AI vẫn là tiếng Anh (chất lượng dịch tốt hơn) nhưng người
    dùng chỉ cần copy-paste nguyên khối, không cần hiểu.

    ``settings`` (nếu có) đưa ngữ cảnh video vào prompt — kể cả ngữ cảnh do
    lượt phân tích tự động đã lưu ở ``data/video_context.json``: dịch tay
    phải nhận được ĐÚNG prompt như dịch tự động, không phải bản chay.

    ``refund_note`` là dòng trấn an về tiền: giá của video đã chốt từ đầu nên
    phần dịch tay không phát sinh thêm Vox. Thấy pipeline dừng giữa đường mà
    không ai nói gì về Vox thì người dùng mặc định là mình vừa mất tiền.
    """
    from autodub.workdir import data_dir

    out_file = target.transcript_name
    # Bố cục mới: transcript nằm trong data/ — hướng dẫn phải trỏ đúng chỗ.
    d_dir = data_dir(work_dir)

    # Bơm ngữ cảnh phân tích (nếu lượt 0 đã chạy và lưu cache) vào settings,
    # y hệt đường dịch tự động — ô nào người dùng điền tay vẫn thắng.
    # File này có thể đang mã hóa (lượt chạy có hold): đọc bằng read_json_secure
    # với khóa của hold, nếu không thì ngữ cảnh người dùng ĐÃ TRẢ Vox để có bị
    # âm thầm bỏ qua và prompt dịch tay thành bản chay.
    ctx_cache = os.path.join(d_dir, "video_context.json")
    if settings is not None and os.path.exists(ctx_cache):
        try:
            from autodub import securestore
            from autodub.text.translate_common import HOLD

            analysis = securestore.read_json_secure(ctx_cache, HOLD.key or None)
            from autodub.text.translate_saas import apply_analysis
            settings = apply_analysis(settings, analysis)
        except Exception as e:  # noqa: BLE001 — thiếu ngữ cảnh không được chặn hướng dẫn
            logger.warning(f"Không đọc được ngữ cảnh video cho dịch tay: {e}")

    # Tiêu đề video gốc (downloader lưu) — dịch tay nhận đúng ngữ cảnh như
    # dịch tự động.
    if settings is not None and not getattr(settings,
                                            "translate_video_title", ""):
        from autodub.workdir import load_video_meta
        title = str(load_video_meta(work_dir).get("title", "")).strip()
        if title:
            import dataclasses
            settings = dataclasses.replace(settings,
                                           translate_video_title=title)

    # Dịch tự động đang TẮT là lựa chọn của người dùng, không phải sự cố —
    # gộp hai chuyện vào một câu khiến người tắt tưởng app hỏng, còn người
    # gặp sự cố thì đi tìm cái công tắc họ chưa từng bật.
    manual_by_choice = (settings is not None
                        and not getattr(settings, "translate_enabled", True))
    if manual_by_choice:
        why = """Bạn đang để "Dịch tự động" TẮT trong Cài đặt, nên app nghe xong
lời thoại rồi dừng lại chờ bản dịch của bạn. Cách làm ở dưới, khoảng 2-3 phút.

MUỐN APP TỰ DỊCH: mở Cài đặt, bật "Dịch tự động" — app dịch giúp bạn toàn bộ
lời thoại, tính thêm 2 Vox mỗi câu."""
    else:
        why = """App đã nghe xong lời thoại nhưng máy chủ dịch đang gặp sự cố.
Không sao — bạn nhờ một AI miễn phí (ChatGPT, Gemini...) dịch giúp theo 3
bước dưới đây, mất khoảng 2-3 phút.

HOẶC: đợi một lúc rồi chạy lại video này. Phần đã nghe-chép được dùng lại
nên không mất công, và phần nào đã dịch rồi cũng không bị tính Vox lần hai."""

    money = f"\n{refund_note}\n" if refund_note else ""

    hint_path = os.path.join(work_dir, "TRANSLATE_PENDING.txt")
    with open(hint_path, "w", encoding="utf-8") as f:
        f.write(
            f"""VIDEO ĐANG CHỜ BẢN DỊCH
=======================

{why}
{money}

BƯỚC 1 — COPY NỘI DUNG CẦN DỊCH
--------------------------------
Mở file này bằng Notepad rồi copy TOÀN BỘ nội dung:

    {os.path.join(d_dir, 'transcript_original.json')}

(File nằm trong thư mục "data" cạnh file hướng dẫn này.)


BƯỚC 2 — NHỜ AI DỊCH
---------------------
1. Mở chatgpt.com hoặc gemini.google.com (đăng nhập miễn phí).
2. Copy nguyên khối "LỜI NHẮN GỬI AI" ở cuối file này, dán vào ô chat.
3. Dán tiếp nội dung đã copy ở Bước 1 vào ngay phía sau, rồi gửi.
4. AI sẽ trả về một đoạn văn bản dài bắt đầu bằng dấu [ — copy toàn bộ
   đoạn đó. (Nếu đầu/cuối có dòng ```json hoặc ``` thì bỏ mấy dòng đó đi,
   chỉ lấy phần từ dấu [ đến dấu ] cuối cùng.)


BƯỚC 3 — LƯU BẢN DỊCH VÀ CHẠY TIẾP
-----------------------------------
1. Mở Notepad, dán bản dịch vừa copy.
2. Bấm "Save as" (Lưu thành), lưu với ĐÚNG tên file:

       {out_file}

   vào ĐÚNG thư mục này (cùng chỗ với file ở Bước 1):

       {d_dir}

   Mục "Encoding" chọn UTF-8 (Notepad thường để sẵn).
3. Quay lại app, bấm nút "Đã dịch xong, tiếp tục". App sẽ tự làm nốt
   phần còn lại (đọc giọng, ghép video).

Nếu app báo lỗi sau khi bấm tiếp tục: thường do file lưu sai tên, sai thư
mục, hoặc còn sót dòng ```json — kiểm tra lại 3 điểm đó rồi bấm lại.


==================================================================
LỜI NHẮN GỬI AI (copy nguyên khối bên dưới, không cần đọc hiểu)
==================================================================
{build_translation_prompt(target, source_lang, settings=settings, compact_output=False)}

Now translate this JSON, return only the translated JSON array:

(dán nội dung transcript_original.json vào đây)
==================================================================
"""
        )
    return hint_path
