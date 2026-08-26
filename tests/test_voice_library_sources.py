from autodub.speech.tts.voices import Voice
from autodub_gui.pages.voice_library import filter_source


def test_clone_source_filter_returns_only_custom_voices():
    voices = [
        Voice("Preset", source="library"),
        Voice("Clone", source="custom"),
        Voice("Cap", source="capcut"),
    ]
    assert [v.name for v in filter_source(voices, "clone")] == ["Clone"]


def test_capcut_only_catalog_opens_capcut_source_tab(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from autodub.config import Settings
    from autodub.speech.tts import voices as catalog
    from autodub_gui.pages.voice_library import VoiceLibraryTab

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(
        catalog,
        "catalog",
        lambda _settings: [Voice("Cap", source="capcut")],
    )

    panel = VoiceLibraryTab(lambda: Settings())
    assert panel._src_tab == 1
    assert [voice.name for voice in panel._filtered] == ["Cap"]

    panel.deleteLater()
    app.processEvents()


def test_loading_unknown_saved_voice_selects_available_voice(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from autodub.config import Settings
    from autodub.speech.tts import voices as catalog
    from autodub_gui.pages.voice_library import VoiceLibraryTab

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(
        catalog,
        "catalog",
        lambda _settings: [Voice("Cap", source="capcut")],
    )

    panel = VoiceLibraryTab(lambda: Settings())
    panel.load({"VIENEU_VOICE": "Missing", "VIENEU_STYLE": "tu_nhien"})

    assert panel._current == "Cap"
    assert panel.values()["VIENEU_VOICE"] == "Cap"

    panel.deleteLater()
    app.processEvents()
