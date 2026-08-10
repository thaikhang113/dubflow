"""Trang Tài khoản — ví Vox, kích hoạt mã, lịch sử tiêu dùng.

Không có đăng nhập: chính chiếc máy này là danh tính. Trang này là nơi duy
nhất người dùng nhìn thấy điều đó — mã máy (để đọc cho bộ phận hỗ trợ khi
cần chuyển credit sang máy mới), số Vox còn lại, ô nhập mã kích hoạt, và
lịch sử cộng trừ.

Mọi lượt gọi mạng đều nằm trên luồng nền: một cú bấm "Kích hoạt" mất vài
giây, và giao diện đứng im trong lúc đó là lỗi nghiêm trọng hơn cả việc mã
sai.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from autodub_gui import tokens
from autodub_gui.pages import BasePage
from autodub_gui.ui.buttons import GhostButton, PrimaryButton
from autodub_gui.ui.cards import Card
from autodub_gui.ui.inputs import LabeledLineEdit
from autodub_gui.ui.style import clear_background
from autodub_gui.ui.toast import TOASTS

_PAGE_MARGIN = 24
_HISTORY_LIMIT = 20

#: Nhãn tiếng Việt cho từng loại giao dịch trong sổ cái.
_LEDGER_LABELS = {
    "activation": "Kích hoạt mã",
    "trial": "Tặng dùng thử",
    "usage": "Sử dụng",
    "admin_grant": "Quản trị cộng",
    "admin_deduct": "Quản trị trừ",
    "refund": "Hoàn lại",
    "transfer_in": "Chuyển từ máy khác sang",
    "transfer_out": "Chuyển sang máy khác",
}


class _CallWorker(QThread):
    """Chạy một lượt gọi máy chủ ở luồng nền và trả về (kết quả, lỗi)."""

    done = Signal(object, str)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn

    def run(self) -> None:
        from autodub.saas_client import SaasError

        try:
            self.done.emit(self._fn(), "")
        except SaasError as e:
            self.done.emit(None, str(e))
        except Exception as e:  # noqa: BLE001 — báo lên giao diện, không sập
            self.done.emit(None, f"{type(e).__name__}: {e}")


def _hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet(f"color: {tokens.TEXT_MUTED}; "
                        f"font-size: {tokens.FS_META}px; background: transparent;")
    return label


class AccountPage(BasePage):
    """Ví Vox, kích hoạt mã và lịch sử."""

    #: Cửa sổ chính nghe tín hiệu này để cập nhật huy hiệu Vox trên header.
    balance_changed = Signal(int)

    def __init__(self, settings_provider=None, parent: QWidget | None = None):
        super().__init__(parent)
        del settings_provider
        self._workers: list[_CallWorker] = []
        self._build()

    # -- Dựng giao diện ------------------------------------------------

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(_PAGE_MARGIN, tokens.SP_4,
                                _PAGE_MARGIN, tokens.SP_4)
        root.setSpacing(tokens.SP_3)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        clear_background(scroll)
        body = QWidget()
        clear_background(body)
        self._body = QVBoxLayout(body)
        self._body.setContentsMargins(0, 0, tokens.SP_2, 0)
        self._body.setSpacing(tokens.SP_3)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        self._body.addWidget(self._build_balance_card())
        self._body.addWidget(self._build_activate_card())
        self._body.addWidget(self._build_history_card())
        self._body.addWidget(self._build_device_card())
        self._body.addStretch()

    def _build_balance_card(self) -> Card:
        card = Card(padding=tokens.SP_4, spacing=tokens.SP_2)
        card.add_header("Ví của bạn")

        self.balance_label = QLabel("— Vox")
        self.balance_label.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-size: 32px; font-weight: 700; "
            f"background: transparent;")
        card.body.addWidget(self.balance_label)

        self.balance_note = _hint("Đang đọc số dư…")
        card.body.addWidget(self.balance_note)

        row = QHBoxLayout()
        row.setSpacing(tokens.SP_2)
        buy = PrimaryButton("Mua thêm Vox")
        buy.clicked.connect(self._open_buy_page)
        refresh = GhostButton("Đọc lại số dư")
        refresh.clicked.connect(self.refresh)
        row.addWidget(buy)
        row.addWidget(refresh)
        row.addStretch()
        card.body.addLayout(row)
        card.body.addWidget(_hint("1 Vox = 10đ · 1.000 Vox = 10.000đ"))
        return card

    def _build_activate_card(self) -> Card:
        card = Card(padding=tokens.SP_4, spacing=tokens.SP_2)
        card.add_header("Kích hoạt mã")
        card.body.addWidget(_hint(
            "Mua Vox trên website, thanh toán qua PayOS (quét QR, thẻ ngân "
            "hàng hoặc ví điện tử) là nhận mã ngay. Dán mã vào đây để cộng "
            "Vox vào máy này.\n"
            "Mỗi mã chỉ kích hoạt được MỘT lần trên MỘT máy — không có ngoại lệ."))

        self.key_input = LabeledLineEdit(
            "Mã kích hoạt", "VOX-XXXX-XXXX-XXXX",
            "Gõ thường hay hoa đều được, dấu gạch nối không bắt buộc.")
        card.body.addWidget(self.key_input)

        row = QHBoxLayout()
        row.setSpacing(tokens.SP_2)
        self.activate_button = PrimaryButton("Kích hoạt")
        self.activate_button.clicked.connect(self._activate)
        row.addWidget(self.activate_button)
        self.activate_status = _hint("")
        row.addWidget(self.activate_status, 1)
        card.body.addLayout(row)
        return card

    def _build_history_card(self) -> Card:
        card = Card(padding=tokens.SP_4, spacing=tokens.SP_2)
        card.add_header("Lịch sử gần đây")
        self.history_box = QVBoxLayout()
        self.history_box.setSpacing(tokens.SP_1)
        card.body.addLayout(self.history_box)
        self.history_empty = _hint("Chưa có giao dịch nào.")
        card.body.addWidget(self.history_empty)
        return card

    def _build_device_card(self) -> Card:
        card = Card(padding=tokens.SP_4, spacing=tokens.SP_2)
        card.add_header("Máy này")
        self.device_label = QLabel("—")
        self.device_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self.device_label.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-size: {tokens.FS_BODY}px; "
            f"font-weight: 600; background: transparent;")
        card.body.addWidget(self.device_label)
        card.body.addWidget(_hint(
            "Vox gắn với chiếc máy này, không phải với tài khoản. Cài lại "
            "ứng dụng hay xóa cấu hình đều không mất Vox.\n"
            "Đổi máy hoặc cài lại Windows thì mã máy đổi theo — đọc mã dưới "
            "đây cho bộ phận hỗ trợ để được chuyển Vox sang máy mới."))
        return card

    # -- Nạp dữ liệu ---------------------------------------------------

    def on_shown(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        """Đọc lại số dư, lịch sử và thông tin máy."""
        from autodub.device_id import get_device_name, short_id
        from autodub.saas_client import is_configured

        self.device_label.setText(f"{get_device_name()}\nMã máy: {short_id()}")

        if not is_configured():
            # Chạy thuần trên máy — không có ví để đọc. Trang này vốn đã bị
            # giấu khỏi thanh bên; đây là chốt chặn cho các lối vào còn lại.
            self.balance_note.setText(
                "Đang chạy thuần trên máy — không dùng Vox.\n"
                "Bước dịch chuyển sang dịch tay. Muốn dịch tự động thì dựng "
                "máy chủ theo control_server/README.md rồi đặt VOXDUB_API_URL.")
            return

        def _load():
            from autodub.saas_client import get_client

            client = get_client()
            device = client.ensure_session()
            history = client.credit_history(page=1, limit=_HISTORY_LIMIT)
            return device, history

        self._run(_load, self._on_loaded)

    def _on_loaded(self, result, error: str) -> None:
        if error:
            self.balance_note.setText(
                f"Chưa đọc được số dư: {error}\n"
                "Kiểm tra kết nối mạng rồi bấm Đọc lại số dư.")
            return
        device, history = result
        balance = int(device.get("balance", 0))
        self.balance_label.setText(f"{balance:,} Vox".replace(",", "."))
        if not device.get("creditEnabled", True):
            self.balance_note.setText(
                "Hệ thống credit đang tắt — mọi tính năng miễn phí.")
        else:
            self.balance_note.setText(
                f"Đủ dịch khoảng {balance} câu thoại.")
        self.balance_changed.emit(balance)
        self._fill_history(history.get("items") or [])

    def _fill_history(self, items: list[dict]) -> None:
        while self.history_box.count():
            item = self.history_box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.history_empty.setVisible(not items)
        for entry in items:
            self.history_box.addWidget(self._history_row(entry))

    def _history_row(self, entry: dict) -> QWidget:
        row = QWidget()
        clear_background(row)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(tokens.SP_2)

        delta = int(entry.get("delta", 0))
        kind = _LEDGER_LABELS.get(entry.get("type", ""), entry.get("type", ""))
        desc = str(entry.get("description") or kind)

        text = QLabel(desc)
        text.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Preferred)
        text.setStyleSheet(f"color: {tokens.TEXT_SECONDARY}; "
                           f"font-size: {tokens.FS_LABEL}px; background: transparent;")
        layout.addWidget(text, 1)

        amount = QLabel(f"{delta:+,}".replace(",", "."))
        amount.setStyleSheet(
            f"color: {tokens.SUCCESS if delta > 0 else tokens.TEXT_MUTED}; "
            f"font-size: {tokens.FS_LABEL}px; font-weight: 600; "
            f"background: transparent;")
        layout.addWidget(amount)
        return row

    # -- Kích hoạt -----------------------------------------------------

    def _activate(self) -> None:
        code = self.key_input.text().strip()
        if not code:
            self.activate_status.setText("Nhập mã kích hoạt trước đã.")
            return
        self.activate_button.set_loading(True, "Đang kích hoạt")
        self.activate_status.setText("")

        def _call():
            from autodub.saas_client import get_client

            return get_client().activate_key(code)

        self._run(_call, self._on_activated)

    def _on_activated(self, result, error: str) -> None:
        self.activate_button.set_loading(False)
        if error:
            self.activate_status.setText(error)
            TOASTS.error("Kích hoạt không thành công", detail=error)
            return

        vox = int(result.get("vox", 0))
        balance = int(result.get("balanceAfter", 0))
        if result.get("alreadyActivated"):
            self.activate_status.setText(
                "Mã này đã được kích hoạt trên máy này từ trước — không cộng lại.")
            TOASTS.info("Mã đã kích hoạt trước đó rồi.")
        else:
            self.activate_status.setText(f"Đã cộng {vox:,} Vox.".replace(",", "."))
            TOASTS.success(f"Kích hoạt thành công, cộng {vox:,} Vox."
                           .replace(",", "."))
            self.key_input.set_text("")
        self.balance_label.setText(f"{balance:,} Vox".replace(",", "."))
        self.balance_changed.emit(balance)
        self.refresh()

    # -- Tiện ích ------------------------------------------------------

    def _open_buy_page(self) -> None:
        import webbrowser

        from autodub.saas_client import get_client

        config = get_client().app_config()
        base = str(config.get("webUrl") or "https://example.com").rstrip("/")
        webbrowser.open(f"{base}/mua")

    def _run(self, fn, on_done) -> None:
        worker = _CallWorker(fn, self)

        def _finish(result, error: str) -> None:
            self._workers.remove(worker)
            on_done(result, error)

        worker.done.connect(_finish)
        self._workers.append(worker)
        worker.start()

    def is_running(self) -> bool:
        return any(w.isRunning() for w in self._workers)

    def shutdown(self) -> None:
        for worker in list(self._workers):
            if worker.isRunning():
                worker.wait(10_000)
