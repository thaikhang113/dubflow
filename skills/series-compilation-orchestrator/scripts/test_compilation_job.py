import json, os, shutil, subprocess, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import compilation_job
from brand_video import build_filter

class TestJob(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)
        self.state=self.root/'series.json'; self.state.write_text(json.dumps({'series':[{'series_id':'s','episodes':[{'episode_number':1,'status':'ready','last_output_dir':str(self.root/'ep1')},{'episode_number':2,'status':'ready','last_output_dir':str(self.root/'none')}]}]}))
        (self.root/'ep1').mkdir(); (self.root/'ep1'/'final_video_vi.mp4').write_bytes(b'x')
        self.intro=self.root/'intro.mp4'; self.outro=self.root/'outro.mp4'; self.intro.touch(); self.outro.touch()
        self.payload={'compilation_id':'t1','state':str(self.state),'output_root':str(self.root/'out')}
        self.output_gate=patch.object(compilation_job, 'verify_completed_output', return_value=12.5)
        self.output_gate.start()
    def tearDown(self): self.output_gate.stop(); self.tmp.cleanup()
    def test_resolution_and_missing_attention(self):
        with patch.object(compilation_job, 'read_json', side_effect=[json.loads(self.state.read_text()), {'approved_intro_mp4':str(self.intro), 'approved_outro_mp4':str(self.outro)}]), patch.object(compilation_job.compile_videos, 'duration', return_value=2): s=compilation_job.plan(self.payload)
        self.assertEqual(s['state'],'needs_attention'); self.assertEqual(len(s['missing_episodes']),1)
        m=json.loads((self.root/'out/t1/manifest.json').read_text()); self.assertEqual(len(m['parts']),1); self.assertIsNone(m['parts'][0]['intro']); self.assertIsNone(m['parts'][0]['outro'])
    def test_plan_status_idempotent(self):
        with patch.object(compilation_job, 'read_json', side_effect=[json.loads(self.state.read_text()), {'approved_intro_mp4':str(self.intro), 'approved_outro_mp4':str(self.outro)}, json.loads(self.state.read_text()), {'approved_intro_mp4':str(self.intro), 'approved_outro_mp4':str(self.outro)}]), patch.object(compilation_job.compile_videos, 'duration', return_value=2): a=compilation_job.plan(self.payload); b=compilation_job.plan(self.payload)
        self.assertEqual(a,b); self.assertEqual(compilation_job.load(self.payload),b)

    def test_plan_copies_manifest_next_to_state_and_includes_series_id(self):
        payload={**self.payload, 'series_id':'s'}
        with patch.object(compilation_job, 'read_json', side_effect=[json.loads(self.state.read_text()), {'approved_intro_mp4':str(self.intro), 'approved_outro_mp4':str(self.outro)}]), patch.object(compilation_job.compile_videos, 'duration', return_value=2):
            status=compilation_job.plan(payload)
        disk_manifest=self.root/'out/t1/manifest.json'
        state_manifest=self.root/'compilations/t1.json'
        self.assertEqual(status['manifest'], str(disk_manifest.resolve()))
        self.assertEqual(status['state_manifest'], str(state_manifest.resolve()))
        self.assertEqual(json.loads(disk_manifest.read_text()), json.loads(state_manifest.read_text()))
        self.assertEqual(json.loads(state_manifest.read_text())['series_id'], 's')
    def test_plan_runs_detection_persists_results_and_requires_all_high_confidence(self):
        payload={**self.payload, 'selector':'list:1', 'branding':{'blur_logo':True}}
        detection={'state':'detected','sampled_frame_previews':['/tmp/preview-1.png'],'diagnostics':{'static_edge_ratio':.95},'regions':[{'label':'bilibili_logo','x':1,'y':2,'width':30,'height':12,'start':0,'end':10,'confidence':.95,'blur':True,'replacement':False,'confirmed':False}]}
        with patch.object(compilation_job, 'read_json', side_effect=[json.loads(self.state.read_text()), {'approved_intro_mp4':str(self.intro), 'approved_outro_mp4':str(self.outro)}]), patch.object(compilation_job.compile_videos, 'duration', return_value=2), patch.object(compilation_job, 'run_overlay_detection', return_value=detection): status=compilation_job.plan(payload)
        manifest=json.loads((self.root/'out/t1/manifest.json').read_text())
        persisted=json.loads((self.root/'compilations/t1.json').read_text())
        self.assertEqual('queued', status['state'])
        self.assertEqual(detection, manifest['overlay_detections']['1'])
        self.assertEqual(manifest['overlay_detections'], persisted['overlay_detections'])
        self.assertEqual(detection, status['overlay_detections']['1'])
        self.assertEqual('bilibili_logo', manifest['overlay_regions'][0]['label'])

        low={**detection, 'state':'needs_attention', 'regions':[dict(detection['regions'][0], confidence=.3)]}
        with patch.object(compilation_job, 'read_json', side_effect=[json.loads(self.state.read_text()), {'approved_intro_mp4':str(self.intro), 'approved_outro_mp4':str(self.outro)}]), patch.object(compilation_job.compile_videos, 'duration', return_value=2), patch.object(compilation_job, 'run_overlay_detection', return_value=low): status=compilation_job.plan({**payload, 'compilation_id':'low'})
        self.assertEqual('needs_attention', status['state'])
        self.assertIn('overlay detection', status['parts'][0]['error'])

    def test_bilibili_platform_profile_plans_full_block_without_explicit_regions(self):
        state={'series':[{'series_id':'s','platform':'bilibili','episodes':[{'episode_number':1,'duration':8,'last_output_dir':str(self.root/'ep1')}]}]}
        payload={**self.payload, 'series_id':'s', 'selector':'list:1', 'branding':{'blur_logo':True,'blur_title':True,'replace_logo':True}}
        detection={'state':'detected','sampled_frame_previews':['/tmp/preview-1.png'],'previews':['/tmp/preview-1.png'], 'diagnostics':{'profile':'bilibili_top_left_block'}, 'regions':[{'label':'bilibili_top_left_block','x':4,'y':4,'width':57,'height':14,'start':0,'end':10,'confidence':.99,'blur':True,'replacement':True,'confirmed':True}]}
        with patch.object(compilation_job, 'read_json', side_effect=[state, {'approved_intro_mp4':str(self.intro), 'approved_outro_mp4':str(self.outro)}]), patch.object(compilation_job.compile_videos, 'duration', return_value=2), patch.object(compilation_job, 'run_overlay_detection', return_value=detection) as detector:
            status=compilation_job.plan(payload)
        manifest=json.loads((self.root/'out/t1/manifest.json').read_text())
        self.assertEqual('queued', status['state'])
        self.assertEqual('bilibili_top_left_block', manifest['overlay_profile']['name'])
        self.assertEqual('series_platform', manifest['overlay_profile']['source'])
        self.assertEqual(manifest['overlay_profile'], status['overlay_profile'])
        self.assertTrue(manifest['overlay_regions'][0]['blur'])
        self.assertTrue(manifest['overlay_regions'][0]['replacement'])
        self.assertEqual('bilibili_top_left_block', detector.call_args.kwargs['profile'])
        self.assertTrue(detector.call_args.kwargs['replacement'])

    def test_unknown_profile_and_failed_detection_remain_needs_attention(self):
        payload={**self.payload, 'series_id':'s', 'selector':'list:1', 'branding':{'profile':'untrusted','blur_logo':True}}
        with patch.object(compilation_job, 'read_json', side_effect=[json.loads(self.state.read_text()), {'approved_intro_mp4':str(self.intro), 'approved_outro_mp4':str(self.outro)}]), patch.object(compilation_job.compile_videos, 'duration', return_value=2), patch.object(compilation_job, 'run_overlay_detection', return_value={'state':'needs_attention','regions':[],'diagnostics':{'reason':'no evidence'}}) as detector:
            status=compilation_job.plan(payload)
        self.assertEqual('needs_attention', status['state'])
        self.assertIsNone(detector.call_args.kwargs['profile'])

    def test_profile_replacement_circle_is_centered_over_the_full_block(self):
        region={'label':'bilibili_top_left_block','x':29,'y':27,'width':120,'height':60,'start':0,'end':10,'confidence':.99,'blur':True,'replacement':True,'confirmed':True}
        filt, _ = build_filter([region])
        self.assertIn('scale=120:60', filt)
        self.assertIn('overlay=29:27', filt)
        self.assertIn('W/2', filt)
        self.assertIn('H/2', filt)

    def test_needs_attention_detection_never_encodes(self):
        root = self.root/'out'/'t1'; root.mkdir(parents=True)
        part = {'part':1,'episodes':[{'episode_number':1,'path':'unused'}]}
        (root/'manifest.json').write_text(json.dumps({'branding':{'blur_logo':True},'overlay_detections':{'1':{'state':'needs_attention','sampled_frame_previews':['preview.pgm'],'diagnostics':{'reason':'weak evidence'},'regions':[]}},'overlay_regions':[],'parts':[part]}))
        (root/'status.json').write_text(json.dumps({'state':'needs_attention','parts':[{'part':1,'state':'needs_attention'}]}))
        with patch('compilation_job.subprocess.run') as run_mock:
            result=compilation_job.run(self.payload)
        run_mock.assert_not_called()
        self.assertEqual('needs_attention', result['state'])
    def test_cancel_does_not_kill_untracked(self):
        with patch.object(compilation_job, 'read_json', side_effect=[json.loads(self.state.read_text()), {'approved_intro_mp4':str(self.intro), 'approved_outro_mp4':str(self.outro)}]), patch.object(compilation_job.compile_videos, 'duration', return_value=2): compilation_job.plan(self.payload)
        with patch('compilation_job.os.killpg') as killpg:
            s=compilation_job.cancel(self.payload); killpg.assert_not_called(); self.assertEqual(s['state'],'canceled')

    def test_enqueue_starts_detached_execute_worker_and_tracks_pid(self):
        root = self.root/'out'/'t1'; root.mkdir(parents=True)
        (root/'status.json').write_text(json.dumps({'state':'queued','parts':[{'part':1,'state':'queued'}],'worker_pid':None}))
        with patch('compilation_job.subprocess.Popen', return_value=type('Proc', (), {'pid':4321})()) as popen:
            status=compilation_job.enqueue(self.payload, resume=False)
        self.assertEqual(status['state'], 'queued')
        self.assertEqual(status['worker_pid'], 4321)
        command=popen.call_args.args[0]
        self.assertEqual(command[2], 'execute')
        self.assertIn('--payload', command)
        self.assertTrue(popen.call_args.kwargs['start_new_session'])

    def test_enqueue_does_not_duplicate_a_live_tracked_worker(self):
        root = self.root/'out'/'t1'; root.mkdir(parents=True)
        (root/'status.json').write_text(json.dumps({'state':'processing','parts':[{'part':1,'state':'processing'}],'worker_pid':4321}))
        with patch('compilation_job.os.kill') as kill, patch('compilation_job.os.getpgid', return_value=4321), patch('compilation_job.subprocess.Popen') as popen:
            status=compilation_job.enqueue(self.payload, resume=True)
        kill.assert_called_once_with(4321, 0)
        popen.assert_not_called()
        self.assertEqual(status['worker_pid'], 4321)

    def test_cancel_terminates_only_live_tracked_worker_group(self):
        root = self.root/'out'/'t1'; root.mkdir(parents=True)
        (root/'status.json').write_text(json.dumps({'state':'processing','parts':[{'part':1,'state':'processing'},{'part':2,'state':'completed'}],'worker_pid':4321}))
        with patch('compilation_job.os.kill', return_value=None), patch('compilation_job.os.getpgid', return_value=4321), patch('compilation_job.os.killpg') as killpg:
            status=compilation_job.cancel(self.payload)
        killpg.assert_called_once_with(4321, compilation_job.signal.SIGTERM)
        self.assertEqual(status['state'], 'canceled')
        self.assertIsNone(status['worker_pid'])
        self.assertEqual(status['parts'][0]['state'], 'canceled')
        self.assertEqual(status['parts'][1]['state'], 'completed')

    def test_execute_clears_its_own_tracked_worker_pid(self):
        root = self.root/'out'/'t1'; root.mkdir(parents=True)
        (root/'status.json').write_text(json.dumps({'state':'processing','parts':[],'worker_pid':4321}))
        with patch('compilation_job.os.getpid', return_value=4321), patch('compilation_job.run', return_value={'state':'completed'}) as run_mock:
            compilation_job.execute(self.payload, resume=True)
        run_mock.assert_called_once_with(self.payload, True)
        self.assertIsNone(compilation_job.load(self.payload)['worker_pid'])

    def test_run_compiles_each_part_with_its_own_manifest_and_output(self):
        root = self.root/'out'/'t1'; root.mkdir(parents=True)
        parts = [{'part': 1, 'episodes': [{'episode_number': 1}]}, {'part': 2, 'episodes': [{'episode_number': 2}]}]
        (root/'manifest.json').write_text(json.dumps({'max_seconds': 123, 'parts': parts}))
        (root/'status.json').write_text(json.dumps({'state':'queued','parts':[{'part':1,'state':'queued'},{'part':2,'state':'queued'}]}))
        calls=[]
        def compiler(cmd, **kwargs):
            calls.append(cmd)
            part_manifest=json.loads(Path(cmd[cmd.index('--manifest')+1]).read_text())
            self.assertEqual(len(part_manifest['parts']), 1)
            self.assertEqual(part_manifest['max_seconds'], 123)
            output=Path(cmd[cmd.index('--output-dir')+1])/'part-1.mp4'
            return type('Proc', (), {'stdout': json.dumps({'parts':[{'part':1,'output':str(output),'duration_seconds':12.5}]})})()
        with patch('compilation_job.subprocess.run', side_effect=compiler):
            result=compilation_job.run(self.payload)
        self.assertEqual(len(calls), 2)
        self.assertNotEqual(calls[0][calls[0].index('--manifest')+1], calls[1][calls[1].index('--manifest')+1])
        self.assertEqual(result['parts'][0]['duration'], 12.5)
        self.assertTrue(calls[0][calls[0].index('--output-dir')+1].endswith('/parts/part-1'))

    def test_completed_run_records_selected_episode_usage_idempotently(self):
        root = self.root/'out'/'t1'; root.mkdir(parents=True)
        original={'unknown_top':'keep','series':[{'series_id':'s','unknown_series':'keep','episodes':[
            {'episode_number':1,'unknown_episode':'one'}, {'episode_number':2}, {'episode_number':3}
        ]}]}
        self.state.write_text(json.dumps(original))
        parts=[{'part':1,'episodes':[{'episode_number':1},{'episode_number':2}]}]
        (root/'manifest.json').write_text(json.dumps({'compilation_id':'t1','series_id':'s','parts':parts}))
        (root/'status.json').write_text(json.dumps({'state':'queued','parts':[{'part':1,'state':'queued'}]}))
        compiler=type('Proc', (), {'stdout':json.dumps({'parts':[{'part':1,'output':'compiled.mp4','duration_seconds':3}]})})()
        with patch('compilation_job.subprocess.run', return_value=compiler):
            result=compilation_job.run(self.payload)
            result=compilation_job.run(self.payload)
        saved=json.loads(self.state.read_text())
        self.assertEqual(result['state'], 'completed')
        self.assertEqual(saved['unknown_top'], 'keep')
        self.assertEqual([ep['episode_number'] for ep in saved['series'][0]['episodes']], [1,2,3])
        self.assertEqual(saved['series'][0]['episodes'][0]['unknown_episode'], 'one')
        for episode in saved['series'][0]['episodes'][:2]:
            self.assertEqual(episode['compilations_used'], ['t1'])
            self.assertEqual(episode['compilation_outputs'], [{'compilation_id':'t1','part':1,'output':'compiled.mp4'}])
        self.assertNotIn('compilations_used', saved['series'][0]['episodes'][2])

    def test_failed_part_is_not_recorded_in_state(self):
        root = self.root/'out'/'t1'; root.mkdir(parents=True)
        parts=[{'part':1,'episodes':[{'episode_number':1}]}, {'part':2,'episodes':[{'episode_number':2}]}]
        (root/'manifest.json').write_text(json.dumps({'compilation_id':'t1','series_id':'s','parts':parts}))
        (root/'status.json').write_text(json.dumps({'state':'queued','parts':[{'part':1,'state':'queued'},{'part':2,'state':'queued'}]}))
        successful=type('Proc', (), {'stdout':json.dumps({'parts':[{'part':1,'output':'one.mp4'}]})})()
        with patch('compilation_job.subprocess.run', side_effect=[successful, RuntimeError('compile failed')]):
            result=compilation_job.run(self.payload)
        saved=json.loads(self.state.read_text())
        self.assertEqual(result['state'], 'error')
        self.assertNotIn('compilations_used', saved['series'][0]['episodes'][0])
        self.assertNotIn('compilations_used', saved['series'][0]['episodes'][1])

    def test_state_bookkeeping_failure_keeps_completed_media_needs_attention(self):
        root = self.root/'out'/'t1'; root.mkdir(parents=True)
        parts=[{'part':1,'episodes':[{'episode_number':1}]}]
        (root/'manifest.json').write_text(json.dumps({'compilation_id':'t1','series_id':'missing','parts':parts}))
        (root/'status.json').write_text(json.dumps({'state':'queued','parts':[{'part':1,'state':'queued'}]}))
        compiler=type('Proc', (), {'stdout':json.dumps({'parts':[{'part':1,'output':'compiled.mp4'}]})})()
        with patch('compilation_job.subprocess.run', return_value=compiler):
            result=compilation_job.run(self.payload)
        self.assertEqual(result['state'], 'needs_attention')
        self.assertEqual(result['parts'][0]['state'], 'completed')
        self.assertEqual(result['parts'][0]['output'], 'compiled.mp4')
        self.assertIn('state bookkeeping failed', result['state_update_error'])

    def test_enqueue_completed_job_returns_without_spawning(self):
        root = self.root/'out'/'t1'; root.mkdir(parents=True)
        (root/'status.json').write_text(json.dumps({'state':'completed','parts':[{'part':1,'state':'completed'}],'worker_pid':None}))
        with patch('compilation_job.subprocess.Popen') as popen:
            status=compilation_job.enqueue(self.payload)
        popen.assert_not_called()
        self.assertEqual(status['state'], 'completed')

    def test_enqueue_needs_attention_does_not_spawn(self):
        root = self.root/'out'/'t1'; root.mkdir(parents=True)
        (root/'status.json').write_text(json.dumps({'state':'needs_attention','parts':[{'part':1,'state':'needs_attention'}],'worker_pid':None}))
        with patch('compilation_job.subprocess.Popen') as popen:
            status=compilation_job.enqueue(self.payload)
        popen.assert_not_called()
        self.assertEqual(status['state'], 'needs_attention')
        self.assertIn('cannot start', status['error'])

    def test_run_and_resume_needs_attention_do_not_encode(self):
        root = self.root/'out'/'t1'; root.mkdir(parents=True)
        (root/'manifest.json').write_text(json.dumps({'parts':[{'part':1,'episodes':[{'episode_number':1}]}]}))
        (root/'status.json').write_text(json.dumps({'state':'needs_attention','parts':[{'part':1,'state':'needs_attention'}]}))
        with patch('compilation_job.subprocess.run') as runner:
            self.assertEqual('needs_attention', compilation_job.run(self.payload)['state'])
            self.assertEqual('needs_attention', compilation_job.run(self.payload, resume=True)['state'])
        runner.assert_not_called()

    def test_plan_rejects_unsupported_options_and_persists_supported_options(self):
        bad={**self.payload, 'order':'episode_number'}
        blocked = compilation_job.plan(bad)
        self.assertEqual('needs_attention', blocked['state'])
        self.assertIn('order', blocked['error'])
        payload={**self.payload, 'order':'source', 'split_episodes':False, 'include_intro':False, 'include_outro':False}
        with patch.object(compilation_job, 'read_json', side_effect=[json.loads(self.state.read_text()), {'approved_intro_mp4':str(self.intro), 'approved_outro_mp4':str(self.outro)}]), patch.object(compilation_job.compile_videos, 'duration') as duration:
            compilation_job.plan(payload)
        manifest=json.loads((self.root/'out/t1/manifest.json').read_text())
        self.assertEqual('source', manifest['order'])
        self.assertFalse(manifest['split_episodes'])
        self.assertFalse(manifest['include_intro'])
        self.assertFalse(manifest['include_outro'])
        duration.assert_not_called()

    def test_invalid_compiled_output_cannot_complete(self):
        self.output_gate.stop()
        root = self.root/'out'/'t1'; root.mkdir(parents=True)
        (root/'manifest.json').write_text(json.dumps({'parts':[{'part':1,'episodes':[{'episode_number':1}]}]}))
        (root/'status.json').write_text(json.dumps({'state':'queued','parts':[{'part':1,'state':'queued'}]}))
        compiler=type('Proc', (), {'stdout':json.dumps({'parts':[{'part':1,'output':str(root/'parts'/'part-1'/'part-1.mp4')} ]})})()
        with patch('compilation_job.subprocess.run', return_value=compiler):
            result=compilation_job.run(self.payload)
        self.assertEqual('error', result['state'])
        self.assertIn('missing', result['parts'][0]['error'])

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'ffmpeg/ffprobe required')
    def test_completion_gate_requires_a_decodable_positive_duration_video(self):
        self.output_gate.stop()
        valid = self.root/'compiled.mp4'
        subprocess.run([
            'ffmpeg', '-y', '-f', 'lavfi', '-i', 'testsrc2=size=16x16:rate=1',
            '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo', '-t', '1',
            '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(valid),
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        self.assertGreater(compilation_job.verify_completed_output(valid), 0)

        invalid = self.root/'not-a-video.mp4'
        invalid.write_bytes(b'not media')
        with self.assertRaises(ValueError):
            compilation_job.verify_completed_output(invalid)

    def test_plan_prefers_current_output_packs_asset_durations_and_exposes_preview(self):
        direct=self.root/'final_video_vi.mp4'; direct.write_bytes(b'x')
        state={'series':[{'episodes':[{'episode_number':1,'duration':8,'final_video_path':str(direct),'last_output_dir':str(self.root/'none')},{'episode_number':2,'duration':8,'last_output_dir':str(self.root/'ep1')}]}]}
        payload={**self.payload, 'voice':'vi-female', 'max_seconds':15}
        with patch.object(compilation_job, 'read_json', side_effect=[state, {'approved_intro_mp4':str(self.intro), 'approved_outro_mp4':str(self.outro)}]), patch.object(compilation_job.compile_videos, 'duration', side_effect=[2, 2]):
            status=compilation_job.plan(payload)
        manifest=json.loads((self.root/'out/t1/manifest.json').read_text())
        self.assertEqual(manifest['voice'],'vi-female')
        self.assertEqual([p['duration_seconds'] for p in manifest['parts']],[8,8])
        self.assertEqual(manifest['parts'][0]['episodes'][0]['path'],str(direct.resolve()))
        self.assertEqual(status['plan_preview']['parts'][0],{'part':1,'episode_numbers':[1],'duration_seconds':8})
        self.assertEqual(status['plan_preview']['missing_episode_numbers'],[])

    def test_plan_brand_clip_toggles_store_null_without_probing_disabled_assets(self):
        payload={**self.payload, 'branding':{'intro':False,'outro':False}}
        with patch.object(compilation_job, 'read_json', side_effect=[json.loads(self.state.read_text()), {'approved_intro_mp4':str(self.intro), 'approved_outro_mp4':str(self.outro)}]), patch.object(compilation_job.compile_videos, 'duration') as duration:
            compilation_job.plan(payload)
        part=json.loads((self.root/'out/t1/manifest.json').read_text())['parts'][0]
        self.assertIsNone(part['intro']); self.assertIsNone(part['outro']); duration.assert_not_called()

    def test_plan_explicit_branding_adds_one_intro_and_outro_per_part(self):
        second=self.root/'ep2'; second.mkdir(); (second/'final_video_vi.mp4').write_bytes(b'x')
        state={'series':[{'episodes':[{'episode_number':1,'duration':8,'last_output_dir':str(self.root/'ep1')},{'episode_number':2,'duration':8,'last_output_dir':str(second)}]}]}
        payload={**self.payload, 'max_seconds':12, 'branding':{'intro':True,'outro':True}}
        with patch.object(compilation_job, 'read_json', side_effect=[state, {'approved_intro_mp4':str(self.intro), 'approved_outro_mp4':str(self.outro)}]), patch.object(compilation_job.compile_videos, 'duration', side_effect=[2, 2]):
            compilation_job.plan(payload)
        parts=json.loads((self.root/'out/t1/manifest.json').read_text())['parts']
        self.assertEqual([[episode['episode_number'] for episode in part['episodes']] for part in parts], [[1], [2]])
        for part in parts:
            self.assertEqual(part['intro'], str(self.intro.resolve()))
            self.assertEqual(part['outro'], str(self.outro.resolve()))

    def test_resume_does_not_rerun_completed_part(self):
        root = self.root/'out'/'t1'; root.mkdir(parents=True)
        parts = [{'part': 1, 'episodes': [{'episode_number': 1}]}, {'part': 2, 'episodes': [{'episode_number': 2}]}]
        (root/'manifest.json').write_text(json.dumps({'parts': parts}))
        (root/'status.json').write_text(json.dumps({'state':'resume_after_fix','parts':[{'part':1,'state':'completed','output':'old'},{'part':2,'state':'error'}]}))
        with patch('compilation_job.subprocess.run', return_value=type('Proc', (), {'stdout': json.dumps({'parts':[{'part':1,'output':'new'}]})})()) as run_mock:
            result=compilation_job.run(self.payload, resume=True)
        run_mock.assert_called_once()
        self.assertEqual(result['parts'][0]['output'], 'old')
        self.assertEqual(result['parts'][1]['state'], 'completed')

    def test_branding_blurs_each_episode_before_compiling_and_records_proofs(self):
        root = self.root/'out'/'t1'; root.mkdir(parents=True)
        episode = self.root/'episode-1-final_video_vi.mp4'; episode.write_bytes(b'video')
        region = {'label':'watermark','x':4,'y':4,'width':20,'height':20,'start':0,'end':10,'confidence':0.9,'blur':True}
        (root/'manifest.json').write_text(json.dumps({'branding':{'blur_logo':True},'overlay_regions':[region],'parts':[{'part':1,'episodes':[{'episode_number':1,'path':str(episode)}]}]}))
        (root/'status.json').write_text(json.dumps({'state':'queued','parts':[{'part':1,'state':'queued'}]}))
        calls=[]
        def runner(cmd, **kwargs):
            calls.append(cmd)
            if str(compilation_job.BRAND) in cmd:
                output_dir=Path(cmd[cmd.index('--output-dir')+1]); output_dir.mkdir(parents=True, exist_ok=True)
                (output_dir/'branded.mp4').write_bytes(b'branded')
                (output_dir/'overlay_regions.json').write_text('[]'); (output_dir/'overlay_proof.json').write_text('{}')
                return type('Proc', (), {'stdout':json.dumps({'status':'executed'})})()
            part_manifest=json.loads(Path(cmd[cmd.index('--manifest')+1]).read_text())
            branded_path=Path(part_manifest['parts'][0]['episodes'][0]['path'])
            self.assertEqual(branded_path.name, 'final_video_vi.mp4')
            self.assertEqual(branded_path.resolve().name, 'branded.mp4')
            return type('Proc', (), {'stdout':json.dumps({'parts':[{'part':1,'output':'compiled.mp4','duration_seconds':3}]})})()
        with patch('compilation_job.subprocess.run', side_effect=runner): result=compilation_job.run(self.payload)
        brand_call=calls[0]
        self.assertIn('--execute', brand_call); self.assertIn('--regions', brand_call); self.assertNotIn('--logo', brand_call)
        self.assertEqual(result['parts'][0]['state'], 'completed')
        self.assertTrue(result['parts'][0]['branding_proofs'][0]['proof'].endswith('episode-1/overlay_proof.json'))
        self.assertIn('1', json.loads((root/'manifest.json').read_text())['branding_proofs'])

    def test_missing_or_invalid_brand_regions_needs_attention_without_compile(self):
        root = self.root/'out'/'t1'; root.mkdir(parents=True)
        part = {'part':1,'episodes':[{'episode_number':1,'path':'unused'}]}
        (root/'manifest.json').write_text(json.dumps({'branding':{'blur_title':True},'overlay_regions':None,'parts':[part]}))
        (root/'status.json').write_text(json.dumps({'state':'queued','parts':[{'part':1,'state':'queued'}]}))
        with patch('compilation_job.subprocess.run') as run_mock:
            result=compilation_job.run(self.payload)
        run_mock.assert_not_called()
        self.assertEqual(result['state'], 'needs_attention')
        self.assertEqual(result['parts'][0]['state'], 'needs_attention')
        self.assertIn('no automatic blur', result['parts'][0]['error'])

        (root/'manifest.json').write_text(json.dumps({'branding':{'blur_title':True},'overlay_regions':[{'bad':'region'}],'parts':[part]}))
        (root/'status.json').write_text(json.dumps({'state':'queued','parts':[{'part':1,'state':'queued'}]}))
        with patch('compilation_job.subprocess.run', side_effect=subprocess.CalledProcessError(2, ['brand'])) as run_mock:
            result=compilation_job.run(self.payload)
        run_mock.assert_not_called()
        self.assertEqual(result['parts'][0]['state'], 'needs_attention')
        self.assertIn('missing required fields', result['parts'][0]['error'])

if __name__=='__main__': unittest.main()
