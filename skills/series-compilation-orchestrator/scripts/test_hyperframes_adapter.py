import json, os, subprocess, sys, tempfile
from pathlib import Path

SCRIPT = Path(__file__).with_name("hyperframes_adapter.py")

def call(*args, env=None):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, env=env)

def test_status_reports_configured_root(tmp_path):
    env = os.environ.copy(); env["OPENCLAW_HYPERFRAMES_ROOT"] = str(tmp_path)
    result = call("status", env=env)
    assert result.returncode == 0
    assert json.loads(result.stdout)["available"] is True

def test_dry_run_rejects_missing_input(tmp_path):
    result = call("dry-run", "--input", str(tmp_path / "missing.mp4"), "--output", str(tmp_path))
    assert result.returncode == 2
    assert json.loads(result.stdout)["error"] == "input_not_file"

def test_dry_run_rejects_file_output(tmp_path):
    source = tmp_path / "input.mp4"; source.write_bytes(b"x")
    output = tmp_path / "output"; output.write_bytes(b"x")
    result = call("dry-run", "--input", str(source), "--output", str(output))
    assert json.loads(result.stdout)["error"] == "output_not_directory"
