import os
import wave
from unittest import mock

from autodub.config import Settings
from autodub.speech import paraformer_transcriber


def _wav(path, rate=48000, channels=2):
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(b"\0\0" * channels * rate)

def test_paraformer_normalizes_non_16k_input_and_cleans_temp(tmp_path):
    source = tmp_path / "source.wav"
    normalized = tmp_path / "source.wav.paraformer_16k_mono.wav"
    _wav(source)

    class Proc:
        returncode = 0
        stdout = [
            '{"seg":true,"start":0,"end":1,"text":"你好"}\n',
            '{"done":true}\n',
        ]
        stderr = []

        def wait(self, timeout=None):
            return 0

        def poll(self):
            return 0

        def kill(self):
            pass

    def fake_run(cmd, **kwargs):
        assert cmd[cmd.index("-ar") + 1] == "16000"
        assert cmd[cmd.index("-ac") + 1] == "1"
        with open(normalized, "wb") as f:
            f.write(b"wav")
        return mock.Mock(returncode=0, stderr="")

    class Stream:
        def __iter__(self):
            return iter(self.lines)

        def close(self):
            pass

    proc = Proc()
    proc.stdout = Stream()
    proc.stdout.lines = Proc.stdout
    proc.stderr = Stream()
    proc.stderr.lines = []

    with mock.patch.object(paraformer_transcriber.subprocess, "run",
                           side_effect=fake_run), \
         mock.patch.object(paraformer_transcriber.subprocess, "Popen",
                           return_value=proc), \
         mock.patch.object(Settings, "asr_venv_python_path",
                           return_value="python"), \
         mock.patch.object(Settings, "paraformer_model_dir_path",
                           return_value="model"):
        result = paraformer_transcriber.transcribe_paraformer(
            str(source), Settings())

    assert result[0]["text"] == "你好"
    assert not os.path.exists(normalized)
