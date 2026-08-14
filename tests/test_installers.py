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

def test_linux_first_run_has_portable_python_runtime():
    source = (ROOT / "autodub_gui" / "workers_setup.py").read_text(
        encoding="utf-8")
    assert "python-build-standalone" in source
    assert "_PORTABLE_PYTHON_SHA256" in source
    assert "_download_portable_python" in source
