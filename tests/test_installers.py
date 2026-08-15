from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_all_installers_exist_and_call_all_setup_steps():
    windows = (ROOT / "cai_dat_all.bat").read_text(encoding="utf-8")
    linux = (ROOT / "cai_dat_all.sh").read_text(encoding="utf-8")
    for content in (windows, linux):
        for script in ("setup_whisper.py", "setup_vieneu.py",
                       "setup_paraformer.py", "setup_douyin.py",
                       "setup_demucs.py"):
            assert script in content
        assert "requirements.txt" in content


def test_release_builders_bundle_setup_support_helper():
    windows = (ROOT / "scripts" / "build_exe.py").read_text(encoding="utf-8")
    linux = (ROOT / "scripts" / "build_linux.py").read_text(encoding="utf-8")
    assert '"setup_support.py"' in windows
    assert '"setup_support.py"' in linux
    assert 'SETUP_PYTHON_VERSION = "3.12"' in windows
    assert "VoxDub" not in windows[windows.index("def release_guide"):].split(
        "def main", 1
    )[0]
    assert "VoxDub" not in linux


def test_release_specs_bundle_whisper_worker():
    for name in ("autodub.spec", "autodub-linux.spec"):
        source = (ROOT / name).read_text(encoding="utf-8")
        assert "asr_whisper_worker.py" in source

def test_linux_release_spec_bundles_logo_asset():
    source = (ROOT / "autodub-linux.spec").read_text(encoding="utf-8")
    assert 'os.path.join(ROOT, "logo.ico")' in source

def test_release_specs_bundle_qt_runtime_plugins():
    for name in ("autodub.spec", "autodub-linux.spec"):
        source = (ROOT / name).read_text(encoding="utf-8")
        assert '"platforms"' in source
        assert '"multimedia"' in source

def test_icons_have_runtime_logo_fallback(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from autodub_gui import icons

    app = QApplication.instance() or QApplication([])
    pixmap = icons.brand_logo(32)
    assert not pixmap.isNull()
    assert pixmap.width() == 32
    app.processEvents()

def test_release_builders_gate_all_python_workers():
    workers = (
        "asr_whisper_worker.py",
        "asr_paraformer_worker.py",
        "vieneu_worker.py",
        "demucs_worker.py",
        "ocr_worker.py",
    )
    for name in ("scripts/build_exe.py", "scripts/build_linux.py"):
        source = (ROOT / name).read_text(encoding="utf-8")
        for worker in workers:
            assert worker in source
        assert "worker in bundle" in source or "worker trong bundle" in source
        assert "_bundle_data_dir" in source


def test_linux_runtime_probe_rejects_unsupported_python(monkeypatch):
    from autodub_gui import workers_setup

    calls = []

    class Result:
        returncode = 0
        stdout = "\n"

    def fake_run(command, **_kwargs):
        calls.append(command)
        return Result()

    monkeypatch.setattr(workers_setup.subprocess, "run", fake_run)
    assert workers_setup._probe_python(["python3"]) == ""
    assert "(3, 10)" in calls[0][-1]
    assert "(3, 12)" in calls[0][-1]

def test_linux_package_does_not_require_host_python():
    source = (ROOT / "scripts" / "build_deb.py").read_text(encoding="utf-8")
    assert "python3.10" not in source
    assert "python3-pip" not in source
    assert "python3-venv" not in source

def test_linux_package_uses_system_ffmpeg():
    source = (ROOT / "scripts" / "build_deb.py").read_text(encoding="utf-8")
    assert "Depends: ffmpeg" in source
    assert "\n Depends:" not in source
    for package in ("libglib2.0-0", "libpulse0", "libgssapi-krb5-2",
                    "libxcb-shape0"):
        assert package in source
    assert "invalid Debian version" in source
    assert "check-only" in source


def test_deb_builder_configures_utf8_console_output():
    source = (ROOT / "scripts" / "build_deb.py").read_text(encoding="utf-8")
    assert "def _force_utf8_stdio" in source
    assert "_force_utf8_stdio()" in source


def test_deb_bundle_validation_checks_executable_workers_and_setup_scripts(
    tmp_path,
):
    from scripts.build_deb import _validate_bundle

    bundle = tmp_path / "DubFlow"
    (bundle / "data" / "autodub" / "speech").mkdir(parents=True)
    for relative in (
        "autodub/speech/asr_whisper_worker.py",
        "autodub/speech/asr_paraformer_worker.py",
        "autodub/speech/tts/vieneu_worker.py",
            "autodub/media/demucs_worker.py",
            "autodub/media/ocr_worker.py",
            "autodub/media/deepseek_ocr_worker.py",
    ):
        path = bundle / "data" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# worker\n", encoding="utf-8")
    (bundle / "DubFlow").write_bytes(b"binary")
    (bundle / "DubFlow").chmod(0o755)
    (bundle / "VERSION").write_text("3.0.4\n", encoding="utf-8")
    (bundle / "scripts").mkdir()
    for name in (
        "setup_support.py", "setup_vieneu.py", "setup_whisper.py",
            "setup_paraformer.py", "setup_ocr.py", "setup_douyin.py",
            "setup_demucs.py", "setup_voices.py", "setup_deepseek_ocr.py",
    ):
        (bundle / "scripts" / name).write_text("# setup\n", encoding="utf-8")

    _validate_bundle(bundle, "3.0.4")

def test_deb_bundle_validation_prefers_data_dir_with_workers(tmp_path):
    from scripts.build_deb import _validate_bundle

    bundle = tmp_path / "DubFlow"
    (bundle / "data").mkdir(parents=True)
    internal = bundle / "_internal"
    for relative in (
        "autodub/speech/asr_whisper_worker.py",
        "autodub/speech/asr_paraformer_worker.py",
        "autodub/speech/tts/vieneu_worker.py",
            "autodub/media/demucs_worker.py",
            "autodub/media/ocr_worker.py",
            "autodub/media/deepseek_ocr_worker.py",
    ):
        path = internal / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# worker\n", encoding="utf-8")
    (bundle / "DubFlow").write_bytes(b"binary")
    (bundle / "DubFlow").chmod(0o755)
    (bundle / "VERSION").write_text("3.0.4\n", encoding="utf-8")
    (bundle / "scripts").mkdir()
    for name in (
        "setup_support.py", "setup_vieneu.py", "setup_whisper.py",
            "setup_paraformer.py", "setup_ocr.py", "setup_douyin.py",
            "setup_demucs.py", "setup_voices.py", "setup_deepseek_ocr.py",
    ):
        (bundle / "scripts" / name).write_text("# setup\n", encoding="utf-8")

    _validate_bundle(bundle, "3.0.4")

def test_preflight_rejects_ffmpeg_without_ffprobe(monkeypatch):
    from autodub import preflight

    monkeypatch.setattr(preflight.sys, "platform", "linux")
    monkeypatch.setattr(
        preflight.shutil,
        "which",
        lambda name: "/usr/bin/ffmpeg" if name == "ffmpeg" else None,
    )

    result = preflight._check_ffmpeg(__import__("autodub.config",
                                                fromlist=["Settings"]).Settings())

    assert result.level == "fail"

def test_linux_first_run_has_portable_python_runtime():
    source = (ROOT / "autodub_gui" / "workers_setup.py").read_text(
        encoding="utf-8")
    assert "python-build-standalone" in source
    assert "_PORTABLE_PYTHON_SHA256" in source
    assert "_download_portable_python" in source

def test_whisper_setup_finds_worker_in_pyinstaller_data_dirs():
    source = (ROOT / "scripts" / "setup_whisper.py").read_text(
        encoding="utf-8")
    assert "def _find_worker" in source
    assert "_find_worker()" in source
    support = (ROOT / "scripts" / "setup_support.py").read_text(
        encoding="utf-8")
    assert '"data"' in support
    assert '"_internal"' in support
    assert "find_bundled_worker" in source

def test_whisper_worker_finder_supports_current_and_legacy_bundle_layouts(
    monkeypatch, tmp_path
):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    from scripts import setup_whisper

    monkeypatch.setattr(setup_whisper, "PROJECT_ROOT", str(tmp_path))
    worker = tmp_path / "data" / "autodub" / "speech" / "asr_whisper_worker.py"
    worker.parent.mkdir(parents=True)
    worker.write_text("# worker\n", encoding="utf-8")
    assert setup_whisper._find_worker() == str(worker)

    worker.unlink()
    worker = tmp_path / "autodub" / "speech" / "asr_whisper_worker.py"
    worker.parent.mkdir(parents=True)
    worker.write_text("# worker\n", encoding="utf-8")
    assert setup_whisper._find_worker() == str(worker)

def test_whisper_worker_finder_uses_installed_app_root_data_layout(
    monkeypatch, tmp_path
):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    from scripts import setup_whisper

    app_root = tmp_path / "DubFlow"
    worker = app_root / "data" / "autodub" / "speech" / "asr_whisper_worker.py"
    worker.parent.mkdir(parents=True)
    worker.write_text("# worker\n", encoding="utf-8")
    monkeypatch.setattr(setup_whisper, "PROJECT_ROOT", str(tmp_path / "source"))
    monkeypatch.setenv("DUBFLOW_APP_ROOT", str(app_root))
    monkeypatch.setenv("DUBFLOW_DATA_DIR", str(tmp_path / "user-data"))

    assert setup_whisper._find_worker() == str(worker)

def test_external_worker_finders_use_installed_app_root_layout(
    monkeypatch, tmp_path
):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    app_root = tmp_path / "DubFlow"
    for relative, module, name in (
        ("autodub/speech/asr_paraformer_worker.py",
         "scripts.setup_paraformer", "WORKER"),
        ("autodub/media/demucs_worker.py",
         "scripts.setup_demucs", "WORKER"),
    ):
        worker = app_root / "data" / relative
        worker.parent.mkdir(parents=True, exist_ok=True)
        worker.write_text("# worker\n", encoding="utf-8")
        monkeypatch.setenv("DUBFLOW_APP_ROOT", str(app_root))
        loaded = __import__(module, fromlist=[name])
        assert getattr(loaded, name) == str(worker)

def test_whisper_batch_passes_app_and_user_data_roots():
    source = (ROOT / "scripts" / "build_exe.py").read_text(encoding="utf-8")
    start = source.index('SETUP_WHISPER_BAT = r"""')
    payload_start = start + len('SETUP_WHISPER_BAT = r"""')
    payload = source[payload_start:source.index('"""', payload_start)]
    assert 'set "DUBFLOW_APP_ROOT=%CD%"' in payload
    assert 'DUBFLOW_DATA_DIR=%LOCALAPPDATA%\\DubFlow' in payload

def test_ffmpeg_bootstrap_accepts_existing_system_install():
    from autodub_gui import workers_setup

    assert workers_setup._system_ffmpeg_pair(
        lambda name: f"/usr/bin/{name}") == (
            "/usr/bin/ffmpeg", "/usr/bin/ffprobe")

def test_ffmpeg_bootstrap_rejects_incomplete_system_install(monkeypatch):
    from autodub_gui import workers_setup

    # Keep this unit test independent from FFmpeg installed on the runner.
    monkeypatch.setattr(workers_setup.sys, "platform", "win32")
    assert workers_setup._system_ffmpeg_pair(
        lambda name: "/usr/bin/ffmpeg" if name == "ffmpeg" else None) is None

def test_ffmpeg_archive_download_retries_and_cleans_partial_file(
    monkeypatch, tmp_path
):
    from autodub_gui import workers_setup

    calls = []

    class Response:
        headers = {"Content-Length": "4"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _size):
            return b"data" if not calls.pop(0) else b""

    def fake_urlopen(_request, timeout):
        assert timeout == 60
        if len(calls) < 1:
            calls.append(False)
            raise OSError("temporary network error")
        calls.append(True)
        return Response()

    monkeypatch.setattr(workers_setup.urllib.request, "urlopen", fake_urlopen)
    part = tmp_path / "ffmpeg.part"
    logs = []
    workers_setup._download_ffmpeg_archive(
        "https://example.invalid/ffmpeg.tar.xz", str(part), "ffmpeg.tar.xz",
        logs.append, lambda _value: None)

    assert part.read_bytes() == b"data"
    assert any("thử lại" in line for line in logs)


def test_ffmpeg_checksum_accepts_binary_checksum_filename_marker(
    monkeypatch, tmp_path
):
    from autodub_gui import workers_setup

    archive = tmp_path / "ffmpeg.tar.xz"
    archive.write_bytes(b"archive")
    digest = __import__("hashlib").sha256(b"archive").hexdigest()

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return f"{digest} *ffmpeg.tar.xz\n".encode()

    monkeypatch.setattr(
        workers_setup.urllib.request, "urlopen",
        lambda _request, timeout: Response(),
    )

    workers_setup._verify_ffmpeg_archive(str(archive), "ffmpeg.tar.xz")

def test_linux_bootstrap_accepts_system_ffmpeg_without_state(
    monkeypatch, tmp_path
):
    from autodub_gui import bootstrap

    monkeypatch.setattr(bootstrap, "data_root", lambda: str(tmp_path))
    monkeypatch.setattr(bootstrap.sys, "platform", "linux")
    monkeypatch.setattr(
        "autodub_gui.workers_setup._system_ffmpeg_pair",
        lambda: ("/usr/bin/ffmpeg", "/usr/bin/ffprobe"),
    )
    state = bootstrap.load_state()
    for step in bootstrap.steps():
        if step.key != "ffmpeg":
            state["completed"][step.key] = True
    bootstrap.save_state(state)

    assert bootstrap.is_complete()

def test_bootstrap_dialog_skips_linux_system_ffmpeg():
    source = (ROOT / "autodub_gui" / "bootstrap_dialog.py").read_text(
        encoding="utf-8")
    assert "_system_ffmpeg_pair" in source
    assert "bootstrap.mark_completed(step.key)" in source
