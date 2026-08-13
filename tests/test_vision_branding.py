import json

from autodub.media.vision import detect_logo_region


def test_vision_failure_returns_none(monkeypatch):
    def fail(*args, **kwargs):
        raise OSError("offline")

    monkeypatch.setattr("autodub.media.vision.urlopen", fail)
    assert detect_logo_region(b"frame", "deepseek-vl") is None


def test_vision_accepts_only_normalized_logo_region(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({
                "response": '{"x":0.7,"y":0.05,"w":0.2,"h":0.1}'
            }).encode()

    monkeypatch.setattr("autodub.media.vision.urlopen", lambda *a, **k: Response())
    assert detect_logo_region(b"frame", "deepseek-vl") == {
        "x": 0.7, "y": 0.05, "w": 0.2, "h": 0.1,
    }
