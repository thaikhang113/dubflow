import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from brand_video import build_filter, validate_regions
from compile_videos import LIMIT, validate_part


class Tests(unittest.TestCase):
    def region(self, **kwargs):
        region = dict(label="x", x=1, y=2, width=10, height=10, start=0, end=2, confidence=.9, blur=True)
        region.update(kwargs)
        return region

    def test_low_confidence_and_bounds_fail_closed(self):
        with self.assertRaises(ValueError):
            validate_regions([self.region(confidence=.2)])
        with self.assertRaises(ValueError):
            validate_regions([self.region(x=-1)])
        with self.assertRaises(ValueError):
            validate_regions([self.region(width=10.5)])
        with self.assertRaises(ValueError):
            validate_regions([self.region(end=5)], media_width=20, media_height=20, media_duration=4)
        with self.assertRaises(ValueError):
            validate_regions([self.region(x=15)], media_width=20, media_height=20, media_duration=4)

    def test_documented_time_aliases_and_optional_label_normalize(self):
        region = self.region(label="", start_seconds=0, end_seconds=2)
        region.pop("start"); region.pop("end")
        normalized = validate_regions([region])
        self.assertEqual("blur", normalized[0]["label"])
        self.assertEqual(0.0, normalized[0]["start"])
        self.assertEqual(2.0, normalized[0]["end"])
        self.assertNotIn("start_seconds", normalized[0])

    def test_filters_chain_blur_replacement_blur(self):
        regions = [self.region(), self.region(blur=False, replacement=True), self.region(x=3)]
        filt, label = build_filter(regions)
        self.assertEqual(label, "v2")
        self.assertIn("[v0][stamp1]overlay", filt)
        self.assertIn("[v1]split=2", filt)
        self.assertIn("a='if(lte(", filt)
        self.assertIn("eof_action=pass:shortest=0", filt)

    def test_conceal_replacement_covers_the_full_region_before_centering_square_logo(self):
        region = self.region(x=29, y=27, width=346, height=81, blur=False, replacement=True, conceal=True)
        filt, label = build_filter([region])
        self.assertEqual(label, "v1")
        self.assertIn("color=c=0x0B1F3A@1:s=346x81,format=rgba[cover0]", filt)
        self.assertIn("[0:v][cover0]overlay=29:27:", filt)
        self.assertIn("scale=81:81:force_original_aspect_ratio=decrease", filt)
        self.assertIn("pad=81:81:(ow-iw)/2:(oh-ih)/2:color=black@0", filt)
        self.assertIn("[v0][stamp1]overlay=161.5:27:", filt)

    def test_non_conceal_replacement_retains_generic_scaling_and_position(self):
        region = self.region(x=29, y=27, width=346, height=81, blur=False, replacement=True)
        filt, label = build_filter([region])
        self.assertEqual(label, "v0")
        self.assertIn("scale=346:81,format=rgba", filt)
        self.assertIn("[0:v][stamp0]overlay=29:27:", filt)
        self.assertNotIn("[cover", filt)

    @patch("compile_videos.probe_media", return_value={"duration": 1, "width": 1, "height": 1, "fps": "1/1", "has_audio": True})
    @patch("compile_videos.Path.is_file", return_value=True)
    def test_order_duplicate(self, *_):
        episode = lambda number: {"episode_number": number, "path": "final_video_vi.mp4"}
        with self.assertRaises(ValueError):
            validate_part({"intro": "i", "episodes": [episode(2), episode(1)], "outro": "o"})
        with self.assertRaises(ValueError):
            validate_part({"intro": "i", "episodes": [episode(1), episode(1)], "outro": "o"})

    @patch("compile_videos.probe_media", return_value={"duration": 2000, "width": 1, "height": 1, "fps": "1/1", "has_audio": True})
    @patch("compile_videos.Path.is_file", return_value=True)
    def test_guard(self, *_):
        episode = {"episode_number": 1, "path": "final_video_vi.mp4"}
        with self.assertRaises(ValueError):
            validate_part({"intro": "i", "episodes": [episode, {"episode_number": 2, "path": "final_video_vi.mp4"}], "outro": "o"})

    @patch("compile_videos.probe_media", return_value={"duration": 10, "width": 1, "height": 1, "fps": "1/1", "has_audio": True})
    @patch("compile_videos.Path.is_file", return_value=True)
    def test_no_intro_or_outro_and_custom_limit(self, *_):
        plan = validate_part({"episodes": [{"episode_number": 1, "path": "final_video_vi.mp4"}]}, 10)
        self.assertEqual(plan["inputs"], ["final_video_vi.mp4"])
        self.assertFalse(plan["intro_included"])
        self.assertFalse(plan["outro_included"])
        with self.assertRaises(ValueError):
            validate_part({"episodes": [{"episode_number": 1, "path": "final_video_vi.mp4"}, {"episode_number": 2, "path": "final_video_vi.mp4"}]}, 15)

    @patch("compile_videos.probe_media", return_value={"duration": 1, "width": 1, "height": 1, "fps": "1/1", "has_audio": True})
    @patch("compile_videos.Path.is_file", return_value=True)
    def test_brand_clips_wrap_all_episodes_once_per_part(self, *_):
        episodes = [{"episode_number": 1, "path": "final_video_vi.mp4"}, {"episode_number": 2, "path": "final_video_vi.mp4"}]
        plan = validate_part({"intro": "intro.mp4", "episodes": episodes, "outro": "outro.mp4"})
        self.assertEqual(plan["inputs"], ["intro.mp4", "final_video_vi.mp4", "final_video_vi.mp4", "outro.mp4"])

    @patch("compile_videos.probe_media", return_value={"duration": 1, "width": 1, "height": 1, "fps": "1/1", "has_audio": False})
    @patch("compile_videos.Path.is_file", return_value=True)
    def test_episode_without_audio_is_rejected(self, *_):
        with self.assertRaisesRegex(ValueError, "audio stream"):
            validate_part({"episodes": [{"episode_number": 1, "path": "final_video_vi.mp4"}]})

    @patch("compile_videos.probe_media", return_value={"duration": 20, "width": 1, "height": 1, "fps": "1/1", "has_audio": True})
    @patch("compile_videos.Path.is_file", return_value=True)
    def test_oversized_single_episode_is_emitted_alone(self, *_):
        plan = validate_part({"intro": "i", "episodes": [{"episode_number": 1, "path": "final_video_vi.mp4"}], "outro": "o"}, 10)
        self.assertEqual(plan["inputs"], ["final_video_vi.mp4"])
        self.assertFalse(plan["intro_included"])
        self.assertFalse(plan["outro_included"])
        self.assertIn("emitted alone", plan["warning"])

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg/ffprobe required")
    def test_three_input_compile_is_decodable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            intro, episode, outro = root / "intro.mp4", root / "final_video_vi.mp4", root / "outro.mp4"
            for target, size, rate in ((intro, "64x48", "24"), (episode, "80x60", "30"), (outro, "48x48", "15")):
                subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"testsrc2=size={size}:rate={rate}", "-f", "lavfi", "-i", "sine=frequency=1000:sample_rate=44100", "-t", "0.25", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(target)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            manifest = root / "manifest.json"
            # Intro/outro deliberately omit audio: normalization must supply silence.
            for target in (intro, outro):
                subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc2=size=64x48:rate=24", "-t", "0.25", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(target)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            manifest.write_text(json.dumps({"max_seconds": 30, "parts": [{"intro": str(intro), "episodes": [{"episode_number": 1, "path": str(episode)}], "outro": str(outro)}]}), encoding="utf-8")
            output_dir = root / "out"
            result = subprocess.run(["python3", str(Path(__file__).with_name("compile_videos.py")), "--manifest", str(manifest), "--output-dir", str(output_dir), "--execute"], check=True, capture_output=True, text=True)
            self.assertIn("part-1.mp4", result.stdout)
            report = json.loads(result.stdout)
            self.assertEqual(report["limit_seconds"], 30)
            self.assertEqual(report["parts"][0]["episode_numbers"], [1])
            self.assertTrue(report["parts"][0]["intro_included"])
            self.assertTrue(report["parts"][0]["outro_included"])
            self.assertIsNone(report["parts"][0]["warning"])
            output = output_dir / "part-1.mp4"
            self.assertTrue(output.is_file())
            subprocess.run(["ffmpeg", "-v", "error", "-i", str(output), "-f", "null", "-"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            media = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name,width,height,pix_fmt,avg_frame_rate", "-of", "json", str(output)], text=True))
            video = next(stream for stream in media["streams"] if stream["codec_type"] == "video")
            audio = next(stream for stream in media["streams"] if stream["codec_type"] == "audio")
            self.assertEqual((video["width"], video["height"], video["pix_fmt"]), (80, 60, "yuv420p"))
            self.assertEqual(video["avg_frame_rate"], "30/1")
            self.assertEqual(audio["codec_name"], "aac")
            self.assertLessEqual(float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(output)], text=True)), LIMIT)


if __name__ == "__main__":
    unittest.main()
