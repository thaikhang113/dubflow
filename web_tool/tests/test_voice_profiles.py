import io
import tempfile
import unittest
import wave
from pathlib import Path

from web_tool.voice_profiles import save_profile


def wav_bytes(seconds=4, sample_rate=48000):
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes((b"\x00\x10" * sample_rate * seconds))
    return output.getvalue()


class VoiceProfileTests(unittest.TestCase):
    def test_save_profile_normalizes_valid_wav(self):
        with tempfile.TemporaryDirectory() as root:
            profile = save_profile(
                Path(root),
                "Narrator",
                "sample.wav",
                wav_bytes(),
            )
            reference = Path(profile["reference_audio"])
            self.assertTrue(reference.is_file())
            self.assertEqual("Narrator", profile["name"])
            self.assertEqual(48000, profile["sample_rate"])
            self.assertEqual(1, profile["channels"])

    def test_rejects_sample_outside_three_to_eight_seconds(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(ValueError, "3 and 8 seconds"):
                save_profile(Path(root), "Short", "sample.wav", wav_bytes(2))


if __name__ == "__main__":
    unittest.main()
