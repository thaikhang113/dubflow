"""Rào chắn: worker dùng cancel_scope("gui") phải xoá cờ huỷ trước khi chạy.

Cờ huỷ của phạm vi "gui" nằm trong cancel.py và KHÔNG tự tắt. Worker nào mở
cancel_scope("gui") mà quên clear_cancel_request() sẽ chết ngay ở bước kiểm
tra huỷ đầu tiên của lượt sau — người dùng thấy "bấm là dừng ngay" dù chưa
hề bấm Dừng. Đây đúng là lỗi mà chú thích ở DubWorker.run đã cảnh báo.

Test quét AST chứ không so chuỗi nguồn, và ràng buộc MỌI lớp worker hiện có
lẫn về sau: thêm một worker mới quên xoá cờ là test đỏ.
"""
from __future__ import annotations

import ast
from pathlib import Path

WORKERS_PY = Path(__file__).resolve().parents[1] / "autodub_gui" / "workers.py"


def _module() -> ast.Module:
    return ast.parse(WORKERS_PY.read_text(encoding="utf-8"))


def _run_method(node: ast.ClassDef) -> ast.FunctionDef | None:
    for item in node.body:
        if isinstance(item, ast.FunctionDef) and item.name == "run":
            return item
    return None


def _calls(node: ast.AST, name: str) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            func = sub.func
            if isinstance(func, ast.Name) and func.id == name:
                return True
            if isinstance(func, ast.Attribute) and func.attr == name:
                return True
    return False


def test_worker_mo_cancel_scope_phai_xoa_co_huy_truoc():
    """Mọi worker mở cancel_scope("gui") phải gọi clear_cancel_request()."""
    module = _module()
    vi_pham: list[str] = []
    da_kiem = 0

    for node in module.body:
        if not isinstance(node, ast.ClassDef):
            continue
        run = _run_method(node)
        if run is None:
            continue
        # Chỉ xét worker thật sự mở phạm vi huỷ "gui" — đó là các worker
        # có thể bị lệnh Dừng của người dùng chạm tới.
        opens_gui_scope = any(
            isinstance(c, ast.Constant) and c.value == "gui"
            for c in ast.walk(run)
        )
        if not opens_gui_scope:
            continue
        da_kiem += 1
        if not _calls(run, "clear_cancel_request"):
            vi_pham.append(node.name)

    assert da_kiem > 0, "không tìm thấy worker nào mở cancel_scope(\"gui\")"
    assert not vi_pham, (
        "các worker sau mở cancel_scope(\"gui\") nhưng thiếu "
        f"clear_cancel_request(): {vi_pham}"
    )


def test_danh_sach_worker_duoc_kiem_khong_bi_rong():
    """Chính bộ quét phải tìm ra worker — tránh test rỗng ruột."""
    module = _module()
    ten = {n.name for n in module.body if isinstance(n, ast.ClassDef)}
    # Vài worker trọng yếu phải có mặt trong tệp, nếu không thì bộ quét
    # đang nhìn nhầm chỗ và test phía trên xanh một cách vô nghĩa.
    for bat_buoc in ("DubWorker", "SaveAllWorker", "RebuildWorker"):
        assert bat_buoc in ten
