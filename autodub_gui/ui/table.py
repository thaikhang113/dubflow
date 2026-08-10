"""Bảng dữ liệu có hàng chứa widget như huy hiệu, thanh tiến trình hay nút.

Cột nội dung co giãn theo cửa sổ; cột số và cột nút vừa khít nội dung. Ô chữ
dài được rút gọn kèm chú giải giữ nguyên văn.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QHeaderView, QStackedWidget,
    QTableWidget, QTableWidgetItem, QWidget,
)

from autodub_gui import tokens
from autodub_gui.ui.style import clear_background
from autodub_gui.ui.empty import EmptyState, ErrorState, LoadingState

_ROW_H = 56


@dataclass
class Column:
    """Mô tả một cột của bảng."""

    title: str
    stretch: bool = False
    width: int = 0
    align: Qt.AlignmentFlag = field(
        default=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)


class DataTable(QStackedWidget):
    """Bảng kèm ba màn hình thay thế (đang tải, trống, lỗi) trong cùng một chỗ."""

    row_activated = Signal(int)

    def __init__(self, columns: list[Column], parent: QWidget | None = None, *,
                 empty_title: str = "Chưa có mục nào",
                 empty_description: str = "",
                 empty_action: str = ""):
        super().__init__(parent)
        self._columns = list(columns)

        self.table = QTableWidget(0, len(columns))
        self.table.setHorizontalHeaderLabels([c.title for c in columns])
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(False)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.table.verticalHeader().setDefaultSectionSize(_ROW_H)
        self.table.cellDoubleClicked.connect(
            lambda row, _c: self.row_activated.emit(row))

        header = self.table.horizontalHeader()
        header.setHighlightSections(False)
        for i, column in enumerate(self._columns):
            if column.stretch:
                header.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)
            elif column.width:
                header.setSectionResizeMode(i, QHeaderView.ResizeMode.Fixed)
                self.table.setColumnWidth(i, column.width)
            else:
                header.setSectionResizeMode(
                    i, QHeaderView.ResizeMode.ResizeToContents)

        self.empty = EmptyState(empty_title, empty_description, empty_action)
        self.loading = LoadingState("Đang tải danh sách")
        self.error = ErrorState()
        for widget in (self.table, self.empty, self.loading, self.error):
            self.addWidget(widget)

    # -- Chuyển màn hình -----------------------------------------------
    def show_table(self) -> None:
        self.setCurrentWidget(self.table)

    def show_empty(self) -> None:
        self.setCurrentWidget(self.empty)

    def show_loading(self) -> None:
        self.setCurrentWidget(self.loading)

    def show_error(self, title: str, description: str = "") -> None:
        """Hiện màn hình lỗi kèm hướng dẫn xử lý."""
        self.error.set_message(title, description)
        self.setCurrentWidget(self.error)

    def auto_state(self) -> None:
        """Tự chọn giữa bảng và màn hình trống dựa vào số hàng hiện có."""
        self.show_table() if self.table.rowCount() else self.show_empty()

    # -- Dựng hàng -----------------------------------------------------
    def clear_rows(self) -> None:
        self.table.clearContents()
        self.table.setRowCount(0)

    def add_row(self) -> int:
        """Thêm một hàng trống và trả về chỉ số của hàng đó."""
        row = self.table.rowCount()
        self.table.insertRow(row)
        return row

    def set_text(self, row: int, col: int, text: str,
                 tooltip: str = "") -> QTableWidgetItem:
        """Đặt chữ vào ô, mặc định lấy luôn chữ đó làm chú giải."""
        item = QTableWidgetItem(text)
        item.setToolTip(tooltip or text)
        item.setTextAlignment(self._columns[col].align)
        self.table.setItem(row, col, item)
        return item

    def set_widget(self, row: int, col: int, widget: QWidget, *,
                   margin: int = tokens.SP_2) -> QWidget:
        """Đặt một widget vào ô, có lề nhỏ để không dính sát viền."""
        holder = QWidget()
        clear_background(holder)
        layout = QHBoxLayout(holder)
        layout.setContentsMargins(margin, 2, margin, 2)
        layout.setSpacing(tokens.SP_2)
        layout.addWidget(widget)
        self.table.setCellWidget(row, col, holder)
        return holder

    def set_widgets(self, row: int, col: int, widgets: list[QWidget], *,
                    margin: int = tokens.SP_2) -> QWidget:
        """Đặt nhiều widget nằm ngang trong cùng một ô."""
        holder = QWidget()
        clear_background(holder)
        layout = QHBoxLayout(holder)
        layout.setContentsMargins(margin, 2, margin, 2)
        layout.setSpacing(tokens.SP_1)
        for widget in widgets:
            layout.addWidget(widget)
        layout.addStretch()
        self.table.setCellWidget(row, col, holder)
        return holder

    def row_count(self) -> int:
        return self.table.rowCount()

    def current_row(self) -> int:
        return self.table.currentRow()
