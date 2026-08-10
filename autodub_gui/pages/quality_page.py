"""Trang Báo cáo chất lượng — hiển thị quality_report.json của một dự án.

Cho phép chọn dự án từ danh sách, hiển thị các chỉ số chất lượng chính:
- Tổng số câu thoại, câu OK, câu bị dịch chuyển/nén/chồng lấn
- Token sử dụng cho dịch thuật (nếu có)
- Danh sách chi tiết các câu có vấn đề (nếu có)
"""
from __future__ import annotations

import json
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QScrollArea, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from autodub.workdir import data_path
from autodub_gui import icons, tokens
from autodub_gui.pages import BasePage
from autodub_gui.ui.cards import Card, StatCard
from autodub_gui.ui.empty import EmptyState, LoadingState
from autodub_gui.ui.style import clear_background

_TABLE_MIN_H = 300   # chiều cao tối thiểu bảng chi tiết segment


class QualityPage(BasePage):
    """Báo cáo chất lượng của một dự án."""

    def __init__(self, settings_provider, parent: QWidget | None = None):
        super().__init__(parent)
        self._settings_provider = settings_provider
        self._projects: list = []
        self._current_report: dict = {}
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(tokens.SP_6, tokens.SP_4,
                                tokens.SP_6, tokens.SP_6)
        root.setSpacing(tokens.SP_4)

        title = QLabel("Báo cáo chất lượng")
        title.setObjectName("pageTitle")
        root.addWidget(title)

        hint = QLabel("Xem chi tiết chất lượng xử lý của một dự án: "
                      "câu dịch quá dài, timeline bị nén, token đã dùng.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        root.addWidget(hint)

        # Dropdown chọn dự án
        picker_row = QHBoxLayout()
        picker_row.setSpacing(tokens.SP_2)
        picker_label = QLabel("Dự án:")
        picker_label.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: {tokens.FS_BODY}px;")
        self.project_combo = QComboBox()
        self.project_combo.setMinimumWidth(400)
        self.project_combo.currentIndexChanged.connect(self._on_project_changed)
        picker_row.addWidget(picker_label)
        picker_row.addWidget(self.project_combo, 1)
        root.addLayout(picker_row)

        # Vùng nội dung chính — scroll area để chứa các thẻ thống kê và bảng
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        clear_background(scroll)
        clear_background(scroll.viewport())

        self._body = QWidget()
        clear_background(self._body)
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(0, 0, 0, 0)
        self._body_layout.setSpacing(tokens.SP_3)

        self._loading = LoadingState("Đang quét dự án...")
        self._body_layout.addWidget(self._loading)
        self._body_layout.addStretch()

        scroll.setWidget(self._body)
        root.addWidget(scroll, 1)

    def on_shown(self) -> None:
        self._scan_projects()

    def _scan_projects(self) -> None:
        """Quét thư mục output để tìm các dự án có quality_report.json."""
        import os

        from autodub.utils import app_root
        from autodub_gui.projects import scan

        settings = self._settings_provider()
        output_dir = getattr(settings, "output_dir", "") or "output"
        if not os.path.isabs(output_dir):
            output_dir = os.path.join(app_root(), output_dir)

        try:
            all_projects = scan(output_dir, use_cache=True)
        except Exception:
            all_projects = []

        # Lọc chỉ những dự án có quality_report.json
        self._projects = []
        for p in all_projects:
            qr_path = data_path(p.work_dir, "quality_report.json")
            if os.path.isfile(qr_path):
                self._projects.append(p)

        self._loading.setVisible(False)

        if not self._projects:
            empty = EmptyState(
                "Chưa có báo cáo nào",
                "Tạo và hoàn thành một dự án để xem báo cáo chất lượng tại đây.")
            self._body_layout.insertWidget(0, empty)
            return

        # Sort mới nhất trước
        self._projects.sort(key=lambda p: p.created_at, reverse=True)

        # Điền vào combo
        self.project_combo.blockSignals(True)
        self.project_combo.clear()
        for p in self._projects:
            self.project_combo.addItem(p.title or p.work_dir, p.work_dir)
        self.project_combo.blockSignals(False)

        # Tự động chọn dự án đầu tiên
        if self._projects:
            self._load_report(self._projects[0].work_dir)

    def _on_project_changed(self, index: int) -> None:
        if index < 0 or index >= len(self._projects):
            return
        work_dir = self.project_combo.itemData(index)
        if work_dir:
            self._load_report(work_dir)

    def _load_report(self, work_dir: str) -> None:
        qr_path = data_path(work_dir, "quality_report.json")
        try:
            with open(qr_path, encoding="utf-8") as f:
                self._current_report = json.load(f)
        except (OSError, json.JSONDecodeError):
            self._current_report = {}

        self._render_report()

    def _render_report(self) -> None:
        """Hiển thị nội dung báo cáo."""
        # Xóa widget cũ (trừ loading và stretch cuối)
        while self._body_layout.count() > 1:
            item = self._body_layout.takeAt(0)
            w = item.widget()
            if w and w is not self._loading:
                w.deleteLater()

        if not self._current_report:
            err = EmptyState("Báo cáo không hợp lệ",
                             "Không đọc được dữ liệu từ quality_report.json.")
            self._body_layout.insertWidget(0, err)
            return

        summary = self._current_report.get("summary", {})
        translate_usage = self._current_report.get("translate_usage", {})
        per_segment = self._current_report.get("per_segment", [])

        # Thẻ tổng quan
        overview = self._build_overview(summary)
        self._body_layout.insertWidget(0, overview)

        # Thẻ token dịch (nếu có)
        if translate_usage and any(translate_usage.values()):
            token_card = self._build_token_card(translate_usage)
            self._body_layout.insertWidget(1, token_card)

        # Bảng chi tiết các câu có vấn đề
        if per_segment:
            table = self._build_segment_table(per_segment)
            self._body_layout.insertWidget(self._body_layout.count() - 1, table)

    def _build_overview(self, summary: dict) -> QWidget:
        card = Card(padding=tokens.SP_4, spacing=tokens.SP_3)
        card.add_header("Tổng quan")

        from PySide6.QtWidgets import QGridLayout

        grid = QGridLayout()
        grid.setSpacing(tokens.SP_3)

        stats = [
            ("Tổng số câu", icons.layers, tokens.TEXT_SECONDARY,
             str(summary.get("segments_total", 0))),
            ("Câu không có vấn đề", icons.check, tokens.SUCCESS,
             str(summary.get("segments_ok", 0))),
            ("Câu bị dời chỗ", icons.merge, tokens.WARNING,
             str(summary.get("segments_shifted", 0))),
            ("Câu bị đọc nhanh lên", icons.waveform, tokens.ACCENT_BLUE,
             str(summary.get("segments_compressed", 0))),
            ("Câu chồng tiếng", icons.warning, tokens.DANGER,
             str(summary.get("segments_overlapped", 0))),
            ("Câu dịch quá dài", icons.edit, tokens.ACCENT_PURPLE,
             str(summary.get("segments_over_budget", 0))),
        ]

        for i, (label, icon_fn, color, value) in enumerate(stats):
            sc = StatCard(label, icon_fn, color)
            sc.set_value(value)
            grid.addWidget(sc, i // 3, i % 3)

        card.body.addLayout(grid)
        return card

    def _build_token_card(self, usage: dict) -> QWidget:
        card = Card(padding=tokens.SP_4, spacing=tokens.SP_2)
        card.add_header("Token đã tiêu cho lượt dịch")

        items = [
            ("Số lượt gọi", usage.get("requests", 0)),
            ("Token gửi đi", usage.get("prompt_tokens", 0)),
            ("Token nhận về", usage.get("completion_tokens", 0)),
            ("Tổng cộng", usage.get("total_tokens", 0)),
        ]

        for label, count in items:
            row = QHBoxLayout()
            row.setSpacing(tokens.SP_2)
            lbl = QLabel(label + ":")
            lbl.setStyleSheet(f"color: {tokens.TEXT_SECONDARY}; "
                              f"font-size: {tokens.FS_BODY}px; "
                              f"background: transparent;")
            val = QLabel(f"{count:,}" if count else "—")
            val.setStyleSheet(f"color: {tokens.TEXT_PRIMARY}; "
                              f"font-size: {tokens.FS_BODY}px; "
                              f"font-weight: 600; background: transparent;")
            row.addWidget(lbl)
            row.addWidget(val)
            row.addStretch()
            card.body.addLayout(row)

        return card

    def _build_segment_table(self, segments: list[dict]) -> QWidget:
        card = Card(padding=tokens.SP_4, spacing=tokens.SP_2)
        card.add_header(f"Câu cần xem lại ({len(segments)})")

        table = QTableWidget()
        table.setColumnCount(4)
        table.setHorizontalHeaderLabels(
            ["Câu", "Thời điểm", "Vấn đề", "Nội dung"])
        table.setRowCount(len(segments))
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows)
        table.verticalHeader().setVisible(False)

        for i, seg in enumerate(segments):
            issues = []
            overlap = seg.get("overlap_prev_s")
            if isinstance(overlap, (int, float)):
                issues.append(f"chồng tiếng {overlap:.2f}s")
            shift = seg.get("shift_s")
            if isinstance(shift, (int, float)):
                issues.append(f"dời {shift:.2f}s")
            atempo = seg.get("atempo")
            if isinstance(atempo, (int, float)):
                issues.append(f"đọc nhanh ×{atempo:.2f}")
            over = seg.get("over_budget_chars")
            if isinstance(over, (int, float)):
                issues.append(f"dư {int(over)} ký tự")

            start = seg.get("start")
            start_text = (f"{float(start):.1f}s"
                          if isinstance(start, (int, float)) else "—")
            values = (str(seg.get("id", "")), start_text,
                      ", ".join(issues) or "—", seg.get("text", ""))
            for col, text in enumerate(values):
                table.setItem(i, col, QTableWidgetItem(text))

        table.resizeColumnsToContents()
        table.horizontalHeader().setStretchLastSection(True)
        table.setMinimumHeight(_TABLE_MIN_H)
        card.body.addWidget(table)
        return card
