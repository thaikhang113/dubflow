"""Quét bí mật và tệp rác trước khi commit phân phối."""
import re
import subprocess

SECRET = re.compile(
    r"(?i)\b(api[_-]?key|secret|password|passwd|access[_-]?token)\b"
    r"\s*[:=]\s*[\"']?([A-Za-z0-9_\-./+]{16,})"
)
# Tệp/thư mục chỉ để chạy tại chỗ: cấm đưa vào commit phân phối.
BANNED = (
    "qa/", "test_ui_data/", "bandit", "bootstrap-state",
    "STATE.md", "uv-export", ".agents/", ".codex/", ".opencode/",
    "dist/", "build/", "logs/",
)
# Cấu hình cá nhân: cấm mọi tệp .env, kể cả .env.<môi trường>.
BANNED_ENV_PREFIX = ".env"
# Ngoại lệ của luật trên: .env.example là tệp phân phối chính thức, được
# scripts/build_exe.py và scripts/build_linux.py sao vào bản cài để người
# dùng có mẫu điền cấu hình. Chặn nó là chặn oan (đã cản trở lúc phát hành
# 3.0.32), nên phải miễn trừ trước khi xét tiền tố .env.
ALLOWED_ENV_FILES = (".env.example",)
# Tệp của chính bộ kiểm tra này được miễn trừ: nó nằm trong qa/ nên khi đang
# sửa dở (trạng thái modified) sẽ bị luật tiền tố "qa/" tố cáo chính nó, khiến
# không thể commit bản vá cho công cụ. Miễn trừ đúng một đường dẫn này, không
# nới lỏng tiền tố "qa/" cho bất kỳ tệp nào khác.
ALLOWED_PATHS = ("qa/commit_safety_check.py",)


def staged():
    """Liệt kê tệp đang nằm trong vùng chờ commit (git diff --cached)."""
    return subprocess.run(["git", "diff", "--cached", "--name-only"],
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace").stdout.split()


def is_banned(path: str) -> bool:
    """True nếu tệp là rác, không được phép commit phân phối.

    .env.example và chính tệp của bộ kiểm tra này được miễn trừ; mọi tệp
    .env khác cùng phần còn lại của qa/ vẫn bị chặn như cũ.
    """
    name = path.rsplit("/", 1)[-1]
    normalized = name[2:] if name.startswith("./") else name
    if path in ALLOWED_PATHS or normalized in ALLOWED_ENV_FILES:
        return False
    return path.startswith(BANNED + (BANNED_ENV_PREFIX,))


def main() -> int:
    files = staged()
    print(f"{len(files)} tep trong commit:")
    for f in files:
        print("   ", f)

    junk = [f for f in files if is_banned(f)]
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
