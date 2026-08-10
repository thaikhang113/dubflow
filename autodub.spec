# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — VoxDub Studio GUI (onedir, windowed).

Không chạy trực tiếp: dùng  py scripts/build_exe.py  (script đó sinh
autodub_gui/_embedded.py với địa chỉ máy chủ rồi mới gọi PyInstaller).

Nguyên tắc:
- onedir (KHÔNG onefile): PySide6 + ctranslate2 giải nén mỗi lần chạy sẽ
  rất chậm và hay bị antivirus chặn.
- Model, các venv phụ và ffmpeg KHÔNG đóng gói — người dùng tự cài theo
  HUONG_DAN_CAI_DAT.md; app tìm chúng CẠNH exe (autodub.utils.app_root).
- torch/demucs/soundfile bị loại: đường tách nhạc nền bằng CPU không dùng
  trong bản đóng gói (đã có tiến trình con chạy card đồ họa trong venv CUDA;
  thiếu venv thì pipeline tự bỏ qua bước tách một cách an toàn).
"""
import os

from PyInstaller.utils.hooks import collect_all

ROOT = os.path.abspath(SPECPATH)

datas = [
    # Các tiến trình con chạy bằng python của venv riêng — phải là tệp .py
    # thật trong gói (autodub.utils.bundled_file tìm chúng ở _internal).
    (os.path.join(ROOT, "autodub", "speech", "tts", "vieneu_worker.py"),
     os.path.join("autodub", "speech", "tts")),
    (os.path.join(ROOT, "autodub", "speech", "asr_paraformer_worker.py"),
     os.path.join("autodub", "speech")),
    (os.path.join(ROOT, "autodub", "media", "demucs_worker.py"),
     os.path.join("autodub", "media")),
    # Danh mục giọng CapCut — tài nguyên trong gói, đọc qua bundled_file.
    (os.path.join(ROOT, "autodub", "speech", "tts", "capcut_api",
                  "Voice.json"),
     os.path.join("autodub", "speech", "tts", "capcut_api")),
    # Icon cửa sổ/taskbar (app.py nạp qua bundled_file).
    (os.path.join(ROOT, "logo.ico"), "."),
]
binaries = []
hiddenimports = [
    # Import lười (trong thân hàm) — liệt kê rõ để không bị sót khi
    # PyInstaller đổi cách phân tích bytecode.
    "autodub.content.generator",       # pipeline.py step 8
    "autodub.text.ass_karaoke",        # pipeline/editor: phụ đề cụm chữ
    "autodub.text.translate_saas",     # pipeline: dịch qua máy chủ VoxDub
    "autodub.text.translate_review",   # pipeline: soát bản dịch
    "autodub.text.subtitles",          # pipeline/editor: làm mới phụ đề
    "autodub.saas_client",             # mọi lượt gọi máy chủ
    "autodub.device_id",               # mã máy gắn với ví Vox
    "autodub.speech.tts.voice_library",  # Cài đặt: nạp thư viện giọng mẫu
    "autodub.speech.tts.voice_downloader",  # tải + enroll giọng lần đầu chạy
    "autodub.speech.tts.capcut_vi",    # engine giọng CapCut (gọi API)
    "autodub.speech.align",            # ass_karaoke: khớp mốc chữ
    "autodub.media.timing",            # pipeline/editor: timeline mềm
    "autodub.securestore",             # mã hóa file trung gian (hold Vox)
    "cryptography.hazmat.primitives.ciphers.aead",  # AESGCM của securestore
    "_cffi_backend",                   # cryptography cần lúc chạy
    "autodub_gui.fonts",               # style_dialog: font kèm app
    # Phần đa phương tiện của Qt — Trình chỉnh sửa phát video bằng nó.
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
]

# Giao diện nạp từng trang đúng lúc cần (import trong thân hàm) nên
# PyInstaller không thấy chúng khi phân tích tĩnh. Gom cả gói cho chắc.
try:
    from PyInstaller.utils.hooks import collect_submodules

    hiddenimports += collect_submodules("autodub_gui")
except Exception as e:  # noqa: BLE001 — không được làm vỡ quá trình đóng gói
    print(f"[spec] bo qua collect_submodules('autodub_gui'): {e}")

# yt-dlp nạp extractor động theo tên; faster-whisper/ctranslate2 có DLL
# native. Không còn SDK mô hình nào ở phía máy khách — mọi lượt gọi AI đi
# qua HTTP tới máy chủ VoxDub (requests đã có sẵn).
# playwright/PIL KHÔNG đóng gói: Douyin cài qua 'Cai dat tinh nang
# Douyin.bat' (libs/ sideload).
for pkg in ("yt_dlp", "faster_whisper", "ctranslate2"):
    try:
        d, b, h = collect_all(pkg)
    except Exception as e:  # package tùy chọn chưa cài → bỏ qua, không vỡ build
        print(f"[spec] skip collect_all({pkg!r}): {e}")
        continue
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    [os.path.join(ROOT, "autodub_gui", "__main__.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # Chỉ dùng ở đường CPU của vocal_separator — bản exe dựa vào tiến
        # trình con chạy card đồ họa trong venv CUDA. Tiết kiệm ~2 GB.
        "torch", "torchaudio", "demucs", "soundfile", "julius", "openunmix",
        # Rác kéo theo từ dependency phụ — app không đụng tới. ~95 MB.
        # (onnxruntime GIỮ LẠI — faster-whisper cần nó cho vad_filter.)
        "pandas", "pyarrow", "datasets", "aiohttp",
        # av/PyAV — không có import trực tiếp; bị kéo vào ngầm qua dep
        # transitiv. Cắt được ~65 MB.
        "av",
        # faster-whisper + ctranslate2 + onnxruntime + tokenizers + hf_xet
        # chạy trong .venv-whisper qua asr_whisper_worker.py — không cần
        # bundle trong exe, cắt được ~112 MB.
        "faster_whisper", "ctranslate2", "tokenizers", "hf_xet",
        # onnxruntime: VieNeu chạy trong .venv-vieneu; Paraformer trong
        # .venv-asr; Whisper trong .venv-whisper. Không có path nào cần ort
        # trong process chính của exe.
        "onnxruntime",
        # Không dùng trong GUI.
        "tkinter", "matplotlib", "IPython", "jupyter", "pytest",
        # Chuyển sang user-install (libs/ sideload qua Cai dat tinh nang
        # Douyin.bat) hoặc bỏ hẳn (PIL: thumbnail ghi bytes thẳng).
        "playwright", "greenlet", "pyee", "PIL",
        # Qt module app không đụng tới (chỉ dùng Widgets/Core/Gui/Multimedia;
        # QtNetwork GIỮ LẠI — Qt6Multimedia link tới nó).
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

# Cắt các DLL Qt bị plugin (qtvirtualkeyboard) kéo vào dù không import —
# excludes ở trên không chặn được binary-level dependency. ~50 MB.
_QT_PRUNE = ("Qt6Quick", "Qt6Qml", "Qt6QmlModels", "Qt6QmlMeta",
             "Qt6QmlWorkerScript", "Qt6Pdf", "Qt6VirtualKeyboard",
             "Qt6Labs", "opengl32sw", "qtvirtualkeyboardplugin",
             "Qt6ShaderTools", "Qt6SpatialAudio")

# av/PyAV không dùng trực tiếp — prune ở cả Python và binary layer.
_AV_PRUNE = ("av.libs", "avcodec", "avformat", "avutil", "avfilter",
             "avdevice", "swscale", "swresample", "libx265", "libvpx",
             "SvtAv1Enc", "libstdc++")

# faster-whisper / ctranslate2 / onnxruntime chạy trong .venv-whisper —
# prune binary residue dù đã exclude ở Python level.
_ML_PRUNE = ("ctranslate2", "onnxruntime", "tokenizers", "hf_xet",
             "faster_whisper")


def _keep_binary(entry):
    base = os.path.basename(entry[0]).lower()
    dest = (entry[1] or "").lower()
    if any(p.lower() in base for p in _QT_PRUNE):
        return False
    if any(p.lower() in base or p.lower() in dest for p in _AV_PRUNE):
        return False
    if any(p.lower() in base or p.lower() in dest for p in _ML_PRUNE):
        return False
    return True


a.binaries = [b for b in a.binaries if _keep_binary(b)]
# App thuần tiếng Việt — 40+ file dịch .qm của Qt là dung lượng chết.
a.datas = [d for d in a.datas
           if "PySide6\\translations" not in d[0]
           and "PySide6/translations" not in d[0]]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VoxDub",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,   # app GUI — không hiện cửa sổ console
    icon=os.path.join(ROOT, "logo.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="VoxDub",
    contents_directory="data",   # _internal → data: gọn hơn, dễ đọc hơn
)
