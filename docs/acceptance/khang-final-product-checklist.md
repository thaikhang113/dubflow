# Khang Final Product Acceptance

## Status

- [x] Bilibili URL query/fragment normalization
- [x] ASR/OCR transcript selection regression
- [x] OCR zero-result diagnostic retry
- [x] Structured transcript and TTS error codes
- [x] Ngoc Huyen alias wiring
- [x] Python compile and Bash syntax checks on checkout
- [ ] Revoke exposed AI33 key
- [ ] Load replacement key through host-only `EnvironmentFile`
- [ ] Real AI33 Ngoc Huyen synthesis
- [ ] Real Ollama/9Router translation
- [ ] Real Chrome CDP Bilibili download
- [ ] Final `final_video_vi.mp4` with all quality gates
- [ ] Series queue/plan/compile E2E
- [ ] HyperFrames book-video E2E

## Offline Verification

Run from repository root:

```bash
PYTHONIOENCODING=utf-8 python3 skills/douyin-vietnamese-dubber/test_voice_registry.py
PYTHONIOENCODING=utf-8 python3 skills/series-tracker/test_series_tracker_state.py
PYTHONIOENCODING=utf-8 python3 skills/bilibili-vietnamese-dubber/test_url_normalization.py
PYTHONIOENCODING=utf-8 python3 skills/douyin-vietnamese-dubber/test_transcript_quality.py
PYTHONIOENCODING=utf-8 python3 skills/douyin-vietnamese-dubber/test_ocr_diagnostic_retry.py
PYTHONIOENCODING=utf-8 python3 skills/douyin-vietnamese-dubber/test_transcript_source_separation.py
PYTHONIOENCODING=utf-8 python3 skills/douyin-vietnamese-dubber/test_translation_cjk_gate.py
PYTHONIOENCODING=utf-8 python3 skills/douyin-vietnamese-dubber/test_exact_sync_policy.py
PYTHONIOENCODING=utf-8 python3 skills/douyin-vietnamese-dubber/test_final_mix_quality.py
PYTHONIOENCODING=utf-8 python3 skills/douyin-vietnamese-dubber/test_voice_sync_overhang.py
python3 -m compileall -q skills
find skills -name '*.sh' -print0 | xargs -0 bash -n
```

## Host Acceptance

1. Revoke old AI33 key.
2. Create replacement secret outside Git with mode `0600`.
3. Start only Khang test service with `EnvironmentFile`.
4. Run voice probe with `Ngoc Huyen`.
5. Process one approved Bilibili URL containing `?vd_source=...`.
6. Verify transcript, translation, TTS, audio, subtitle, and final-video reports.
7. Verify `final_video_vi.mp4` exists and plays.
8. Run series refresh, queue, compilation plan, compilation run.
9. Run HyperFrames book-video only when runtime reports available.

Do not record API keys, cookies, signed CDN URLs, or browser profile data in this file.
