#!/usr/bin/env python3
"""JSON-only, local series compilation job orchestration."""
import argparse, copy, json, os, signal, subprocess, sys, tempfile, time
from pathlib import Path
import compile_videos
from brand_video import validate_regions

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_STATE = Path('/home/haonguyen/.openclaw-series/series.json')
DEFAULT_OUTPUT = Path('/mnt/hdd500/video douyin vietsub/compilations')
ASSETS = Path(__file__).resolve().parents[1] / 'assets' / 'brand-assets.json'
COMPILE = Path(__file__).with_name('compile_videos.py')
BRAND = Path(__file__).with_name('brand_video.py')
DETECT = Path(__file__).with_name('detect_overlays.py')
VALID = {'draft','queued','processing','needs_attention','completed','error','canceled'}
OVERLAY_PROFILES = {'bilibili_top_left_block'}
class BrandingError(ValueError): pass

def read_json(path):
    with path.open(encoding='utf-8') as f: return json.load(f)
def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.~job-', suffix='.json', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f: json.dump(data, f, ensure_ascii=False, indent=2); f.write('\n'); f.flush(); os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)
def safe_asset(value):
    p = Path(value)
    return p if p.is_absolute() else ROOT / p
def job_path(payload):
    ident = str(payload.get('compilation_id') or '').strip()
    if not ident or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-.' for c in ident): raise ValueError('invalid compilation_id')
    return Path(payload.get('output_root') or DEFAULT_OUTPUT) / ident
def state_manifest_path(payload):
    ident = job_path(payload).name
    state = Path(payload.get('state') or DEFAULT_STATE)
    return state.parent / 'compilations' / f'{ident}.json'
def write_manifest(payload, manifest):
    root = job_path(payload)
    atomic_json(root / 'manifest.json', manifest)
    atomic_json(state_manifest_path(payload), manifest)
def branding_requested(branding):
    return isinstance(branding, dict) and any(
        branding.get(mode) is True
        for mode in ('blur_logo', 'blur_title', 'replace_logo', 'blur', 'replacement')
    )
def branding_error(branding, regions):
    if branding_requested(branding) and (not isinstance(regions, list) or not regions):
        return 'branding requested but overlay_regions must be a non-empty explicit list; no automatic blur was applied'
    return None
def requested_overlay_labels(branding, profile=None):
    """Return automatic regions; the known profile maps all branding to one full block.

    For ``bilibili_top_left_block``, ``blur_logo``, ``blur_title``, and
    ``replace_logo`` intentionally request the same full block. Generic sources
    retain stricter title detection behavior.
    """
    if not branding_requested(branding): return []
    if profile == 'bilibili_top_left_block':
        return ['bilibili_top_left_block']
    requested=[]
    if branding.get('blur_logo') is True or branding.get('replace_logo') is True or branding.get('blur') is True or branding.get('replacement') is True:
        requested.append('bilibili_logo')
    if branding.get('blur_title') is True:
        requested.append('title')
    return requested
def run_overlay_detection(video, output_dir, profile=None, replacement=False):
    """Run the local detector for one trusted, already-resolved episode path."""
    cmd=[sys.executable, str(DETECT), '--input', str(video), '--output-dir', str(output_dir)]
    if profile in OVERLAY_PROFILES: cmd += ['--profile', profile]
    if replacement: cmd.append('--replacement')
    try:
        proc=subprocess.run(cmd, check=True, capture_output=True, text=True)
        result=json.loads(proc.stdout)
    except (subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        result={'state':'needs_attention','sampled_frame_previews':[],'previews':[],'diagnostics':{'reason':f'overlay detector failed closed: {exc}'},'regions':[]}
    if not isinstance(result, dict):
        return {'state':'needs_attention','sampled_frame_previews':[],'previews':[],'diagnostics':{'reason':'overlay detector returned invalid JSON'},'regions':[]}
    return result
def detect_requested_overlays(root, resolved, branding, profile=None):
    """Return detection records and compile-safe regions only if every request is proven."""
    requested=requested_overlay_labels(branding, profile)
    records, usable={}, {}
    errors=[]
    for episode in resolved:
        number=episode.get('episode_number')
        replacement = branding.get('replace_logo') is True or branding.get('replacement') is True
        result=run_overlay_detection(episode['path'], root/'overlay-detections'/f'episode-{number}', profile=profile, replacement=replacement)
        records[str(number)]=result
        by_label={item.get('label'):item for item in result.get('regions',[]) if isinstance(item,dict)}
        episode_regions=[]
        for label in requested:
            region=by_label.get(label)
            if result.get('state') != 'detected' or not region or region.get('confidence',0) < .8:
                reason=(result.get('diagnostics') or {}).get('reason','insufficient evidence')
                errors.append(f'episode {number}: overlay detection for {label} needs attention ({reason})')
                continue
            region=copy.deepcopy(region)
            if profile == 'bilibili_top_left_block':
                region['blur'] = True
                region['replacement'] = replacement
            else:
                region['blur']=label != 'bilibili_logo' or branding.get('blur_logo') is True or branding.get('blur') is True
                region['replacement']=label == 'bilibili_logo' and replacement
            episode_regions.append(region)
        usable[str(number)]=episode_regions
    return records, usable, '; '.join(errors) if errors else None
def overlay_profile(state, payload, branding):
    """Select only an explicitly allowlisted profile or a Bilibili series profile."""
    explicit = branding.get('profile') if isinstance(branding, dict) else None
    if explicit in OVERLAY_PROFILES:
        return {'name': explicit, 'source': 'branding'}
    series_id = payload.get('series_id')
    for series in state.get('series', []) if isinstance(state, dict) else []:
        if isinstance(series, dict) and series.get('series_id') == series_id and str(series.get('platform', '')).lower() == 'bilibili':
            return {'name': 'bilibili_top_left_block', 'source': 'series_platform'}
    return None
def plan_options(payload):
    order = payload.get('order', 'source')
    split_episodes = payload.get('split_episodes', False)
    if order != 'source': raise ValueError('only order="source" is supported')
    if split_episodes is not False: raise ValueError('only split_episodes=false is supported')
    for name in ('include_intro', 'include_outro'):
        if name in payload and not isinstance(payload[name], bool):
            raise ValueError(f'{name} must be boolean')
    return order, split_episodes
def blocked_status(payload, error):
    root = job_path(payload); root.mkdir(parents=True, exist_ok=True)
    status = {'version':1, 'compilation_id':root.name, 'state':'needs_attention',
              'error':str(error), 'worker_pid':None, 'parts':[], 'missing_episodes':[]}
    atomic_json(root/'status.json', status)
    return status
def normalized_regions(branding, regions):
    error = branding_error(branding, regions)
    if error: return regions, error
    if not branding_requested(branding): return regions, None
    low = [region for region in regions if isinstance(region, dict) and region.get('confidence', 1) < .8]
    allow_low = bool(low) and all(region.get('confirmed') is True for region in low)
    try:
        return validate_regions(regions, allow_low_confidence=allow_low), None
    except ValueError as exc:
        return regions, str(exc)
def include_brand_clip(branding, name):
    """Return an explicitly requested brand clip; branding is off by default."""
    if not isinstance(branding, dict): return False
    for key in (name, f'include_{name}', f'{name}_enabled'):
        if key in branding: return branding[key] is True
    return False
def resolve_episode_video(ep):
    """Prefer the current state path, then the legacy output-directory convention."""
    candidates=[]
    direct=ep.get('final_video_path')
    if direct: candidates.append(Path(direct))
    for key in ('final_video_vi_path','final_video_vi'):
        value=ep.get(key)
        if value: candidates.append(Path(value))
    out=ep.get('last_output_dir')
    if out: candidates.append(Path(out) / 'final_video_vi.mp4')
    for video in candidates:
        if video.is_file(): return video.resolve()
    return None
def plan_preview(parts, missing, warnings):
    return {'parts':[{'part':p['part'],'episode_numbers':[e['episode_number'] for e in p['episodes']], 'duration_seconds':p['duration_seconds']} for p in parts], 'missing_episode_numbers':[e['episode_number'] for e in missing], 'warnings':list(warnings)}
def plan(payload):
    from series_compilation import select, pack
    try:
        order, split_episodes = plan_options(payload)
        max_seconds = compile_videos.validate_max_seconds(payload.get('max_seconds', 5400))
    except ValueError as exc:
        return blocked_status(payload, exc)
    state = read_json(Path(payload.get('state') or DEFAULT_STATE))
    assets = read_json(ASSETS)
    branding = payload.get('branding', {})
    include_intro = payload.get('include_intro', include_brand_clip(branding, 'intro'))
    include_outro = payload.get('include_outro', include_brand_clip(branding, 'outro'))
    intro = safe_asset(assets['approved_intro_mp4']) if include_intro else None
    outro = safe_asset(assets['approved_outro_mp4']) if include_outro else None
    if (intro and not intro.is_file()) or (outro and not outro.is_file()): raise ValueError('missing approved intro/outro asset')
    intro_seconds = compile_videos.duration(intro) if intro else 0
    outro_seconds = compile_videos.duration(outro) if outro else 0
    selected = select(state, payload.get('selector','all'), payload.get('series_id'))
    resolved=[]; missing=[]
    for ep in selected:
        video = resolve_episode_video(ep)
        if video: resolved.append({**ep, 'path': str(video)})
        else: missing.append({**ep, 'reason':'missing_or_unprocessed_output'})
    packed = pack(resolved, intro_seconds, outro_seconds, max_seconds)
    explicit_regions=payload.get('overlay_regions')
    profile = overlay_profile(state, payload, branding)
    overlay_detections={}; detected_regions={}
    if branding_requested(branding) and not explicit_regions:
        root=job_path(payload); root.mkdir(parents=True,exist_ok=True)
        overlay_detections, detected_regions, attention_error=detect_requested_overlays(root, resolved, branding, profile=profile['name'] if profile else None)
        # Keep a canonical preview for operators, while run() consumes per-episode
        # records so pixels from one episode are never applied to another.
        regions=next(iter(detected_regions.values()), []) if detected_regions else []
    else:
        regions, attention_error = normalized_regions(branding, explicit_regions)
    parts=[]
    for i, part in enumerate(packed['manifests'], 1):
        entry={'part':i,'intro':str(intro.resolve()) if intro else None,'outro':str(outro.resolve()) if outro else None,'episodes':part['episodes'],'duration_seconds':part['duration_seconds'],'status':'needs_attention' if attention_error else 'queued'}
        if attention_error: entry['error']=attention_error
        parts.append(entry)
    ident = str(payload['compilation_id'])
    voice=payload.get('voice',payload.get('selected_voice'))
    manifest={'version':1,'compilation_id':ident,'series_id':payload.get('series_id'),'max_seconds':max_seconds,'selector':payload.get('selector','all'),'order':order,'split_episodes':split_episodes,'include_intro':include_intro,'include_outro':include_outro,'voice':voice,'branding':branding,'overlay_profile':profile,'overlay_regions':regions,'overlay_detections':overlay_detections,'detected_overlay_regions':detected_regions,'parts':parts,'missing_episodes':missing,'warnings':packed['warnings']}
    root=job_path(payload); root.mkdir(parents=True,exist_ok=True); write_manifest(payload, manifest)
    preview=plan_preview(parts, missing, packed['warnings'])
    status={'version':1,'compilation_id':ident,'state':'needs_attention' if missing or attention_error else 'queued','manifest':str((root/'manifest.json').resolve()),'state_manifest':str(state_manifest_path(payload).resolve()),'worker_pid':None,'overlay_profile':profile,'overlay_detections':overlay_detections,'parts':[{'part':p['part'],'state':p['status'],'output':None,'pid':None,**({'error':attention_error} if attention_error else {})} for p in parts],'missing_episodes':missing,'plan_preview':preview}
    atomic_json(root/'status.json',status); return status
def load(payload): return read_json(job_path(payload)/'status.json')
def record_completed_state(payload, manifest, status):
    """Atomically add completed compilation metadata without restructuring state."""
    series_id = manifest.get('series_id')
    if not series_id:
        raise ValueError('manifest is missing series_id')
    state_path = Path(payload.get('state') or DEFAULT_STATE)
    state = read_json(state_path)
    if not isinstance(state, dict):
        raise ValueError('state JSON must be an object')
    series = [item for item in state.get('series', []) if isinstance(item, dict) and item.get('series_id') == series_id]
    if len(series) != 1:
        raise ValueError(f'series_id {series_id!r} was not found exactly once')
    by_part = {item.get('part'): item for item in manifest.get('parts', []) if isinstance(item, dict)}
    selected = []
    for part in status.get('parts', []):
        source = by_part.get(part.get('part'))
        if not source:
            raise ValueError(f"manifest is missing part {part.get('part')}")
        for episode in source.get('episodes', []):
            number = episode.get('episode_number')
            selected.append((number, part.get('part'), part.get('output')))
    episodes = series[0].get('episodes')
    if not isinstance(episodes, list):
        raise ValueError(f'series {series_id!r} has no episode list')
    targets = {}
    for episode in episodes:
        if isinstance(episode, dict):
            targets.setdefault(episode.get('episode_number'), []).append(episode)
    for number, _, _ in selected:
        if number not in targets:
            raise ValueError(f'selected episode {number!r} is missing from state')
    compilation_id = manifest.get('compilation_id') or payload.get('compilation_id')
    for number, part_number, output in selected:
        for episode in targets[number]:
            used = episode.get('compilations_used')
            if not isinstance(used, list):
                used = []
                episode['compilations_used'] = used
            if compilation_id not in used:
                used.append(compilation_id)
            outputs = episode.get('compilation_outputs')
            if not isinstance(outputs, list):
                outputs = []
                episode['compilation_outputs'] = outputs
            mapping = {'compilation_id': compilation_id, 'part': part_number, 'output': output}
            existing = next((index for index, item in enumerate(outputs) if isinstance(item, dict) and item.get('compilation_id') == compilation_id and item.get('part') == part_number), None)
            if existing is None:
                outputs.append(mapping)
            else:
                outputs[existing] = mapping
    atomic_json(state_path, state)
def brand_episodes(root, manifest, part_number, part_data):
    """Brand one part's episodes and return a compile-ready copy plus proof records."""
    branding, default_regions = manifest.get('branding', {}), manifest.get('overlay_regions')
    branded_part, proofs = copy.deepcopy(part_data), []
    for episode in branded_part.get('episodes', []):
        number, source = episode.get('episode_number'), episode.get('path')
        if not isinstance(number, int) or not source: raise BrandingError('episode requires number and source path for branding')
        regions = (manifest.get('detected_overlay_regions') or {}).get(str(number), default_regions)
        regions, error = normalized_regions(branding, regions)
        if error: raise BrandingError(error)
        replacement = any(isinstance(region, dict) and region.get('replacement') is True for region in regions)
        logo = None
        if replacement:
            assets = read_json(ASSETS)
            logo = safe_asset(assets.get('logo', ''))
            if not logo.is_file(): raise BrandingError('missing approved branding logo asset')
        output_dir = root / 'parts' / 'branding' / f'episode-{number}'
        regions_path = output_dir / 'requested_regions.json'
        runnable_regions = copy.deepcopy(regions)
        low_confidence = [region for region in runnable_regions if region.get('confidence', 1) < 0.8]
        allow_low_confidence = bool(low_confidence) and all(region.get('confirmed') is True for region in low_confidence)
        if allow_low_confidence:
            for region in runnable_regions:
                region.pop('confirmed', None)
        atomic_json(regions_path, runnable_regions)
        cmd=[sys.executable, str(BRAND), '--input', str(source), '--regions', str(regions_path), '--output-dir', str(output_dir), '--execute']
        if replacement: cmd += ['--logo', str(logo)]
        if allow_low_confidence: cmd.append('--allow-low-confidence')
        try:
            proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
            proof = json.loads(proc.stdout)
        except subprocess.CalledProcessError as exc:
            detail = str(exc)
            try:
                detail = json.loads(exc.stdout or '').get('error') or detail
            except (TypeError, ValueError):
                pass
            raise BrandingError(f'branding failed for episode {number}: {detail}') from exc
        except Exception as exc:
            raise BrandingError(f'branding failed for episode {number}: {exc}') from exc
        branded = output_dir / 'branded.mp4'
        if proof.get('status') != 'executed' or not branded.is_file(): raise BrandingError(f'branding did not produce output for episode {number}')
        compile_path = output_dir / 'final_video_vi.mp4'
        if compile_path.exists() or compile_path.is_symlink(): compile_path.unlink()
        compile_path.symlink_to(branded.name)
        episode['path'] = str(compile_path)
        proofs.append({'episode_number':number, 'input':str(source), 'output':str(branded), 'regions':str(output_dir / 'overlay_regions.json'), 'proof':str(output_dir / 'overlay_proof.json')})
    return branded_part, proofs
def verify_completed_output(value):
    """Require a regular, decodable file with a positive duration before completion."""
    output = Path(value or '')
    if not output.is_file() or output.stat().st_size <= 0:
        raise ValueError('compiled output is missing or not a regular non-empty file')
    try:
        media = compile_videos.probe_media(output)
    except Exception as exc:
        raise ValueError('compiled output failed ffprobe quality gate') from exc
    if media['duration'] <= 0:
        raise ValueError('compiled output has no positive duration')
    return media['duration']
def run(payload, resume=False):
    root=job_path(payload); manifest=root/'manifest.json'; status=load(payload)
    if status['state'] == 'canceled' and not resume: return status
    allowed = {'approved', 'queued', 'processing', 'resume_after_fix'}
    if status.get('state') not in allowed:
        status['error'] = f"compilation cannot execute from {status.get('state')!r}; fix the plan and explicitly queue or approve it"
        atomic_json(root/'status.json', status)
        return status
    status['state']='processing'; atomic_json(root/'status.json',status)
    manifest_data = read_json(manifest)
    for part in status['parts']:
        allowed = {'queued', 'error', 'needs_attention'} if resume else {'queued'}
        if part['state'] not in allowed: continue
        part['state']='processing'; atomic_json(root/'status.json',status)
        part_number = part['part']
        part_manifest = root / f'.part-{part_number}-manifest.json'
        part_output = root / 'parts' / f'part-{part_number}'
        try:
            source_part = manifest_data['parts'][part_number - 1]
            if branding_requested(manifest_data.get('branding')):
                compile_part, proofs = brand_episodes(root, manifest_data, part_number, source_part)
                part['branding_proofs'] = proofs
                manifest_data.setdefault('branding_proofs', {})[str(part_number)] = proofs
                write_manifest(payload, manifest_data)
            else:
                compile_part = source_part
            atomic_json(part_manifest, {**manifest_data, 'parts': [compile_part]})
            cmd=[sys.executable,str(COMPILE),'--manifest',str(part_manifest),'--output-dir',str(part_output),'--execute']
            proc=subprocess.run(cmd, check=True, capture_output=True, text=True)
            result=json.loads(proc.stdout); entry=result['parts'][0]
            output = entry.get('output')
            duration = verify_completed_output(output)
            part.update(state='completed',output=output,duration=duration,pid=None); part.pop('error', None)
        except BrandingError as exc: part.update(state='needs_attention',error=str(exc),pid=None)
        except Exception as exc: part.update(state='error',error=str(exc),pid=None)
        finally:
            try: part_manifest.unlink()
            except FileNotFoundError: pass
        atomic_json(root/'status.json',status)
    status['state']='completed' if status['parts'] and all(p['state']=='completed' for p in status['parts']) else ('error' if any(p['state']=='error' for p in status['parts']) else 'needs_attention')
    if status['state'] == 'completed':
        try:
            record_completed_state(payload, manifest_data, status)
            status.pop('state_update_error', None)
        except Exception as exc:
            status['state'] = 'needs_attention'
            status['state_update_error'] = f'state bookkeeping failed: {exc}'
    atomic_json(root/'status.json',status); return status

def tracked_worker_alive(status):
    """Return true only for a tracked process that remains its own session leader."""
    pid = status.get('worker_pid')
    if not isinstance(pid, int) or pid <= 1:
        return False
    try:
        os.kill(pid, 0)
        return os.getpgid(pid) == pid
    except (ProcessLookupError, PermissionError, OSError):
        return False

def enqueue(payload, resume=False):
    """Start an isolated worker and return promptly with its tracked PID."""
    root = job_path(payload)
    status = load(payload)
    if status.get('state') == 'completed':
        return status
    allowed = {'approved', 'queued', 'processing', 'resume_after_fix'}
    if status.get('state') not in allowed:
        status['error'] = f"compilation cannot start from {status.get('state')!r}; fix the plan and explicitly queue or approve it"
        atomic_json(root/'status.json', status)
        return status
    if tracked_worker_alive(status):
        return status
    status['worker_pid'] = None
    if status.get('state') in {'approved', 'resume_after_fix'}:
        status['state'] = 'queued'
    command = [sys.executable, str(Path(__file__).resolve()), 'execute', '--queued-worker', '--payload', json.dumps(payload, ensure_ascii=False)]
    if resume:
        command.append('--resume')
    try:
        worker = subprocess.Popen(
            command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True, close_fds=True,
        )
    except Exception:
        atomic_json(root/'status.json', status)
        raise
    status['worker_pid'] = worker.pid
    atomic_json(root/'status.json', status)
    return status

def execute(payload, resume=False, queued_worker=False):
    """Synchronous child-worker entry point; clear only its own tracking record."""
    root = job_path(payload)
    if queued_worker:
        deadline = time.monotonic() + 1
        while True:
            tracked = load(payload)
            if tracked.get('worker_pid') == os.getpid():
                break
            if tracked.get('state') == 'canceled':
                return tracked
            if time.monotonic() >= deadline:
                raise RuntimeError('worker was not registered')
            time.sleep(0.01)
    try:
        return run(payload, resume)
    finally:
        status = load(payload)
        if status.get('worker_pid') == os.getpid():
            status['worker_pid'] = None
            atomic_json(root/'status.json', status)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('command',choices=['plan','run','status','resume','execute','cancel']); ap.add_argument('--payload',required=True); ap.add_argument('--resume',action='store_true'); ap.add_argument('--queued-worker',action='store_true'); a=ap.parse_args()
    try:
        payload=json.loads(a.payload)
        if not isinstance(payload,dict): raise ValueError('payload must be object')
        result = plan(payload) if a.command=='plan' else load(payload) if a.command=='status' else enqueue(payload,a.command=='resume') if a.command in {'run','resume'} else execute(payload,a.resume,a.queued_worker) if a.command=='execute' else cancel(payload)
        print(json.dumps(result,ensure_ascii=False,sort_keys=True)); return 0
    except Exception as exc: print(json.dumps({'error':str(exc)},ensure_ascii=False)); return 2
def cancel(payload):
    root=job_path(payload); status=load(payload)
    if tracked_worker_alive(status):
        try: os.killpg(status['worker_pid'], signal.SIGTERM)
        except ProcessLookupError: pass
        except OSError: pass
    for p in status.get('parts',[]):
        if p['state'] in {'processing','queued','error','needs_attention'}: p['state']='canceled'
        p['pid']=None
    status['worker_pid']=None; status['state']='canceled'; atomic_json(root/'status.json',status); return status
if __name__=='__main__': sys.exit(main())
