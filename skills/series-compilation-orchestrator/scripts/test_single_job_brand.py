import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import single_job_brand


class SingleJobBrandTests(unittest.TestCase):
    def test_bilibili_region_covers_fixed_top_left_block(self):
        region = single_job_brand.bilibili_top_left_region(1920, 1080, 42.5)
        self.assertEqual(region["label"], "bilibili_top_left_block")
        self.assertEqual((region["x"], region["y"], region["width"], region["height"]), (29, 27, 346, 81))
        self.assertTrue(region["blur"])
        self.assertTrue(region["replacement"])
        self.assertTrue(region["conceal"])
        self.assertEqual((region["start"], region["end"]), (0.0, 42.5))

    def test_plan_adds_intro_and_outro_once_only_when_requested(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / "final_video_vi.mp4"
            logo = root / "logo.png"
            intro = root / "intro.mp4"
            outro = root / "outro.mp4"
            for path in (video, logo, intro, outro):
                path.touch()
            with patch.object(single_job_brand, "probe_media", return_value={"width": 1920, "height": 1080, "duration": 10.0, "has_audio": True}):
                plan = single_job_brand.plan(video, logo, intro, outro, include_intro=True, include_outro=True)
            self.assertEqual(plan["inputs"], [str(intro), str(video), str(outro)])
            self.assertTrue(plan["intro_included"])
            self.assertTrue(plan["outro_included"])
            self.assertEqual(len(plan["regions"]), 1)
            self.assertEqual(plan["regions"][0]["label"], "bilibili_top_left_block")
            self.assertTrue(plan["regions"][0]["conceal"])

            with patch.object(single_job_brand, "probe_media", return_value={"width": 1920, "height": 1080, "duration": 10.0, "has_audio": True}):
                plain = single_job_brand.plan(video, logo, intro, outro, include_intro=False, include_outro=False)
            self.assertEqual(plain["inputs"], [str(video)])
            self.assertFalse(plain["intro_included"])
            self.assertFalse(plain["outro_included"])

    def test_invalid_clip_flag_is_rejected_before_execution(self):
        with self.assertRaisesRegex(ValueError, "include_intro"):
            single_job_brand.parse_bool("maybe", "include_intro")

    def test_cli_accepts_managed_logo_override(self):
        source = Path(single_job_brand.__file__).read_text(encoding="utf-8")
        self.assertIn('parser.add_argument("--logo")', source)
        self.assertIn('Path(args.logo) if args.logo else resolve(assets["logo"])', source)

    def test_decode_media_requires_video_and_audio_to_decode(self):
        with patch.object(single_job_brand.subprocess, "run") as run:
            single_job_brand.decode_media("branded.mp4")
        self.assertEqual(run.call_args.args[0][:4], ["ffmpeg", "-v", "error", "-i"])

    def test_in_place_input_is_preserved_when_branding_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video, logo = root / "final_video_vi.mp4", root / "logo.png"
            video.write_bytes(b"unbranded-original")
            logo.touch()
            with patch.object(single_job_brand, "probe_media", return_value={"width": 640, "height": 360, "duration": 1.0, "has_audio": True}), patch.object(single_job_brand.subprocess, "run", side_effect=subprocess.CalledProcessError(1, ["brand"])):
                with self.assertRaises(subprocess.CalledProcessError):
                    single_job_brand.execute(video, video, logo, None, None, False, False)
            self.assertEqual(video.read_bytes(), b"unbranded-original")

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg/ffprobe required")
    def test_execute_blurs_replaces_region_and_wraps_single_job_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video, intro, outro, logo, output = (root / "episode.mp4", root / "intro.mp4", root / "outro.mp4", root / "logo.png", root / "final_video_vi.mp4")
            def make_video(path, color):
                subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"color={color}:size=640x360:rate=24", "-f", "lavfi", "-i", "sine=frequency=500:sample_rate=48000", "-t", "0.3", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(path)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            make_video(video, "red")
            make_video(intro, "blue")
            make_video(outro, "green")
            subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=yellow:size=32x32", "-frames:v", "1", str(logo)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            proof = single_job_brand.execute(video, video, logo, intro, outro, True, True)
            self.assertEqual(proof["inputs"], [str(intro), str(video), str(outro)])
            self.assertTrue(video.is_file())
            duration = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(video)], text=True))
            self.assertGreater(duration, 0.8)
            subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            self.assertTrue((root / "bilibili_branding_proof.json").is_file())


if __name__ == "__main__":
    unittest.main()
