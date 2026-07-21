import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import detect_overlays


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'ffmpeg/ffprobe required')
class TestDetectOverlays(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def video(self, name, watermark=False):
        output = self.root / name
        filters = 'testsrc2=size=320x180:rate=8' if watermark else 'color=c=gray:size=320x180:rate=8'
        if watermark:
            # This deliberately has a changing background: only the top-left mark is static.
            filters += ",drawbox=x=12:y=10:w=82:h=28:color=white@1:t=3,drawbox=x=22:y=19:w=18:h=8:color=white@1:t=fill"
        subprocess.run(['ffmpeg', '-y', '-f', 'lavfi', '-i', filters, '-t', '2', '-pix_fmt', 'yuv420p', str(output)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        return output

    def test_static_top_left_watermark_is_detected_from_sampled_evidence(self):
        result = detect_overlays.detect(self.video('marked.mp4', True), self.root / 'detect')
        self.assertEqual('detected', result['state'])
        region = result['regions'][0]
        self.assertEqual('bilibili_logo', region['label'])
        self.assertGreaterEqual(region['confidence'], .8)
        self.assertTrue(region['blur'])
        self.assertFalse(region['confirmed'])
        self.assertGreater(region['width'], 10)
        self.assertGreaterEqual(len(result['previews']), 3)
        self.assertTrue(all(Path(path).is_file() for path in result['previews']))
        self.assertTrue(all(Path(path).suffix == '.png' and Path(path).read_bytes().startswith(b'\x89PNG\r\n\x1a\n') for path in result['previews']))
        self.assertGreater(result['diagnostics']['static_edge_ratio'], .8)

    def test_trusted_bilibili_block_scales_and_exposes_png_previews(self):
        result = detect_overlays.detect(
            self.video('bilibili.mp4'), self.root / 'detect',
            profile='bilibili_top_left_block', replacement=True,
        )
        self.assertEqual('detected', result['state'])
        self.assertEqual('bilibili_top_left_block', result['diagnostics']['profile'])
        self.assertEqual(1, len(result['regions']))
        region = result['regions'][0]
        self.assertEqual('bilibili_top_left_block', region['label'])
        self.assertEqual((5, 4, 57, 14), (region['x'], region['y'], region['width'], region['height']))
        self.assertEqual(.99, region['confidence'])
        self.assertTrue(region['blur'])
        self.assertTrue(region['replacement'])
        self.assertTrue(region['confirmed'])
        self.assertTrue(all(Path(path).suffix == '.png' for path in result['previews']))
        self.assertTrue(all(Path(path).read_bytes().startswith(b'\x89PNG\r\n\x1a\n') for path in result['sampled_frame_previews']))

    def test_no_static_mark_fails_closed_with_previews(self):
        result = detect_overlays.detect(self.video('plain.mp4'), self.root / 'detect')
        self.assertEqual('needs_attention', result['state'])
        self.assertEqual([], result['regions'])
        self.assertGreaterEqual(len(result['previews']), 3)
        self.assertIn('no stable top-left overlay', result['diagnostics']['reason'])

    def test_cli_emits_json_contract(self):
        video = self.video('cli.mp4', True)
        proc = subprocess.run(['python3', str(Path(detect_overlays.__file__)), '--input', str(video), '--output-dir', str(self.root / 'cli-out')], check=True, capture_output=True, text=True)
        result = json.loads(proc.stdout)
        self.assertEqual('detected', result['state'])
        self.assertIn('sampled_frame_previews', result)
        self.assertEqual(set(('label', 'x', 'y', 'width', 'height', 'start', 'end', 'confidence', 'blur', 'replacement', 'confirmed')), set(result['regions'][0]))


if __name__ == '__main__':
    unittest.main()
