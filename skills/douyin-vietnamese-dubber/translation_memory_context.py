#!/usr/bin/env python3
"""Build scoped translation-memory context for the Vietnamese dubbing prompt."""
import argparse
import json
import re
import sys
from pathlib import Path


SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
SPLIT_RE = re.compile(r"[\s,;]+")


def normalize_id(value):
    value = (value or "").strip()
    if not value or not SAFE_ID_RE.match(value):
        return ""
    return value


def parse_genre_tags(raw):
    if raw is None:
        return []
    if isinstance(raw, list):
        items = raw
    else:
        text = str(raw).strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                data = json.loads(text)
                items = data if isinstance(data, list) else [text]
            except Exception:
                items = SPLIT_RE.split(text)
        else:
            items = SPLIT_RE.split(text)

    out = []
    seen = set()
    for item in items:
        tag = normalize_id(str(item))
        if tag and tag not in seen:
            out.append(tag)
            seen.add(tag)
    return out


def read_text_file(path, warnings):
    try:
        if not path.exists() or not path.is_file():
            return ""
        text = path.read_text(encoding="utf-8", errors="replace").strip()
        return text
    except Exception as exc:
        warnings.append(f"cannot_read:{path.name}:{exc}")
        return ""


def load_json_file(path, warnings):
    try:
        if not path.exists() or not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:
        warnings.append(f"invalid_json:{path.name}:{exc}")
        return None


def glossary_lines(data):
    if not data:
        return []
    lines = []
    if isinstance(data, dict):
        for source, target in sorted(data.items()):
            if isinstance(target, dict):
                vi = target.get("vi") or target.get("target") or target.get("translation") or ""
                note = target.get("note") or ""
                if vi:
                    suffix = f" ({note})" if note else ""
                    lines.append(f"- {source} => {vi}{suffix}")
            elif isinstance(target, str):
                lines.append(f"- {source} => {target}")
    elif isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            source = item.get("source") or item.get("zh") or item.get("term") or ""
            target = item.get("target") or item.get("vi") or item.get("translation") or ""
            note = item.get("note") or ""
            if source and target:
                suffix = f" ({note})" if note else ""
                lines.append(f"- {source} => {target}{suffix}")
    return lines


def character_lines(data):
    if not data:
        return []
    lines = []
    if isinstance(data, dict):
        items = data.items()
    elif isinstance(data, list):
        items = []
        for item in data:
            if isinstance(item, dict):
                name = item.get("name") or item.get("id") or item.get("character") or ""
                items.append((name, item))
    else:
        return lines

    for name, meta in items:
        if isinstance(meta, str):
            lines.append(f"- {name}: {meta}")
            continue
        if not isinstance(meta, dict):
            continue
        vi_name = meta.get("vi_name") or meta.get("name_vi") or meta.get("display_name") or ""
        address = meta.get("addressing") or meta.get("xung_ho") or meta.get("pronouns") or ""
        note = meta.get("note") or ""
        parts = []
        if vi_name:
            parts.append(f"tên Việt: {vi_name}")
        if address:
            parts.append(f"xưng hô: {address}")
        if note:
            parts.append(note)
        if parts and name:
            lines.append(f"- {name}: {'; '.join(parts)}")
    return lines


def trim_context(text, max_chars):
    max_chars = max(0, int(max_chars or 0))
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    marker = "\n[Memory trimmed to fit prompt budget]\n"
    keep = max(0, max_chars - len(marker))
    return text[:keep].rstrip() + marker


def collect_memory(memory_dir, genre_tags=None, series_id="", max_chars=6000):
    root = Path(memory_dir)
    warnings = []
    sections = []

    global_text = read_text_file(root / "global_style.md", warnings)
    if global_text:
        sections.append(("[Global]", global_text))

    for tag in parse_genre_tags(genre_tags):
        text = read_text_file(root / "genres" / f"{tag}.md", warnings)
        if text:
            sections.append((f"[Genre: {tag}]", text))

    safe_series = normalize_id(series_id)
    if safe_series:
        series_dir = root / "series" / safe_series
        style = read_text_file(series_dir / "style.md", warnings)
        if style:
            sections.append((f"[Series: {safe_series}]", style))

        glossary = glossary_lines(load_json_file(series_dir / "glossary.json", warnings))
        if glossary:
            sections.append((f"[Series glossary: {safe_series}]", "\n".join(glossary)))

        characters = character_lines(load_json_file(series_dir / "characters.json", warnings))
        if characters:
            sections.append((f"[Series characters: {safe_series}]", "\n".join(characters)))

    body = "\n\n".join(f"{title}\n{text.strip()}" for title, text in sections if text.strip())
    return trim_context(body.strip(), max_chars), warnings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--memory-dir", required=True)
    parser.add_argument("--genre-tags", default="")
    parser.add_argument("--series-id", default="")
    parser.add_argument("--max-chars", type=int, default=6000)
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    context, warnings = collect_memory(
        args.memory_dir,
        genre_tags=args.genre_tags,
        series_id=args.series_id,
        max_chars=args.max_chars,
    )
    for warning in warnings:
        print(f"WARN: translation memory {warning}", file=sys.stderr)
    if args.out:
        Path(args.out).write_text(context, encoding="utf-8")
    else:
        print(context)


if __name__ == "__main__":
    main()
