#!/usr/bin/env python3
"""Local, fail-closed overlay detection using FFmpeg samples and edge persistence.

For unknown sources, this derives candidates from persistent top-left edges across
several decoded frames.  The allowlisted ``bilibili_top_left_block`` profile uses
the approved normalized fixed profile covering the known full top-left block.
OCR is only an optional diagnostic; no cloud or model/API calls are made.
"""
import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

CANONICAL = ('label', 'x', 'y', 'width', 'height', 'start', 'end', 'confidence', 'blur', 'replacement', 'confirmed')
PROFILES = {'bilibili_top_left_block': (0.015, 0.025, 0.18, 0.075)}


def command(args):
    return subprocess.run(args, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def probe(video):
    data = json.loads(command(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height:format=duration', '-of', 'json', str(video)]).stdout)
    stream = (data.get('streams') or [{}])[0]
    width, height = int(stream['width']), int(stream['height'])
    duration = max(float((data.get('format') or {}).get('duration') or 0), 0.0)
    if not width or not height or not duration:
        raise ValueError('video has no decodable visual duration')
    return width, height, duration


def sample_frames(video, output_dir, count=5):
    width, height, duration = probe(video)
    output_dir.mkdir(parents=True, exist_ok=True)
    times = [duration * (index + 1) / (count + 1) for index in range(count)]
    frames, previews = [], []
    for index, moment in enumerate(times):
        target = output_dir / f'frame-{index + 1:02d}.pgm'
        preview = output_dir / f'frame-{index + 1:02d}.png'
        command(['ffmpeg', '-y', '-v', 'error', '-ss', f'{moment:.3f}', '-i', str(video), '-frames:v', '1', '-vf', 'format=gray', str(target)])
        command(['ffmpeg', '-y', '-v', 'error', '-ss', f'{moment:.3f}', '-i', str(video), '-frames:v', '1', str(preview)])
        if not target.is_file() or target.stat().st_size <= 20 or not preview.is_file() or not preview.read_bytes().startswith(b'\x89PNG\r\n\x1a\n'):
            raise ValueError(f'failed to decode sample frame {index + 1}')
        frames.append(target)
        previews.append(preview)
    return width, height, duration, frames, previews


def read_pgm(path):
    raw = path.read_bytes()
    pieces, pos = [], 0
    while len(pieces) < 4:
        while pos < len(raw) and raw[pos:pos + 1].isspace(): pos += 1
        if raw[pos:pos + 1] == b'#':
            pos = raw.find(b'\n', pos) + 1
            continue
        end = pos
        while end < len(raw) and not raw[end:end + 1].isspace(): end += 1
        pieces.append(raw[pos:end]); pos = end
    if pieces[0] != b'P5' or pieces[3] != b'255':
        raise ValueError('expected 8-bit binary PGM preview')
    while pos < len(raw) and raw[pos:pos + 1].isspace(): pos += 1
    width, height = int(pieces[1]), int(pieces[2])
    pixels = raw[pos:pos + width * height]
    if len(pixels) != width * height: raise ValueError('truncated PGM preview')
    return width, height, pixels


def edge_map(pixels, width, height, limit_width, limit_height):
    edges = set()
    # A compact threshold avoids adding imaging dependencies while still measuring
    # actual visual evidence rather than assuming a logo rectangle.
    for y in range(1, limit_height - 1):
        row = y * width
        for x in range(1, limit_width - 1):
            value = pixels[row + x]
            magnitude = abs(value - pixels[row + x - 1]) + abs(value - pixels[row + x + 1]) + abs(value - pixels[row - width + x]) + abs(value - pixels[row + width + x])
            if magnitude >= 130:
                edges.add((x, y))
    return edges


def components(points):
    remaining, found = set(points), []
    while remaining:
        start, todo, group = remaining.pop(), [], []
        todo.append(start)
        while todo:
            x, y = todo.pop(); group.append((x, y))
            # Permit small anti-aliasing gaps while retaining evidence-derived bounds.
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (2, 0), (-2, 0), (0, 2), (0, -2)):
                item = (x + dx, y + dy)
                if item in remaining: remaining.remove(item); todo.append(item)
        found.append(group)
    return found


def static_candidate(frame_paths, width, height):
    roi_width, roi_height = max(8, int(width * .35)), max(8, int(height * .25))
    edge_sets = []
    for frame in frame_paths:
        frame_width, frame_height, pixels = read_pgm(frame)
        if (frame_width, frame_height) != (width, height): raise ValueError('sample dimensions changed')
        edge_sets.append(edge_map(pixels, width, height, roi_width, roi_height))
    if not edge_sets: return None, 0.0, 0.0
    votes = {}
    for edges in edge_sets:
        for point in edges: votes[point] = votes.get(point, 0) + 1
    required = max(3, int(len(edge_sets) * .8 + .999))
    stable = {point for point, value in votes.items() if value >= required}
    if not stable: return None, 0.0, 0.0
    groups = components(stable)
    groups = [group for group in groups if len(group) >= 16]
    if not groups: return None, 0.0, 0.0
    group = max(groups, key=len)
    x0, x1 = min(x for x, _ in group), max(x for x, _ in group)
    y0, y1 = min(y for _, y in group), max(y for _, y in group)
    # Pad only around discovered edges; bounds are not a hard-coded target area.
    x0, y0 = max(0, x0 - 3), max(0, y0 - 3)
    x1, y1 = min(width - 1, x1 + 3), min(height - 1, y1 + 3)
    area = (x1 - x0 + 1) * (y1 - y0 + 1)
    stable_ratio = sum(votes[point] for point in group) / (len(group) * len(edge_sets))
    edge_density = len(group) / max(area, 1)
    if x0 > width * .2 or y0 > height * .16 or area < 80 or edge_density < .025:
        return None, stable_ratio, edge_density
    confidence = min(.99, round(.55 * stable_ratio + min(.35, edge_density * 2.5) + .1, 3))
    if confidence < .8: return None, stable_ratio, edge_density
    return (x0, y0, x1 - x0 + 1, y1 - y0 + 1, confidence), stable_ratio, edge_density


def canonical_region(label, x, y, width, height, end, confidence, blur=True, replacement=False, confirmed=False):
    return {'label': label, 'x': int(x), 'y': int(y), 'width': int(width), 'height': int(height), 'start': 0, 'end': round(end, 3), 'confidence': float(confidence), 'blur': bool(blur), 'replacement': bool(replacement), 'confirmed': bool(confirmed)}


def profile_region(profile, width, height, duration, replacement=False):
    """Return the approved normalized block, clamped to the decoded frame."""
    normalized = PROFILES.get(profile)
    if not normalized:
        return None
    x, y, block_width, block_height = normalized
    left, top = round(width * x), round(height * y)
    right, bottom = round(width * (x + block_width)), round(height * (y + block_height))
    left, top = min(max(left, 0), max(width - 1, 0)), min(max(top, 0), max(height - 1, 0))
    right, bottom = min(max(right, left + 1), width), min(max(bottom, top + 1), height)
    return canonical_region(profile, left, top, right - left, bottom - top, duration, .99, blur=True, replacement=replacement, confirmed=True)


def ocr_diagnostics(frame):
    """Use a locally installed OCR binary only as an optional diagnostic."""
    binary = shutil.which('tesseract')
    if not binary:
        return {'available': False, 'reason': 'OCR binary unavailable; title overlays require explicit confirmed regions'}
    try:
        result = command([binary, str(frame), 'stdout', '--psm', '6', 'tsv'])
        confidences = []
        for line in result.stdout.splitlines()[1:]:
            fields = line.split('\t')
            if len(fields) >= 12 and fields[11].strip():
                try: confidences.append(float(fields[10]) / 100)
                except ValueError: pass
        confidence = max(confidences, default=0.0)
        return {'available': True, 'max_confidence': round(confidence, 3), 'reason': 'OCR title candidate confidence is below automatic threshold' if confidence < .8 else 'OCR text observed; explicit title bounds are still required'}
    except Exception as exc:
        return {'available': True, 'reason': f'OCR unavailable for this sample: {exc}'}


def detect(video, output_dir, profile=None, replacement=False):
    """Decode local samples and return only high-confidence edge-supported regions."""
    video, output_dir = Path(video), Path(output_dir)
    if not video.is_file(): raise ValueError('input video must be a local regular file')
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'): raise ValueError('ffmpeg and ffprobe are required for local overlay detection')
    if profile is not None and profile not in PROFILES:
        raise ValueError('unsupported overlay profile')
    width, height, duration, frames, previews = sample_frames(video, output_dir / 'previews')
    candidate, static_ratio, density = static_candidate(frames, width, height)
    diagnostics = {'method': 'sampled_top_left_static_edges', 'sample_count': len(frames), 'static_edge_ratio': round(static_ratio, 3), 'edge_density': round(density, 3), 'ocr': ocr_diagnostics(frames[0])}
    if profile:
        diagnostics['profile'] = profile
        diagnostics['reason'] = 'approved Bilibili top-left watermark block profile; samples retained for operator review'
        return {'state': 'detected', 'sampled_frame_previews': [str(path.resolve()) for path in previews], 'previews': [str(path.resolve()) for path in previews], 'diagnostics': diagnostics, 'regions': [profile_region(profile, width, height, duration, replacement)]}
    if candidate is None:
        diagnostics['reason'] = 'no stable top-left overlay had sufficient temporal/static edge evidence; no automatic blur proposed'
        return {'state': 'needs_attention', 'sampled_frame_previews': [str(path.resolve()) for path in previews], 'previews': [str(path.resolve()) for path in previews], 'diagnostics': diagnostics, 'regions': []}
    region = canonical_region('bilibili_logo', *candidate[:4], duration, candidate[4])
    diagnostics['reason'] = 'static edge evidence supports top-left Bilibili-style logo candidate'
    return {'state': 'detected', 'sampled_frame_previews': [str(path.resolve()) for path in previews], 'previews': [str(path.resolve()) for path in previews], 'diagnostics': diagnostics, 'regions': [region]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, help='fixed local episode path supplied by compilation_job')
    parser.add_argument('--output-dir', required=True, help='local job-owned directory supplied by compilation_job')
    parser.add_argument('--profile', choices=sorted(PROFILES), help='approved source-specific overlay profile')
    parser.add_argument('--replacement', action='store_true', help='mark the approved profile region for logo replacement')
    args = parser.parse_args()
    try:
        print(json.dumps(detect(args.input, args.output_dir, args.profile, args.replacement), ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({'state': 'needs_attention', 'error': str(exc), 'sampled_frame_previews': [], 'previews': [], 'diagnostics': {'reason': 'detection failed closed'}, 'regions': []}, ensure_ascii=False, sort_keys=True))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
