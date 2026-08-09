#!/usr/bin/env python3
import importlib.util
import sys
import types
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parent / "scripts" / "bilibili_cdp.py"


def load_module():
    playwright = types.ModuleType("playwright")
    async_api = types.ModuleType("playwright.async_api")
    async_api.async_playwright = object()
    sys.modules.setdefault("playwright", playwright)
    sys.modules.setdefault("playwright.async_api", async_api)
    spec = importlib.util.spec_from_file_location("bilibili_cdp_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BilibiliUrlNormalizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def test_strips_tracking_query_and_fragment(self):
        self.assertEqual(
            self.module.normalize_video_url(
                "https://www.bilibili.com/video/BV1example?vd_source=abc#reply"
            ),
            "https://www.bilibili.com/video/BV1example",
        )

    def test_normalizes_mobile_host(self):
        self.assertEqual(
            self.module.normalize_video_url("https://m.bilibili.com/video/BV1example/"),
            "https://www.bilibili.com/video/BV1example",
        )

    def test_rejects_non_bilibili_host(self):
        self.assertEqual(
            self.module.normalize_video_url("https://evil.example/video/BV1example"),
            "",
        )

    def test_rejects_invalid_port(self):
        self.assertEqual(
            self.module.normalize_video_url("https://www.bilibili.com:bad/video/BV1example"),
            "",
        )

    def test_wrapper_emits_child_job_status_on_failure(self):
        run_sh = SCRIPT.parent.parent / "run.sh"
        source = run_sh.read_text(encoding="utf-8")
        self.assertIn("emit_latest_job_failure", source)
        self.assertIn("OPENCLAW_JOB_STATUS_JSON=", source)
        self.assertIn('if [[ "$child_status" -ne 0 ]]', source)

    def test_wrapper_only_requires_hdd_for_hdd_output(self):
        run_sh = SCRIPT.parent.parent / "run.sh"
        source = run_sh.read_text(encoding="utf-8")
        self.assertIn('if [[ "$BASE_ROOT" == /mnt/hdd500/* ]]', source)

    def test_wrapper_defaults_to_repo_local_dependencies(self):
        run_sh = SCRIPT.parent.parent / "run.sh"
        source = run_sh.read_text(encoding="utf-8")
        self.assertIn(
            'DOUYIN_PIPELINE="${DOUYIN_PIPELINE:-$SKILL_ROOT/douyin-vietnamese-dubber/run.sh}"',
            source,
        )
        self.assertIn(
            'SINGLE_JOB_BRAND_SCRIPT="${SINGLE_JOB_BRAND_SCRIPT:-$SKILL_ROOT/series-compilation-orchestrator/scripts/single_job_brand.py}"',
            source,
        )

    def test_wrapper_reuses_resume_video_without_downloading_again(self):
        run_sh = SCRIPT.parent.parent / 'run.sh'
        source = run_sh.read_text(encoding='utf-8')
        self.assertIn('OPENCLAW_RESUME_JOB_DIR', source)
        self.assertIn('Resume: dùng lại video Bilibili đã tải', source)

    def test_child_pipeline_publishes_current_job_before_first_status(self):
        run_sh = SCRIPT.parents[2] / "douyin-vietnamese-dubber" / "run.sh"
        source = run_sh.read_text(encoding="utf-8")
        mkdir_at = source.index('mkdir -p "$OUT_DIR"')
        latest_at = source.index('printf \'%s\\n\' "$OUT_DIR" > "$LATEST_OUTPUT_TXT"')
        queued_at = source.index('status_update "queued" "3"')
        self.assertLess(mkdir_at, latest_at)
        self.assertLess(latest_at, queued_at)

    def test_wrapper_always_brands_before_final_handoff(self):
        run_sh = SCRIPT.parent.parent / "run.sh"
        source = run_sh.read_text(encoding="utf-8")

        self.assertNotIn('BILIBILI_BRANDING="${BILIBILI_BRANDING:-0}"', source)
        self.assertNotIn('if [[ "$BILIBILI_BRANDING" == "1" ]]', source)
        self.assertIn(
            'ORGANIZE_OUTPUT=0 AUTO_TELEGRAM_RESULT=0 bash "$DOUYIN_PIPELINE" "$VIDEO_FILE"',
            source,
        )
        brand_at = source.index('python3 "$SINGLE_JOB_BRAND_SCRIPT"')
        organize_at = source.index('python3 "$ORGANIZE_SCRIPT"')
        self.assertLess(brand_at, organize_at)
        self.assertIn('--include-intro "$BILIBILI_BRAND_INCLUDE_INTRO"', source)
        self.assertIn('--include-outro "$BILIBILI_BRAND_INCLUDE_OUTRO"', source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
