# Translation Memory For OpenClaw Vietnamese Dubbing

## Goal

OpenClaw and the dashboard are orchestration layers. The main translation model is still the 9Router LLM selected for the job, normally `ollama/minimax-m3:cloud`. Translation memory is a scoped prompt layer that teaches style, glossary, and character addressing for each video.

This is soft training, not fine-tuning. The model becomes more consistent because the pipeline injects the right notes before translation.

## Current MVP

Memory lives in:

```text
skills/douyin-vietnamese-dubber/translation_memory/
  global_style.md
  genres/
    tu_tien.md
    hoc_duong.md
    giang_ho.md
    hien_dai.md
    co_trang.md
  series/
    <series_id>/
      style.md
      glossary.json
      characters.json
```

When a job runs, the pipeline builds context from:

1. `global_style.md`
2. genre files named in `TRANSLATION_GENRE_TAGS`
3. the matching `series/<series_id>/` folder from `TRANSLATION_SERIES_ID`

It never loads every series into every video. If memory is missing or invalid, the pipeline warns and continues like before.

## How It Reaches The Model

`run.sh` calls `translation_memory_context.py` to create a short context file. `viet_dub_timing_optimizer.py` reads that file and adds a block named `BO NHO DICH AP DUNG CHO VIDEO NAY` to the translation prompt.

The memory may guide wording, tone, names, glossary, and xung ho. It must not override JSON format, timing rules, `subtitle_segments`, or `dub_text`.

## Series Tags

`series-tracker.py` stores `genre_tags` on a series. It also has lightweight inference for common keywords like `tu tien`, `hoc duong`, `giang ho`, `hien dai`, and `co trang`.

When a dashboard/series download queues a job with `series_id`, the request can pass:

```text
TRANSLATION_SERIES_ID=series-abc
TRANSLATION_GENRE_TAGS=tu_tien
```

The dashboard UI can be improved later, but the pipeline already supports the data path.

## Future Step 3: Learn From Approved SRT

Later, add a tool that compares:

```text
original.srt
vietnamese.srt
vietnamese.approved.srt
```

It should save selected corrections to `approved_pairs.jsonl`, for example:

```json
{"source_zh":"你干嘛呀","machine_vi":"Bạn đang làm gì vậy?","approved_vi":"Làm gì đó?","scope":"series","series_id":"series-abc","genre":"hien_dai","note":"Thoai doi thuong, can ngan cho dub"}
```

Future prompts should retrieve only a few relevant examples, not paste the entire history.

## Future Step 4: Dashboard Memory Manager

Add a dashboard tab for:

- series genre tags
- style guide
- glossary
- character xung ho
- approved examples
- mistakes to avoid

Default rule: write new lessons into series memory first. Promote to global only when the rule is safe for every film.
