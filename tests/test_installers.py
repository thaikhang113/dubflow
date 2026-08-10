from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_all_installers_exist_and_call_all_setup_steps():
    windows = (ROOT / "cai_dat_all.bat").read_text(encoding="utf-8")
    linux = (ROOT / "cai_dat_all.sh").read_text(encoding="utf-8")
    for content in (windows, linux):
        for script in ("setup_whisper.py", "setup_vieneu.py",
                       "setup_paraformer.py", "setup_douyin.py"):
            assert script in content
        assert "requirements.txt" in content
