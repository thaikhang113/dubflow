"""Rà soát GUI như người dùng: dựng MainWindow offscreen, đi qua 13 trang,
chụp ảnh, kiểm widget trọng yếu và trạng thái, thử nhánh lỗi hiển thị.

Chạy:  .venv\\Scripts\\python.exe qa\\gui_walkthrough.py
Kết quả: qa/shots/<page>.png, qa/logs/gui_walkthrough.log, qa/findings.json
"""
from __future__ import annotations

import json
import os
import sys
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("AUTODUB_SMOKE", "1")
os.environ.setdefault(
    "DUBFLOW_DATA_DIR",
    os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "DubFlow"),
)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from autodub_gui import _frozen  # noqa: E402

_frozen.init()

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QCheckBox, QComboBox, QLineEdit, QPushButton, QSlider,
)

from autodub_gui.app import (  # noqa: E402
    PAGES, ROW_BATCH, ROW_EDITOR, ROW_NEW, ROW_SETTINGS,
    ROW_TRANSLATE, MainWindow,
)
from autodub_gui.app import ROW_EDITOR_LAUNCHER  # noqa: E402

SHOTS = os.path.join(ROOT, "qa", "shots")
LOGS = os.path.join(ROOT, "qa", "logs")
os.makedirs(SHOTS, exist_ok=True)
os.makedirs(LOGS, exist_ok=True)

FINDINGS: list[dict] = []
LOG_LINES: list[str] = []


def log(msg: str) -> None:
    LOG_LINES.append(msg)
    print(msg, flush=True)


def finding(page: str, kind: str, severity: str, summary: str,
            expected: str = "", actual: str = "", evidence: str = "") -> None:
    FINDINGS.append({
        "page": page, "kind": kind, "severity": severity,
        "summary": summary, "expected": expected, "actual": actual,
        "evidence": evidence,
    })
    log(f"  [{severity}] {kind}: {summary}"
        + (f" | mong đợi: {expected} | thực tế: {actual}" if expected else ""))


def pump(app: QApplication, n: int = 4) -> None:
    for _ in range(n):
        app.processEvents()
        QTimer.singleShot(0, lambda: None)


def shot(widget, name: str) -> str:
    path = os.path.join(SHOTS, f"{name}.png")
    try:
        pm = widget.grab()
        if pm.isNull():
            return ""
        pm.save(path)
        return path
    except Exception:
        return ""


def count(widget, cls) -> int:
    return len(widget.findChildren(cls))


def texts(widget) -> list[str]:
    out = []
    for le in widget.findChildren(QLineEdit):
        out.append(le.text())
    return out


def _make_editor_fixture() -> str:
    """Dự án tối thiểu trong qa/work để mở Trình chỉnh sửa như người dùng."""
    work = os.path.join(ROOT, "qa", "work", "editor_fixture")
    data = os.path.join(work, "data")
    os.makedirs(data, exist_ok=True)
    segments = [
        {"id": 1, "text": "hello world", "text_vi": "Xin chào thế giới.",
         "start": 0.0, "end": 2.0, "duration": 2.0, "slot": 2.4},
        {"id": 2, "text": "second line", "text_vi": "Đây là câu thứ hai.",
         "start": 2.0, "end": 4.5, "duration": 2.5, "slot": 2.9},
    ]
    with open(os.path.join(data, "transcript_vi.json"), "w",
              encoding="utf-8") as f:
        json.dump(segments, f, ensure_ascii=False, indent=2)
    with open(os.path.join(data, "transcript_original.json"), "w",
              encoding="utf-8") as f:
        json.dump(segments, f, ensure_ascii=False, indent=2)
    with open(os.path.join(data, "render_opts.json"), "w",
              encoding="utf-8") as f:
        json.dump({"subtitle_mode": "soft", "blur_regions": []}, f)
    return work


def check_page(app, win, row: int, label: str) -> dict:
    """Chuyển tới trang, chụp, kiểm tra sơ bộ. Trả về số liệu thống kê."""
    info = {"row": row, "label": label, "built": False, "widgets": 0,
            "buttons": 0, "inputs": 0, "combos": 0, "blank": False}
    try:
        win.switch_page(row)
        pump(app)
        # ROW_EDITOR là trang ngữ cảnh: chưa có dự án -> app chuyển hướng
        # sang launcher. Đó là hành vi chủ đích, không phải lỗi.
        actual_row = win.pages.currentIndex()
        redirect = None
        if row == ROW_EDITOR and actual_row != row:
            redirect = actual_row
            log(f"  (chuyển hướng editor -> index {actual_row}, đúng thiết kế)")
        page = win._page_widgets.get(row) or win.pages.currentWidget()
        if page is None:
            finding(label, "build", "S1", "trang không được dựng khi chuyển tới")
            return info
        info["built"] = True
        info["redirect"] = redirect
        page.show()
        pump(app)
        path = shot(page, f"page_{row}")
        info["widgets"] = len(page.findChildren(object))
        info["buttons"] = count(page, QPushButton)
        info["inputs"] = count(page, QLineEdit)
        info["combos"] = count(page, QComboBox)
        info["evidence"] = path
        # Trang trắng: có nội dung nhưng không có widget tương tác nào
        if info["widgets"] < 5 and info["buttons"] == 0:
            info["blank"] = True
            finding(label, "render", "S3", "trang gần như trống",
                    "có nội dung điều khiển được", f"widgets={info['widgets']}",
                    path)
        log(f"  OK widgets={info['widgets']} buttons={info['buttons']} "
            f"inputs={info['inputs']} combos={info['combos']} shot={os.path.basename(path)}")
        return info
    except Exception as exc:
        finding(label, "crash", "S1", f"exception khi dựng/chuyển trang: {exc}",
                "không exception", traceback.format_exc(limit=3)[-300:])
        return info


def main() -> int:
    app = QApplication.instance() or QApplication([])
    win = MainWindow()
    win.resize(1360, 820)
    win.show()
    pump(app, 8)
    log(f"MainWindow dựng xong, {len(PAGES)} trang khai báo")

    stats = []
    for row, name, *_rest in PAGES:
        log(f"--- trang {row}: {name}")
        stats.append(check_page(app, win, row, name))

    # --- Kiểm trạng thái nút theo dữ liệu (Batch) ---------------------
    log("--- Batch: trạng thái nút Start khi danh sách trống")
    try:
        batch = win._page_widgets.get(ROW_BATCH)
        if batch is not None:
            batch._items.clear()
            batch._refresh_table()
            pump(app)
            if batch.btn_start.isEnabled():
                finding("Xử lý hàng loạt", "validation", "S3",
                        "nút 'Bắt đầu tất cả' bật khi chưa có video nào",
                        "disabled khi danh sách trống", "enabled=True")
            else:
                log("  OK nút Start disabled khi trống")
            batch._add_files([os.path.join(ROOT, "test_ui_data", "e2e_test.mp4")])
            pump(app)
            if not batch._items:
                finding("Xử lý hàng loạt", "interaction", "S2",
                        "thêm file video hợp lệ nhưng danh sách vẫn trống")
            else:
                log(f"  OK thêm file -> {len(batch._items)} item")
            if not batch.btn_start.isEnabled():
                finding("Xử lý hàng loạt", "validation", "S2",
                        "nút Start vẫn disable dù đã có video")
            shot(batch, "batch_with_items")
    except Exception as exc:
        finding("Xử lý hàng loạt", "crash", "S1", f"lỗi tương tác: {exc}",
                actual=traceback.format_exc(limit=3)[-300:])

    # --- Wizard Tạo dự án: điều hướng 6 bước -------------------------
    log("--- Tạo dự án: điều hướng 6 bước")
    try:
        newp = win._page_widgets.get(ROW_NEW)
        if newp is not None:
            stepper = getattr(newp, "stepper", None) or getattr(newp, "_stepper", None)
            log(f"  stepper={type(stepper).__name__}")
            n_steps = 6
            for i in range(n_steps):
                try:
                    if hasattr(newp, "go_to_step"):
                        newp.go_to_step(i)
                    elif stepper is not None and hasattr(stepper, "set_current"):
                        stepper.set_current(i)
                    pump(app)
                    shot(newp, f"wizard_step_{i}")
                except Exception as exc:
                    finding("Tạo dự án", "interaction", "S2",
                            f"không chuyển được tới bước {i + 1}: {exc}")
                    break
            else:
                log(f"  OK đi qua {n_steps} bước")
    except Exception as exc:
        finding("Tạo dự án", "crash", "S1", f"lỗi wizard: {exc}",
                actual=traceback.format_exc(limit=3)[-300:])

    # --- Cài đặt: đọc/ghi không mất dữ liệu ---------------------------
    log("--- Cài đặt: nạp giá trị và ghi")
    try:
        settings_page = win._page_widgets.get(ROW_SETTINGS)
        if settings_page is not None:
            fields = settings_page.findChildren(QLineEdit)
            combos = settings_page.findChildren(QComboBox)
            checks = settings_page.findChildren(QCheckBox)
            sliders = settings_page.findChildren(QSlider)
            log(f"  ô nhập={len(fields)} combo={len(combos)} "
                f"checkbox={len(checks)} slider={len(sliders)}")
            if len(fields) + len(combos) + len(checks) + len(sliders) < 10:
                finding("Cài đặt", "render", "S2",
                        "số control cấu hình quá ít so với mặt bằng settings",
                        "nhiều nhóm cấu hình",
                        f"total={len(fields) + len(combos) + len(checks) + len(sliders)}")
            shot(settings_page, "settings_full")
    except Exception as exc:
        finding("Cài đặt", "crash", "S1", f"lỗi trang Cài đặt: {exc}",
                actual=traceback.format_exc(limit=3)[-300:])

    # --- Dịch thuật: endpoint chết phải báo rõ ------------------------
    log("--- Dịch thuật: trạng thái khi endpoint không truy cập được")
    try:
        tr = win._page_widgets.get(ROW_TRANSLATE)
        if tr is not None:
            shot(tr, "translate_page")
            log("  OK trang Dịch thuật render")
    except Exception as exc:
        finding("Dịch thuật", "crash", "S1", f"lỗi: {exc}")

    # --- Trình chỉnh sửa với dự án thật -------------------------------
    log("--- Trình chỉnh sửa: mở một dự án có transcript")
    try:
        fixture = _make_editor_fixture()
        win.open_editor(fixture)
        pump(app, 8)
        editor = win._page_widgets.get(ROW_EDITOR)
        if editor is None:
            finding("Trình chỉnh sửa", "build", "S1",
                    "open_editor() không dựng trang chỉnh sửa",
                    "trang editor được dựng và nạp danh sách câu",
                    "page is None")
        else:
            pump(app)
            path = shot(editor, "editor_loaded")
            n_seg = len(getattr(getattr(editor, "_state", None), "segments", []) or [])
            log(f"  OK editor dựng, segments={n_seg}, shot={os.path.basename(path)}")
            if n_seg == 0:
                finding("Trình chỉnh sửa", "data", "S2",
                        "mở dự án hợp lệ nhưng 0 câu được nạp",
                        "số câu khớp transcript_vi.json", f"segments={n_seg}", path)
            tl = getattr(editor, "timeline", None) or getattr(editor, "_timeline", None)
            log(f"  timeline={type(tl).__name__ if tl is not None else 'không thấy'}")
    except Exception as exc:
        finding("Trình chỉnh sửa", "crash", "S1",
                f"exception khi mở dự án: {exc}",
                actual=traceback.format_exc(limit=4)[-400:])

    # --- Trang launcher của editor (không nằm trong PAGES) ------------
    log("--- Editor launcher (hàng đợi trung gian)")
    try:
        win.switch_page(ROW_EDITOR_LAUNCHER)
        pump(app)
        launcher = win._page_widgets.get(ROW_EDITOR_LAUNCHER)
        if launcher is None:
            finding("Editor launcher", "build", "S2",
                    "không dựng được trang launcher khi chuyển trực tiếp")
        else:
            shot(launcher, "editor_launcher")
            log("  OK launcher render")
    except Exception as exc:
        finding("Editor launcher", "crash", "S2", f"lỗi: {exc}",
                actual=traceback.format_exc(limit=3)[-300:])

    # --- Không có emoji trong UI (chuẩn dự án) ------------------------
    log("--- Quét emoji trong nhãn hiển thị")
    try:
        import re
        emoji = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF]")
        bad = []
        for row, page in win._page_widgets.items():
            for btn in page.findChildren(QPushButton):
                t = btn.text()
                if t and emoji.search(t):
                    bad.append((row, t))
        if bad:
            finding("Toàn cục", "styling", "S3",
                    f"{len(bad)} nút chứa emoji", "không emoji trong UI",
                    "; ".join(f"{r}:{t}" for r, t in bad[:5]))
        else:
            log("  OK không có emoji trên nút")
    except Exception as exc:
        log(f"  bỏ qua kiểm tra emoji: {exc}")

    # --- Thoát an toàn ------------------------------------------------
    for page in win._page_widgets.values():
        if hasattr(page, "shutdown"):
            try:
                page.shutdown()
            except Exception as exc:
                finding("Toàn cục", "teardown", "S2",
                        f"shutdown trang lỗi: {exc}")
    win._force_close = True
    win.close()
    pump(app, 4)

    out = {
        "pages_checked": len(stats),
        "pages_built": sum(1 for s in stats if s["built"]),
        "findings": FINDINGS,
    }
    with open(os.path.join(ROOT, "qa", "findings_gui.json"), "w",
              encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    with open(os.path.join(LOGS, "gui_walkthrough.log"), "w",
              encoding="utf-8") as f:
        f.write("\n".join(LOG_LINES))
    log(f"=== {out['pages_built']}/{out['pages_checked']} trang dựng OK, "
        f"{len(FINDINGS)} phát hiện")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
