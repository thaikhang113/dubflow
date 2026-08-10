"""Học toàn bộ giọng mẫu trong thư mục ``voices/`` vào bộ giọng của ứng dụng.

Chạy một lần sau khi thả thêm giọng mẫu:

    py scripts/setup_voices.py            # học những giọng chưa có
    py scripts/setup_voices.py --lam-lai  # học lại cả những giọng đã có

Model chỉ được nạp MỘT lần cho cả lô nên học 60 giọng cũng chỉ mất vài phút,
thay vì vài chục phút nếu gọi lẻ từng giọng. Giọng nào hỏng sẽ bị bỏ qua và
được liệt kê ở cuối; những giọng còn lại vẫn được học bình thường.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from autodub.config import Settings                             # noqa: E402
from autodub.speech.tts import voice_library                    # noqa: E402
from autodub.speech.tts.vieneu_vi import _WORKER_SCRIPT         # noqa: E402

TIMEOUT_S = 3600


def run(overwrite: bool = False) -> int:
    settings = Settings.load()
    if not settings.vieneu_configured():
        print("Chưa cài bộ giọng VieNeu. Chạy trước một lần:\n"
              "    py scripts/setup_vieneu.py")
        return 2

    root = voice_library.library_dir()
    voices = voice_library.scan(root)
    if not voices:
        print(f"Không tìm thấy giọng mẫu nào trong: {root}\n"
              "Mỗi thư mục con cần có tệp voices_manifest.json và các tệp "
              ".wav đi kèm.")
        return 1

    todo = voices if overwrite else voice_library.pending(settings, root)
    print(f"Thư viện có {len(voices)} giọng; cần học {len(todo)} giọng.")
    if not todo:
        print("Không có gì để làm — mọi giọng đều đã sẵn sàng.")
        return 0

    fd, batch_path = tempfile.mkstemp(suffix=".json", prefix="voxdub_enroll_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump([v.to_batch_item() for v in todo], f,
                      ensure_ascii=False)
        command = [
            settings.vieneu_venv_python_path(), _WORKER_SCRIPT,
            "--model-dir", settings.vieneu_model_dir_path(),
            "--custom-voices", settings.vieneu_custom_voices_path(),
            "--enroll-batch", batch_path,
        ]
        if overwrite:
            command.append("--enroll-overwrite")
        print("Đang học giọng, tiến độ hiện bên dưới. Đừng tắt cửa sổ này.\n")
        result = subprocess.run(command, capture_output=True,
                                encoding="utf-8", errors="replace",
                                timeout=TIMEOUT_S)
    finally:
        if os.path.exists(batch_path):
            os.remove(batch_path)

    # Tiến độ của tiến trình con đi qua stderr; dòng JSON kết quả ở stdout.
    if result.stderr:
        print(result.stderr.strip())
    payload = _last_json_line(result.stdout or "")
    if not payload.get("ok"):
        print("\nKhông học được giọng: "
              + (payload.get("error") or (result.stderr or "")[-400:]
                 or "không rõ nguyên nhân"))
        return 1

    added, failed = payload.get("added", []), payload.get("failed", [])
    print(f"\nXong: đã thêm {len(added)} giọng, "
          f"bỏ qua {payload.get('skipped', 0)} giọng đã có.")
    if failed:
        print(f"{len(failed)} giọng không học được:")
        for item in failed:
            print(f"  - {item.get('name')}: {item.get('error')}")
    print("\nMở ứng dụng, vào Cài đặt > Âm thanh để nghe thử và chọn giọng.")
    return 0


def _last_json_line(output: str) -> dict:
    for line in reversed(output.strip().splitlines()):
        if line.lstrip().startswith("{"):
            try:
                return json.loads(line)
            except ValueError:
                continue
    return {}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lam-lai", action="store_true", dest="overwrite",
                        help="học lại cả những giọng đã có trong máy")
    args = parser.parse_args()
    return run(overwrite=args.overwrite)


if __name__ == "__main__":
    sys.exit(main())
