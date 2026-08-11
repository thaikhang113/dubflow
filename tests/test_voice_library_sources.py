from autodub.speech.tts.voices import Voice
from autodub_gui.pages.voice_library import filter_source


def test_clone_source_filter_returns_only_custom_voices():
    voices = [
        Voice("Preset", source="library"),
        Voice("Clone", source="custom"),
        Voice("Cap", source="capcut"),
    ]
    assert [v.name for v in filter_source(voices, "clone")] == ["Clone"]
