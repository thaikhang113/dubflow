#!/usr/bin/env python3
"""Focused tests for translation memory scoping and prompt injection."""
import importlib.util
import json
import tempfile
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parent


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_collect_memory_scoped():
    mod = load_module("translation_memory_context_test", SKILL_DIR / "translation_memory_context.py")
    with tempfile.TemporaryDirectory(prefix="tmemory_") as td:
        root = Path(td)
        (root / "genres").mkdir()
        (root / "series" / "series-a").mkdir(parents=True)
        (root / "series" / "series-b").mkdir(parents=True)
        (root / "global_style.md").write_text("- global rule\n", encoding="utf-8")
        (root / "genres" / "tu_tien.md").write_text("- dao huu\n", encoding="utf-8")
        (root / "genres" / "hoc_duong.md").write_text("- school style\n", encoding="utf-8")
        (root / "series" / "series-a" / "style.md").write_text("- A goi B la nang\n", encoding="utf-8")
        (root / "series" / "series-a" / "glossary.json").write_text(json.dumps({"灵力": "linh lực"}, ensure_ascii=False), encoding="utf-8")
        (root / "series" / "series-b" / "style.md").write_text("- must not load\n", encoding="utf-8")

        context, warnings = mod.collect_memory(root, genre_tags="tu_tien", series_id="series-a", max_chars=10000)

    assert not warnings
    assert "[Global]" in context
    assert "[Genre: tu_tien]" in context
    assert "[Series: series-a]" in context
    assert "linh lực" in context
    assert "school style" not in context
    assert "must not load" not in context


def test_optimizer_prompt_includes_memory():
    opt = load_module("viet_dub_timing_optimizer_test", SKILL_DIR / "viet_dub_timing_optimizer.py")
    captured = {}

    def fake_chat(api_base, api_key, model, messages, temperature=0.2, timeout=None, api_provider="ninerouter"):
        captured["prompt"] = messages[-1]["content"]
        return json.dumps({"subtitle_segments": [{"id": 1, "text": "Sư phụ tới rồi"}], "dub_text": "Sư phụ tới rồi"}, ensure_ascii=False)

    opt.chat = fake_chat
    group = [{"id": 1, "start_ms": 0, "end_ms": 1000, "source_text": "师父来了"}]
    subtitle, dub_text = opt.translate_group(
        group,
        "http://fake",
        "fake",
        "fake-model",
        translation_memory_context="[Genre: tu_tien]\n- 师父 dịch là sư phụ.",
    )

    assert "BỘ NHỚ DỊCH ÁP DỤNG CHO VIDEO NÀY" in captured["prompt"]
    assert "师父 dịch là sư phụ" in captured["prompt"]
    assert subtitle[0]["subtitle_text"] == "Sư phụ tới rồi"
    assert dub_text == "Sư phụ tới rồi"


if __name__ == "__main__":
    test_collect_memory_scoped()
    test_optimizer_prompt_includes_memory()
    print("OK translation memory tests")
