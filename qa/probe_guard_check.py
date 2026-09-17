"""Chung minh rang guard test that su bat duoc loi probe bi rong ruot.

Pha mot probe trong app.py, chay test guard, doi phai FAIL, roi khoi phuc.
"""
import shutil
import subprocess
import sys

TARGET = "autodub_gui/app.py"
BACKUP = "qa/_app_backup.py"
PROBE = '        __import__("PySide6.QtMultimedia")\n'


def main() -> int:
    src = open(TARGET, encoding="utf-8").read()
    assert PROBE in src, "khong tim thay probe de pha"
    shutil.copyfile(TARGET, BACKUP)
    try:
        with open(TARGET, "w", encoding="utf-8", newline="") as handle:
            handle.write(src.replace(PROBE, "        pass\n", 1))
        result = subprocess.run(
            [sys.executable, "-m", "pytest",
             "tests/test_gui_regressions.py::test_smoke_probes_still_try_real_imports",
             "-q", "--no-header", "--tb=no", "-p", "no:cacheprovider"],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        broke = result.returncode != 0
        print("probe bi pha -> test:", "FAIL (dung)" if broke else "PASS (SAI)")
        out = (result.stdout or "").strip().splitlines()
        for line in out[-3:]:
            print("   ", line[:110])
    finally:
        shutil.copyfile(BACKUP, TARGET)
        import os

        os.remove(BACKUP)
    restored = open(TARGET, encoding="utf-8").read()
    assert PROBE in restored, "chua khoi phuc duoc app.py"
    print("app.py da khoi phuc nguyen ven")
    return 0 if broke else 1


if __name__ == "__main__":
    raise SystemExit(main())
