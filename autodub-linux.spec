# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Linux desktop bundle."""
import os
import sys

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = os.path.abspath(SPECPATH)

datas = [
    (os.path.join(ROOT, "autodub", "speech", "tts", "vieneu_worker.py"),
     os.path.join("autodub", "speech", "tts")),
    (os.path.join(ROOT, "autodub", "speech", "asr_paraformer_worker.py"),
     os.path.join("autodub", "speech")),
    (os.path.join(ROOT, "autodub", "speech", "asr_whisper_worker.py"),
     os.path.join("autodub", "speech")),
    (os.path.join(ROOT, "autodub", "media", "demucs_worker.py"),
     os.path.join("autodub", "media")),
    (os.path.join(ROOT, "autodub", "speech", "tts", "capcut_api", "Voice.json"),
     os.path.join("autodub", "speech", "tts", "capcut_api")),
]
binaries = []
hiddenimports = [
    "autodub.content.generator",
    "autodub.text.ass_karaoke",
    "autodub.text.subtitles",
    "autodub.device_id",
    "autodub.speech.tts.voice_library",
    "autodub.speech.tts.voice_downloader",
    "autodub.speech.tts.capcut_vi",
    "autodub.speech.align",
    "autodub.media.timing",
    "autodub_gui.fonts",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
]
hiddenimports += collect_submodules("autodub_gui")

for package in ("yt_dlp",):
    try:
        data, binary, hidden = collect_all(package)
    except Exception as exc:
        print(f"[spec] skip {package}: {exc}")
        continue
    datas += data
    binaries += binary
    hiddenimports += hidden

a = Analysis(
    [os.path.join(ROOT, "autodub_gui", "__main__.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "torch", "torchaudio", "demucs", "soundfile", "julius", "openunmix",
        "pandas", "pyarrow", "datasets", "aiohttp", "av",
        "faster_whisper", "ctranslate2", "tokenizers", "hf_xet",
        "onnxruntime", "playwright", "greenlet", "pyee", "PIL",
        "tkinter", "matplotlib", "IPython", "jupyter", "pytest",
        "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets",
        "PySide6.QtQuickControls2", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
        "PySide6.QtVirtualKeyboard", "PySide6.QtWebChannel",
        "PySide6.QtWebSockets", "PySide6.QtPositioning", "PySide6.QtLocation",
        "PySide6.QtBluetooth", "PySide6.QtSensors", "PySide6.QtSerialPort",
        "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtDesigner",
        "PySide6.QtUiTools", "PySide6.QtHelp",
    ],
    noarchive=False,
)

prune = (
    "Qt6Quick", "Qt6Qml", "Qt6QmlModels", "Qt6QmlMeta",
    "Qt6QmlWorkerScript", "Qt6Pdf", "Qt6VirtualKeyboard", "Qt6Labs",
    "Qt6ShaderTools", "Qt6SpatialAudio", "av.libs", "avcodec", "avformat",
    "avutil", "avfilter", "avdevice", "swscale", "swresample", "libx265",
    "libvpx", "SvtAv1Enc", "libstdc++", "ctranslate2", "onnxruntime",
    "tokenizers", "hf_xet", "faster_whisper",
)

def keep_binary(entry):
    name = os.path.basename(entry[0]).lower()
    destination = (entry[1] or "").lower()
    return not any(
        marker.lower() in name or marker.lower() in destination
        for marker in prune
    )

a.binaries = [entry for entry in a.binaries if keep_binary(entry)]
a.datas = [
    entry for entry in a.datas
    if "PySide6/translations" not in entry[0]
    and "PySide6\\translations" not in entry[0]
]

pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DubFlow",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)
COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="DubFlow",
    contents_directory="data",
)
