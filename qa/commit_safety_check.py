"""Quet bí mật và tệp rác trước khi commit phân phối."""
import re
import subprocess

SECRET = re.compile(
    r"(?i)\b(api[_-]?key|secret|password|passwd|access[_-]?token)\b"
    r"\s*[:=]\s*[\"']?([A-Za-z0-9_\-./+]{16,})"
)
BANNED_PREFIX = (
    "qa/", "test_ui_data/", ".env", "bandit", "bootstrap-state",
    "STATE.md", "uv-export", ".agents/", ".codex/", ".opencode/",
    "dist/", "build/", "logs/",
)


def staged():
    return subprocess.run(["git", "diff", "--cached", "--name-only"],
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace").stdout.split()


def main() -> int:
    files = staged()
    print(f"{len(files)} tep trong commit:")
    for f in files:
        print("   ", f)

    junk = [f for f in files if f.startswith(BANNED_PREFIX)]
    print("\ntep rac/ruc ki:", junk or "khong co")

    diff = subprocess.run(["git", "diff", "--cached"], capture_output=True,
                          text=True, encoding="utf-8",
                          errors="replace").stdout or ""
    hits = []
    for line in diff.splitlines():
        if not line.startswith("+") or line.startswith("+++"):
            continue
        for m in SECRET.finditer(line):
            value = m.group(2)
            # Bo qua ten bien/ham khong phai gia tri that
            if value.startswith(("\"", "f\"", "settings.", "self.")):
                continue
            hits.append(line.strip()[:120])
    print("\nkhoan nghi secret:", len(hits) or 0)
    for h in hits[:10]:
        print("   ", h)

    ok = not junk and not hits
    print("\nKET LUAN:", "san sang commit" if ok else "DUNG LAI - kiem tra moi len tren")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
