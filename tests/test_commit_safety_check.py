"""Kiểm tra qa/commit_safety_check.py không chặn oan tệp phân phối.

Lỗi gốc: BANNED_PREFIX chứa ".env" và so bằng str.startswith nên .env.example
bị báo là rác, dù scripts/build_exe.py và scripts/build_linux.py sao tệp này
vào bản cài. Việc đó đã cản trở thật lúc phát hành 3.0.32. Bộ test này khoá
cả hai chiều: tệp phân phối phải lọt, cấu hình cá nhân phải bị chặn.
"""
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "qa" / "commit_safety_check.py"


def _load_module():
    """Nạp qa/commit_safety_check.py theo đường dẫn, không cần package qa."""
    spec = importlib.util.spec_from_file_location("commit_safety_check",
                                                  SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODULE = _load_module()


# Tệp được phép commit: .env.example là mẫu cấu hình chính thức của bản cài,
# còn chính bộ kiểm tra này phải commit được (nếu không thì không thể vá nó).
DUOC_PHEP = [
    ".env.example",
    "./.env.example",
    "autodub/utils.py",
    "qa/commit_safety_check.py",
]

# Tệp bị chặn, mỗi dòng kèm lý do để khi test đỏ là biết ngay luật nào vỡ.
BI_CHAN = [
    (".env", "cấu hình cá nhân, .gitignore đã loại"),
    (".env.local", "biến thể cấu hình cá nhân"),
    (".env.production", "biến thể cấu hình cá nhân"),
    ("STATE.md", "nhật ký nội bộ của trợ lý"),
    # Chỉ miễn trừ đúng tệp bộ kiểm tra; phần còn lại của qa/ vẫn bị chặn.
    ("qa/findings_e2e.json", "thư mục qa/"),
    ("qa/work/audit-settings/.env", "thư mục qa/ và cấu hình cá nhân"),
    ("test_ui_data/.env", "thư mục test_ui_data/"),
    ("dist/DubFlow.exe", "thư mục dist/"),
    ("build/lib/foo.py", "thư mục build/"),
    ("logs/run1.txt", "thư mục logs/"),
    (".agents/agent.json", "thư mục .agents/"),
    (".codex/config.toml", "thư mục .codex/"),
    (".opencode/state.json", "thư mục .opencode/"),
    ("bandit.json", "kết quả quét bảo mật"),
    ("bootstrap-state.json", "trạng thái bootstrap"),
    ("uv-export.txt", "bản xuất phụ thuộc"),
]


@pytest.mark.parametrize("duong_dan", DUOC_PHEP)
def test_khong_chan_tep_phan_phoi(duong_dan):
    """.env.example phải lọt qua bộ kiểm tra."""
    assert MODULE.is_banned(duong_dan) is False


@pytest.mark.parametrize("duong_dan,ly_do", BI_CHAN)
def test_chan_rac_va_cau_hinh_ca_nhan(duong_dan, ly_do):
    """Rác và .env thật vẫn phải bị chặn."""
    assert MODULE.is_banned(duong_dan) is True, ly_do


def test_mien_tru_theo_tieng_toi_trong_moi_thu_muc():
    """Bản sao .env.example lồng trong thư mục con cũng phải lọt."""
    assert MODULE.is_banned("docs/huong-dan/.env.example") is False
    assert MODULE.is_banned("sub/.env.example") is False


def test_main_cho_qua_khi_chi_co_env_example(monkeypatch, capsys):
    """Đầu-cuối: commit chỉ có .env.example thì main() trả về 0."""
    monkeypatch.setattr(MODULE, "staged", lambda: [".env.example"])
    monkeypatch.setattr(MODULE.subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a, 0,
                                                                    "", ""))
    assert MODULE.main() == 0
    assert ".env.example" not in capsys.readouterr().out.split("tep rac")[1]


def test_main_dung_lai_khi_co_env_that(monkeypatch):
    """Đầu-cuối: commit có .env thật thì main() trả về 1."""
    monkeypatch.setattr(MODULE, "staged", lambda: [".env"])
    monkeypatch.setattr(MODULE.subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a, 0,
                                                                    "", ""))
    assert MODULE.main() == 1


def test_danh_sach_cam_khong_con_tien_to_env_tho():
    """Luật .env phải tách riêng để không chặn oan .env.example."""
    assert ".env" not in MODULE.BANNED
    assert MODULE.BANNED_ENV_PREFIX == ".env"
    assert ".env.example" in MODULE.ALLOWED_ENV_FILES
    assert "qa/commit_safety_check.py" in MODULE.ALLOWED_PATHS


def test_bo_kiem_tra_khong_tu_to_cao_chinh_minh():
    """Tệp bộ kiểm tra phải commit được, nhưng qa/ vẫn chặn mọi tệp khác."""
    assert MODULE.is_banned("qa/commit_safety_check.py") is False
    assert MODULE.is_banned("./qa/commit_safety_check.py") is False
    # Không được nới lỏng tiền tố "qa/" cho tệp khác trong cùng thư mục.
    assert MODULE.is_banned("qa/findings_e2e.json") is True
    assert MODULE.is_banned("qa/other_tool.py") is True


def test_script_chay_truc_tiep_voi_nguon_tieng_viet():
    """Chạy thật bằng python: phải thoát 0 và in tiêu đề có dấu."""
    ket_qua = subprocess.run([sys.executable, str(SCRIPT)],
                             capture_output=True, text=True,
                             encoding="utf-8", errors="replace",
                             cwd=str(REPO_ROOT))
    assert ket_qua.returncode == 0, ket_qua.stderr
    # Dòng tiêu đề giữ dấu tiếng Việt; các dòng trạng thái cố ý viết không dấu
    # cho an toàn trên console mã hoá lạ, nên chỉ kiểm tra phần có dấu.
    assert "\ntep rac/ruc ki:" in ket_qua.stdout
    assert "khoan nghi secret:" in ket_qua.stdout
