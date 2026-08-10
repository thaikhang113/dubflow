"""Trình phát video có lớp phụ đề chồng lên hình.

Dùng khung cảnh đồ họa của Qt thay vì widget video gốc: trên Windows, widget
video gốc vẽ thẳng lên bề mặt của hệ điều hành nên mọi thứ đặt chồng lên nó
đều bị che mất, kể cả chữ phụ đề.

Câu phụ đề đang hiện được tìm bằng phép tìm nhị phân trên mảng mốc bắt đầu đã
sắp xếp; quét tuần tự sẽ chậm thấy rõ với video dài hàng trăm câu.
"""
from __future__ import annotations

import bisect
import os

from PySide6.QtCore import QPointF, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QGraphicsScene, QGraphicsTextItem, QGraphicsView, QHBoxLayout, QLabel,
    QSizePolicy, QSlider, QStackedWidget, QVBoxLayout, QWidget,
)

from autodub_gui import icons, tokens
from autodub_gui.formatting import format_duration
from autodub_gui.ui.buttons import IconButton
from autodub_gui.ui.empty import EmptyState, ErrorState
from autodub_gui.ui.style import panel_background

try:
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
    from PySide6.QtMultimediaWidgets import QGraphicsVideoItem
    HAS_MULTIMEDIA = True
except ImportError:      # thiếu phần đa phương tiện thì vẫn mở được ứng dụng
    HAS_MULTIMEDIA = False

_MS = 1000.0
_TICK_MS = 40                  # nhịp cập nhật vị trí, đủ mượt mà không tốn sức
_CONTROL_H = 44
_ICON = 32
_SEEK_STEP_S = 1.0
_SEEK_BIG_STEP_S = 5.0
# libass vẽ phụ đề trên khung cao 288 điểm; cỡ chữ và lề trong kiểu phụ đề
# đều tính theo khung đó, nên xem trước phải quy đổi qua tỉ lệ này.
_ASS_PLAY_RES_Y = 288
_VOLUME_DEFAULT = 80
_PIP_W, _PIP_H = 320, 180


class VideoPlayer(QWidget):
    """Khung phát video kèm thanh điều khiển và lớp phụ đề."""

    position_changed = Signal(float)     # vị trí hiện tại, tính bằng giây
    duration_changed = Signal(float)
    state_changed = Signal(bool)         # đang phát hay không
    open_requested = Signal()            # người dùng muốn chọn thư mục dự án

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        from autodub.media.subtitle import normalize_style

        self._segments: list[dict] = []
        self._starts: list[float] = []
        self._text_field = "text_vi"
        self._duration = 0.0
        self._seeking = False
        self._source = ""
        self._external_dialog = None
        # Tệp đang mở đã có phụ đề ghi thẳng vào hình thì tắt lớp chữ xem
        # trước — không thì hai lớp phụ đề chồng lên nhau.
        self._overlay_enabled = True
        # Chữ xem trước dùng CHÍNH dict kiểu sẽ ghi vào video, nên khung xem
        # trước là bản nháp thật của phụ đề chứ không phải một lớp chữ khác.
        self._style = normalize_style(None)
        self._build()

    # -- Dựng giao diện ------------------------------------------------
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_stage())
        self.empty = EmptyState(
            "Chưa mở dự án nào",
            "Chọn một dự án ở trang Dự án của tôi, hoặc mở thư mục dự án có "
            "sẵn trên máy.", "Chọn thư mục dự án…")
        self.empty.action_clicked.connect(self.open_requested.emit)
        self.error = ErrorState("Không phát được video",
                                retry_label="", action_label="")
        self._stack.addWidget(self.empty)
        self._stack.addWidget(self.error)
        root.addWidget(self._stack, 1)
        root.addWidget(self._build_controls())
        self._stack.setCurrentWidget(self.empty)

    def _build_stage(self) -> QWidget:
        """Vùng hiển thị hình ảnh và chữ phụ đề."""
        self.view = QGraphicsView()
        self.view.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.view.setRenderHints(QPainter.RenderHint.Antialiasing
                                 | QPainter.RenderHint.SmoothPixmapTransform)
        self.view.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setStyleSheet(
            f"QGraphicsView {{ background: {tokens.BG_VIDEO}; border: none; }}")
        self.view.setSizePolicy(QSizePolicy.Policy.Expanding,
                                QSizePolicy.Policy.Expanding)
        self.scene = QGraphicsScene(self)
        self.view.setScene(self.scene)

        if HAS_MULTIMEDIA:
            self.video_item = QGraphicsVideoItem()
            self.scene.addItem(self.video_item)
            self.player = QMediaPlayer(self)
            self.audio = QAudioOutput(self)
            self.audio.setVolume(_VOLUME_DEFAULT / 100)
            self.player.setAudioOutput(self.audio)
            self.player.setVideoOutput(self.video_item)
            self.player.durationChanged.connect(self._on_duration)
            self.player.playbackStateChanged.connect(self._on_state)
            self.player.errorOccurred.connect(self._on_error)
        else:
            self.video_item = None
            self.player = None
            self.audio = None

        self.subtitle_item = QGraphicsTextItem()
        self.scene.addItem(self.subtitle_item)
        self._restyle_subtitle()

        self._timer = QTimer(self)
        self._timer.setInterval(_TICK_MS)
        self._timer.timeout.connect(self._tick)
        return self.view

    def _build_controls(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(_CONTROL_H)
        panel_background(bar, tokens.PLAYER_BAR_BG)
        row = QHBoxLayout(bar)
        row.setContentsMargins(tokens.SP_2, 0, tokens.SP_2, 0)
        row.setSpacing(tokens.SP_1)

        self.btn_play = IconButton(icons.play(tokens.SUCCESS),
                                   "Phát hoặc tạm dừng", size=_ICON)
        self.btn_play.clicked.connect(self.toggle_play)
        row.addWidget(self.btn_play)
        for icon, tip, handler in (
                (icons.skip_back(tokens.TEXT_SECONDARY), "Về câu trước",
                 self.previous_segment),
                (icons.skip_forward(tokens.TEXT_SECONDARY), "Sang câu sau",
                 self.next_segment)):
            button = IconButton(icon, tip, size=_ICON)
            button.clicked.connect(handler)
            row.addWidget(button)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.sliderPressed.connect(self._on_slider_pressed)
        self.slider.sliderReleased.connect(self._on_slider_released)
        row.addWidget(self.slider, 1)

        self.time_label = QLabel("00:00 / 00:00")
        self.time_label.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: {tokens.FS_META}px; "
            f"background: transparent;")
        row.addWidget(self.time_label)

        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(_VOLUME_DEFAULT)
        self.volume.setMaximumWidth(90)
        self.volume.setToolTip("Âm lượng")
        self.volume.valueChanged.connect(self._on_volume)
        row.addWidget(IconButton(icons.volume(tokens.TEXT_SECONDARY),
                                 "Âm lượng", size=_ICON))
        row.addWidget(self.volume)

        for icon, tip, handler in (
                (icons.pip(tokens.TEXT_SECONDARY),
                 "Xem trong cửa sổ nhỏ luôn nổi trên cùng", self.open_pip),
                (icons.fullscreen(tokens.TEXT_SECONDARY),
                 "Xem toàn màn hình", self.open_fullscreen)):
            button = IconButton(icon, tip, size=_ICON)
            button.clicked.connect(handler)
            row.addWidget(button)
        return bar

    # -- Nạp video -----------------------------------------------------
    def open(self, path: str) -> bool:
        """Mở một tệp video. Trả về True nếu mở được."""
        self.release()
        if not path or not os.path.isfile(path):
            self._show_error(
                "Không tìm thấy tệp video",
                "Tệp video của dự án này không còn trên máy. Có thể nó đã bị "
                "di chuyển hoặc xóa đi.")
            return False
        if not HAS_MULTIMEDIA:
            self._show_error(
                "Máy này chưa phát được video trong ứng dụng",
                "Phần đa phương tiện của giao diện chưa sẵn sàng. Bạn vẫn có "
                "thể mở video bằng trình phát ngoài.")
            return False
        self._source = path
        self.player.setSource(QUrl.fromLocalFile(path))
        self._stack.setCurrentIndex(0)
        # Bố trí ngay — không có bước này thì QGraphicsVideoItem ở kích thước
        # 0×0 cho đến khi cửa sổ được thay đổi kích thước lần đầu, gây ra màn
        # hình video đen hoàn toàn dù đã nạp xong.
        self._layout_scene()
        # Sau khi media nạp xong: giải mã frame đầu tiên để hiện ảnh tĩnh
        # ngay (không cần người dùng bấm Phát trước).
        try:
            self.player.mediaStatusChanged.connect(self._on_media_loaded_once)
        except Exception:
            pass
        return True

    def _on_media_loaded_once(self, status) -> None:
        """Hiện frame đầu khi media vừa nạp xong (chỉ kích hoạt một lần)."""
        from PySide6.QtMultimedia import QMediaPlayer as _QMP
        if status not in (_QMP.MediaStatus.LoadedMedia,
                          _QMP.MediaStatus.BufferedMedia):
            return
        try:
            self.player.mediaStatusChanged.disconnect(self._on_media_loaded_once)
        except Exception:
            pass
        self._layout_scene()
        # play → pause ngay sau 80 ms để bộ giải mã decode frame đầu tiên.
        # Nếu chưa có source (release() đã gọi) thì bỏ qua.
        if self._source and not self.is_playing():
            self.player.play()
            from PySide6.QtCore import QTimer
            QTimer.singleShot(80, self._pause_after_first_frame)

    def _pause_after_first_frame(self) -> None:
        """Dừng ngay sau khi frame đầu đã vẽ xong."""
        if self._source and not self._seeking:
            self.player.pause()
            self.player.setPosition(0)

    def set_segments(self, segments: list[dict], text_field: str = "text_vi") -> None:
        """Nạp danh sách câu thoại để hiện phụ đề và nhảy giữa các câu."""
        self._segments = sorted(segments, key=lambda s: float(s.get("start", 0)))
        self._starts = [float(s.get("start", 0.0)) for s in self._segments]
        self._text_field = text_field
        self._update_subtitle(self.position())

    def set_subtitle_style(self, style: dict | None) -> None:
        """Đổi kiểu chữ xem trước cho khớp kiểu sẽ ghi vào video."""
        from autodub.media.subtitle import normalize_style

        self._style = normalize_style(style)
        self._restyle_subtitle()
        self._update_subtitle(self.position())
        self._layout_subtitle()

    def _restyle_subtitle(self) -> None:
        """Áp phông, cỡ chữ và màu của kiểu hiện tại lên chữ xem trước.

        Cỡ chữ trong tệp phụ đề tính trên khung ASS cao 288 điểm, còn khung
        xem trước có chiều cao thật của widget — nhân theo tỉ lệ đó thì chữ
        xem trước to đúng bằng chữ sẽ hiện trên video.
        """
        s = self._style
        height = max(1, self.view.height()) if hasattr(self, "view") else 288
        scale = height / _ASS_PLAY_RES_Y
        font = QFont(str(s["font"]) or "Arial")
        font.setPixelSize(max(8, round(int(s["font_size"]) * scale)))
        font.setBold(bool(s["bold"]))
        self.subtitle_item.setFont(font)
        self.subtitle_item.setDefaultTextColor(QColor(str(s["color"])))

    def release(self) -> None:
        """Nhả tệp đang mở để Windows không khóa nó lại."""
        self._timer.stop()
        if self.player is not None:
            self.player.stop()
            self.player.setSource(QUrl())
        self._source = ""
        self.subtitle_item.setPlainText("")

    def show_empty(self) -> None:
        self._stack.setCurrentWidget(self.empty)

    def _show_error(self, title: str, message: str) -> None:
        self.error.set_message(title, message)
        self._stack.setCurrentWidget(self.error)

    def _on_error(self, _error, message: str = "") -> None:
        self._show_error(
            "Không phát được video này",
            "Máy chưa có bộ giải mã phù hợp cho định dạng của video. Bạn vẫn "
            "có thể mở bằng trình phát ngoài. "
            + (message or ""))

    # -- Điều khiển ----------------------------------------------------
    def play(self) -> None:
        if self.player is not None and self._source:
            self.player.play()

    def pause(self) -> None:
        if self.player is not None:
            self.player.pause()

    def toggle_play(self) -> None:
        """Đang phát thì dừng, đang dừng thì phát tiếp."""
        if self.player is None:
            return
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.pause()
        else:
            self.play()

    def seek(self, seconds: float) -> None:
        """Nhảy tới một thời điểm, tính bằng giây."""
        if self.player is None:
            return
        target = max(0.0, min(seconds, self._duration or seconds))
        self.player.setPosition(int(target * _MS))
        self._update_subtitle(target)
        self.position_changed.emit(target)

    def position(self) -> float:
        if self.player is None:
            return 0.0
        return self.player.position() / _MS

    def duration(self) -> float:
        return self._duration

    def is_playing(self) -> bool:
        return (self.player is not None
                and self.player.playbackState()
                == QMediaPlayer.PlaybackState.PlayingState)

    def step(self, seconds: float) -> None:
        """Lùi hoặc tiến một khoảng so với vị trí hiện tại."""
        self.seek(self.position() + seconds)

    def nudge_back(self, big: bool = False) -> None:
        self.step(-(_SEEK_BIG_STEP_S if big else _SEEK_STEP_S))

    def nudge_forward(self, big: bool = False) -> None:
        self.step(_SEEK_BIG_STEP_S if big else _SEEK_STEP_S)

    def previous_segment(self) -> None:
        """Về đầu câu trước."""
        index = self._segment_index(self.position() - 0.25)
        if index > 0:
            self.seek(self._starts[index - 1])
        elif self._starts:
            self.seek(self._starts[0])

    def next_segment(self) -> None:
        """Sang đầu câu sau."""
        index = self._segment_index(self.position())
        if index + 1 < len(self._starts):
            self.seek(self._starts[index + 1])

    def _on_volume(self, value: int) -> None:
        if self.audio is not None:
            self.audio.setVolume(value / 100)

    def _on_slider_pressed(self) -> None:
        self._seeking = True

    def _on_slider_released(self) -> None:
        self._seeking = False
        self.seek(self.slider.value() / _MS)

    # -- Cập nhật theo thời gian ---------------------------------------
    def _on_duration(self, milliseconds: int) -> None:
        self._duration = milliseconds / _MS
        self.slider.setRange(0, milliseconds)
        self._refresh_time()
        self.duration_changed.emit(self._duration)

    def _on_state(self, state) -> None:
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self.btn_play.setIcon(icons.pause(tokens.WARNING) if playing
                              else icons.play(tokens.SUCCESS))
        self.btn_play.setToolTip("Tạm dừng" if playing else "Phát")
        self._timer.start() if playing else self._timer.stop()
        self.state_changed.emit(playing)

    def _tick(self) -> None:
        """Chạy 25 lần mỗi giây khi đang phát để phụ đề bám sát lời."""
        current = self.position()
        if not self._seeking:
            self.slider.setValue(int(current * _MS))
        self._refresh_time()
        self._update_subtitle(current)
        self.position_changed.emit(current)

    def _refresh_time(self) -> None:
        self.time_label.setText(
            f"{format_duration(self.position())} / "
            f"{format_duration(self._duration)}")

    def _segment_index(self, seconds: float) -> int:
        """Chỉ số câu đang được đọc, tìm bằng phép tìm nhị phân."""
        if not self._starts:
            return -1
        return max(0, bisect.bisect_right(self._starts, seconds) - 1)

    def current_segment(self) -> dict | None:
        index = self._segment_index(self.position())
        return self._segments[index] if 0 <= index < len(self._segments) else None

    def set_overlay_enabled(self, enabled: bool) -> None:
        """Bật/tắt lớp chữ xem trước.

        Tắt khi video đang mở đã có phụ đề ghi thẳng vào hình — hiện thêm lớp
        chữ nữa là thành hai phụ đề chồng nhau.
        """
        self._overlay_enabled = enabled
        if not enabled:
            self.subtitle_item.setPlainText("")
        else:
            self._update_subtitle(self.position())

    def _update_subtitle(self, seconds: float) -> None:
        """Chữ đang hiện tại một thời điểm — đúng chữ sẽ ghi vào video.

        Dùng chung :func:`autodub.text.srt.split_for_display` với bước sinh
        tệp .srt, nên xem trước hiện đúng phần chữ đó (kể cả phụ đề viết
        riêng, cách ngắt dòng và chế độ viết hoa) chứ không phải nguyên câu.
        """
        from autodub.text.srt import split_for_display

        if not self._overlay_enabled:
            return
        index = self._segment_index(seconds)
        text = ""
        if 0 <= index < len(self._segments):
            segment = self._segments[index]
            if float(segment.get("end", 0.0)) >= seconds:
                s = self._style
                cues = split_for_display(
                    segment, self._text_field,
                    line_words=int(s["line_words"]),
                    max_lines=int(s["max_lines"]),
                    all_caps=bool(s["all_caps"]))
                # Tìm đúng cụm chữ khớp với vị trí hiện tại.
                # KHÔNG dùng for-else: nếu con trỏ đang ở khoảng trống giữa
                # hai cụm (ví dụ cuối câu trước khi hết segment), cụm cuối
                # cùng đã qua vẫn là lựa chọn tốt nhất để hiện — thay vì
                # nhảy ngược lên cụm đầu tiên gây nhấp nháy chữ.
                matched = None
                last_before = None
                for cue in cues:
                    if cue["start"] <= seconds <= cue["end"]:
                        matched = cue["text"]
                        break
                    if cue["start"] <= seconds:
                        last_before = cue["text"]
                if matched is not None:
                    text = matched
                elif last_before is not None:
                    text = last_before
                elif cues:
                    text = cues[0]["text"]
        if text != self.subtitle_item.toPlainText():
            self.subtitle_item.setPlainText(text)
            self._layout_subtitle()

    # -- Bố trí khung hình ---------------------------------------------
    def resizeEvent(self, event) -> None:  # noqa: N802 — theo quy ước của Qt
        super().resizeEvent(event)
        self._layout_scene()

    def _layout_scene(self) -> None:
        size = self.view.size()
        if self.video_item is not None:
            self.video_item.setSize(size)
        self.scene.setSceneRect(0, 0, size.width(), size.height())
        self.view.fitInView(self.scene.sceneRect(),
                            Qt.AspectRatioMode.KeepAspectRatio)
        self._restyle_subtitle()
        self._layout_subtitle()

    def _layout_subtitle(self) -> None:
        """Đặt chữ phụ đề đúng vị trí và lề mà kiểu phụ đề quy định."""
        rect = self.scene.sceneRect()
        if rect.height() <= 0:
            return
        self.subtitle_item.setTextWidth(max(100.0, rect.width() * 0.9))
        bounds = self.subtitle_item.boundingRect()
        margin = int(self._style["margin_v"]) * rect.height() / _ASS_PLAY_RES_Y
        position = str(self._style["position"])
        if position == "top":
            top = margin
        elif position == "middle":
            top = (rect.height() - bounds.height()) / 2
        else:
            top = rect.height() - bounds.height() - margin
        self.subtitle_item.setPos(QPointF(
            (rect.width() - bounds.width()) / 2, max(0.0, top)))

    # -- Cửa sổ phụ ----------------------------------------------------
    def open_fullscreen(self) -> None:
        """Xem toàn màn hình trong một cửa sổ riêng, bấm Esc để thoát."""
        self._open_detached(fullscreen=True)

    def open_pip(self) -> None:
        """Xem trong cửa sổ nhỏ luôn nổi trên cùng."""
        self._open_detached(fullscreen=False)

    def _open_detached(self, fullscreen: bool) -> None:
        from autodub_gui.video.detached import DetachedVideoWindow

        if self.player is None or not self._source:
            return
        if self._external_dialog is not None:
            self._external_dialog.close()
        window = DetachedVideoWindow(self.player, self, fullscreen=fullscreen,
                                     size=(_PIP_W, _PIP_H))
        window.closed.connect(self._on_detached_closed)
        self._external_dialog = window
        window.show_video()

    def _on_detached_closed(self) -> None:
        """Đưa hình ảnh về lại khung chính khi đóng cửa sổ phụ."""
        self._external_dialog = None
        if self.player is not None and self.video_item is not None:
            self.player.setVideoOutput(self.video_item)
            self._layout_scene()

    def source_path(self) -> str:
        return self._source

    def cleanup(self) -> None:
        if self._external_dialog is not None:
            self._external_dialog.close()
        self.release()
