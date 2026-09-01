from autodub.text import translate_common


def test_translation_checkpoint_writes_atomically(tmp_path, monkeypatch):
    calls = []

    def fake_save(data, path):
        calls.append((data, path))

    monkeypatch.setattr(translate_common, "save_json_atomic", fake_save)
    checkpoint = translate_common.TranslateCheckpoint(
        str(tmp_path / "translate_checkpoint.json"), "text_vi")

    checkpoint.put([{"id": 1, "text": "hello", "text_vi": "Xin chào"}])

    assert len(calls) == 1
    data, path = calls[0]
    assert path.endswith("translate_checkpoint.json")
    assert data["text_field"] == "text_vi"
    assert data["items"]["1"]["text"] == "Xin chào"
