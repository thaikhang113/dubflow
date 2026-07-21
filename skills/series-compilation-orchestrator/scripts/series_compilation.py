#!/usr/bin/env python3
import argparse,json,sys
from pathlib import Path
from dataclasses import dataclass,asdict
LIMIT_SECONDS=90*60
def seconds(v):
    if isinstance(v,(int,float)): return max(0,int(v))
    s=str(v or '').strip()
    try:
        if ':' in s:
            p=[int(x) for x in s.split(':')]; return p[-1]+60*p[-2]+(3600*p[-3] if len(p)>2 else 0)
        return max(0,int(float(s)))
    except ValueError:return 0
def normalize_state(raw):
    raw=raw if isinstance(raw,dict) else {}; series=raw.get('series',[]); series=[series] if isinstance(series,dict) else series
    out={'version':2,'series':[]}
    for item in series if isinstance(series,list) else []:
        if not isinstance(item,dict): continue
        eps=item.get('episodes',[]); eps=list(eps.values()) if isinstance(eps,dict) else eps; normalized=[]
        for i,ep in enumerate(eps if isinstance(eps,list) else []):
            if not isinstance(ep,dict): continue
            e=dict(ep)
            try:n=int(e.get('episode_number',e.get('number',i)))
            except (TypeError,ValueError):n=i
            e.update(episode_number=n,duration_seconds=seconds(e.get('duration_seconds',e.get('duration'))),status=str(e.get('status') or 'unknown').lower()); normalized.append(e)
        normalized.sort(key=lambda e:(e['episode_number'],e.get('url',''),e.get('title',''))); copy=dict(item); copy['episodes']=normalized; out['series'].append(copy)
    return out
def select(state,selector='all',series_id=None):
    eps=[e for s in normalize_state(state)['series'] if series_id is None or s.get('series_id')==series_id for e in s['episodes']]; selector=selector.strip().lower()
    if selector in ('','all'): return eps
    if selector=='latest': return eps[-1:]
    if selector.startswith('latest:'):
        try: count=int(selector[7:])
        except ValueError as exc: raise ValueError('latest:N requires a positive integer') from exc
        if count < 1: raise ValueError('latest:N requires a positive integer')
        return eps[-count:]
    if selector=='unprocessed': return [e for e in eps if not is_processed(e)]
    try:
        if selector.startswith('range:'): a,b=selector[6:].split('-',1); wanted=set(range(int(a),int(b)+1))
        elif selector.startswith('list:'): wanted={int(x) for x in selector[5:].split(',') if x.strip()}
        else: raise ValueError
    except ValueError as exc: raise ValueError('selector must be all, latest, latest:N, unprocessed, range:N-M, or list:N,M') from exc
    return [e for e in eps if e['episode_number'] in wanted]
def is_processed(ep):
    """Treat any declared final output or completed localization as processed."""
    if ep.get('final_video_path') or ep.get('final_video_vi') or ep.get('final_video_vi_path'):
        return True
    output=ep.get('output')
    if isinstance(output,dict) and (output.get('final_video_path') or output.get('final_video_vi')): return True
    legacy_dir=ep.get('last_output_dir')
    if legacy_dir and (Path(legacy_dir) / 'final_video_vi.mp4').is_file(): return True
    completed={'completed','compiled','done','processed'}
    if str(ep.get('status') or '').lower() in completed or str(ep.get('localization_status') or '').lower() in completed: return True
    localization=ep.get('localization')
    if isinstance(localization,dict): return str(localization.get('status',localization.get('state',''))).lower() in completed
    return str(localization or '').lower() in completed
@dataclass
class Manifest: manifest_id:str; episode_numbers:list; episodes:list; intro_seconds:int; outro_seconds:int; duration_seconds:int; warnings:list
def pack(selected,intro=0,outro=0,limit=LIMIT_SECONDS):
    manifests=[]; current=[]; total=intro+outro; warnings=[]
    def flush():
        nonlocal current,total
        if current:
            n=[e['episode_number'] for e in current]; manifests.append(asdict(Manifest(f'compilation-{n[0]}-{n[-1]}',n,current,intro,outro,total,[]))); current=[]; total=intro+outro
    for ep in selected:
        d=ep['duration_seconds']
        if d+intro+outro>limit:
            flush(); w=f"episode {ep['episode_number']} exceeds {limit} seconds"; warnings.append(w); n=ep['episode_number']; manifests.append(asdict(Manifest(f'compilation-{n}-{n}',[n],[ep],intro,outro,d+intro+outro,[w])))
        elif current and total+d>limit: flush(); current=[ep]; total=intro+outro+d
        else: current.append(ep); total+=d
    flush(); return {'limit_seconds':limit,'manifests':manifests,'warnings':warnings}
def main(argv=None):
    p=argparse.ArgumentParser(); sub=p.add_subparsers(dest='command',required=True)
    for name in ('list','plan'):
        q=sub.add_parser(name); q.add_argument('--state',required=True); q.add_argument('--series-id')
        if name=='plan': q.add_argument('--selector',default='all'); q.add_argument('--intro',type=int,default=0); q.add_argument('--outro',type=int,default=0)
    a=p.parse_args(argv)
    try:
        with open(a.state,encoding='utf-8') as f: state=json.load(f)
        result={'version':2,'episodes':select(state,'all',a.series_id)} if a.command=='list' else pack(select(state,a.selector,a.series_id),a.intro,a.outro)
        print(json.dumps(result,ensure_ascii=False,sort_keys=True)); return 0
    except Exception as exc: print(json.dumps({'error':str(exc)},ensure_ascii=False)); return 2
if __name__=='__main__':sys.exit(main())
