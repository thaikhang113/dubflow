"""Phần đọc lại giọng và xuất video của Trình chỉnh sửa.

Tách khỏi `editor_page.py` để mỗi tệp giữ được kích thước dễ đọc. Đây là một
lớp trộn: nó chỉ chứa hành vi, còn mọi widget đều do trang chính dựng.
"""
from __future__ import annotations

from dataclasses import replace

from autodub_gui.dub_constants import friendly_error
from autodub_gui.log_text import Narrator, error_line
from autodub_gui.run_state import REGISTRY, ActiveJob
from autodub_gui.system_open import open_file
from autodub_gui.ui.modal import ConfirmDialog
from autodub_gui.ui.toast import TOASTS


class VoiceAndExportMixin:
    """Các thao tác nghe thử, đọc lại giọng và xuất video."""

    # -- Nghe thử và đọc lại -------------------------------------------
    def _preview_voice(self, voice: str = "") -> None:
        values = self.voice_panel.values()
        settings = replace(self._settings_provider(),
                           voice_speed=values["voice_speed"])
        # Khoá nút ngay khi bấm, tránh bấm liên tục khi phải chờ tổng hợp.
        # finished signal sẽ mở lại (kết nối trong editor_page._build_panels).
        self.voice_panel.picker.set_preview_enabled(False)
        self._preview.play(settings, voice or self.voice_panel.picker.voice())

    def _resynth_one(self, seg_id: int) -> None:
        self._flush_edits()
        # Truyền seg_id vào force_ids để buộc đọc lại dù chỉ đổi giọng,
        # không sửa chữ (save_segment_texts sẽ trả [] nhưng force_ids bù lại).
        self._start_resynth({seg_id: self._text_of(seg_id)},
                            force_ids={seg_id})

    def _save_all_and_resynth(self) -> None:
        self._flush_edits()
        edits = {int(s["id"]): str(s.get(self._state.target.text_field, ""))
                 for s in self._segments}
        # Đổi sang giọng khác thì phải đọc lại TẤT CẢ các câu — không chỉ
        # những câu vừa sửa chữ — video mới đồng nhất một giọng.
        resynth_all = self.voice_panel.has_pending_voice_change()
        if resynth_all:
            confirmed, _ = ConfirmDialog.ask(
                self, "Đổi giọng cho cả video",
                f"Bạn vừa chọn giọng {self.voice_panel.picker.voice()}. Toàn "
                f"bộ {len(self._segments)} câu sẽ được đọc lại bằng giọng "
                "này để cả video cùng một giọng. Tiếp tục chứ?",
                confirm_label="Đọc lại toàn bộ",
                cancel_label="Khoan đã")
            if not confirmed:
                return
        # Câu chỉ đổi giọng riêng (không sửa chữ) cũng phải đọc lại.
        self._start_resynth(edits, resynth_all=resynth_all,
                            force_ids=set(self._dirty_ids))

    def _text_of(self, seg_id: int) -> str:
        segment = self._segment(seg_id)
        return str(segment.get(self._state.target.text_field, "")) if segment else ""

    def _render_settings(self):
        """Cài đặt dùng cho xuất video/xem thử: cài chung + tinh chỉnh dự án.

        Bảng Âm thanh và thanh Tốc độ đọc lưu giá trị riêng của dự án vào
        render_opts.json và hiển thị đúng trên giao diện — nên lượt xuất phải
        dùng đúng các giá trị đó, không phải giá trị chung trong .env.
        """
        audio = self.audio_panel.values()
        voice = self.voice_panel.values()
        return replace(
            self._settings_provider(),
            voice_postprocess=audio["voice_postprocess"],
            voice_target_lufs=audio["voice_target_lufs"],
            bg_duck_voice_db=audio["bg_duck_voice_db"],
            soft_timing_fit=audio["soft_timing_fit"],
            timing_max_drift_s=audio["timing_max_drift_s"],
            voice_speed=voice["voice_speed"],
        )

    # -- Khóa chéo ------------------------------------------------------
    def _busy_warn(self) -> bool:
        """True nếu đang đọc lại giọng hoặc đang xuất — hai việc này đụng
        cùng các tệp (dubbed_video.mp4, các đoạn giọng) nên cấm chạy chéo."""
        if (self._resynth_worker is not None
                and self._resynth_worker.isRunning()):
            TOASTS.warn("Đang đọc lại giọng, hãy đợi xong đã.")
            return True
        if (self._rebuild_worker is not None
                and self._rebuild_worker.isRunning()):
            TOASTS.warn("Đang xuất video, hãy đợi xong đã.")
            return True
        if (getattr(self, "_preview_seg_worker", None) is not None
                and self._preview_seg_worker.isRunning()):
            TOASTS.warn("Đang dựng đoạn xem thử, hãy đợi xong đã.")
            return True
        if (getattr(self, "_export_subs_file_worker", None) is not None
                and self._export_subs_file_worker.isRunning()):
            TOASTS.warn("Đang xuất phụ đề, hãy đợi xong đã.")
            return True
        if (getattr(self, "_export_audio_worker", None) is not None
                and self._export_audio_worker.isRunning()):
            TOASTS.warn("Đang xuất âm thanh, hãy đợi xong đã.")
            return True
        return False

    def _start_resynth(self, edits: dict[int, str],
                       resynth_all: bool = False,
                       force_ids: set[int] | None = None) -> None:
        from autodub_gui.workers import SaveAllWorker

        if self._busy_warn():
            return
        values = self.voice_panel.values()
        settings = replace(self._settings_provider(),
                           voice_speed=values["voice_speed"])
        # Đọc lại lẻ tẻ thì dùng giọng ĐANG CÓ trong video (tránh một câu nói
        # bằng giọng khác); đổi giọng cả video thì dùng giọng mới đã chọn.
        voice = (self.voice_panel.picker.voice() if resynth_all
                 else self.voice_panel.project_voice())
        worker = SaveAllWorker(settings, self._work_dir, edits,
                               self.target_key(), voice, self,
                               force_all=resynth_all,
                               force_ids=force_ids)
        # Chỉ coi giọng mới là "đã áp dụng" khi lần đọc lại này phủ đủ mọi
        # câu; đọc lại một câu lẻ bằng giọng mới thì video vẫn chưa đổi giọng.
        self._resynth_covers_voice = resynth_all
        worker.seg_done.connect(
            lambda _sid, done, total: self.voice_panel.set_progress(done, total))
        worker.log.connect(self.log.append_log)
        worker.finished_ok.connect(self._on_resynth_done)
        worker.failed.connect(self._on_resynth_failed)
        worker.cancelled.connect(self._on_resynth_cancelled)
        self.log.setVisible(True)
        self.voice_panel.btn_resynth.set_loading(True, "Đang đọc lại")
        worker.finished.connect(
            lambda: self.voice_panel.btn_resynth.set_loading(False))
        self._resynth_worker = worker
        # Đọc lại giọng sẽ xóa dubbed_video.mp4 (bản cũ đã lỗi thời) — nhả
        # video ra trước, không thì Windows báo WinError 32 vì tệp đang mở.
        self._resynth_resume_pos = self.release_video()
        worker.start()

    def _on_resynth_cancelled(self) -> None:
        self.voice_panel.finish_progress("Đã dừng theo yêu cầu.")
        self.restore_video(getattr(self, "_resynth_resume_pos", None))
        self._resynth_resume_pos = None

    def _on_resynth_done(self, changed: list) -> None:
        self._dirty_ids.clear()
        self._structural_edit = False
        self._refresh_banner()
        self.restore_video(getattr(self, "_resynth_resume_pos", None))
        self._resynth_resume_pos = None
        # Đổi giọng cả video xong thì giọng mới thành giọng thật của dự án —
        # ghim lại vào render_opts để lần mở sau hiện đúng.
        if changed and getattr(self, "_resynth_covers_voice", False):
            self.voice_panel.mark_voice_applied()
            self._pin_project_voice(self.voice_panel.picker.voice())
        self.voice_panel.finish_progress(
            f"Đã đọc lại {len(changed)} câu. Bấm Xuất video để ghép vào phim."
            if changed else "Không có câu nào cần đọc lại.")
        TOASTS.success("Đã tạo xong giọng đọc mới.")

    def _pin_project_voice(self, voice: str) -> None:
        """Ghi tên giọng đã dùng thật vào tùy chọn của dự án."""
        from autodub.editor import load_render_opts, save_render_opts

        try:
            opts = load_render_opts(self._work_dir)
            opts["voice"] = voice
            save_render_opts(self._work_dir, opts)
        except OSError as e:
            TOASTS.warn(f"Không lưu được tên giọng của dự án: {e}")

    def _on_resynth_failed(self, message: str) -> None:
        self.voice_panel.finish_progress("")
        self.restore_video(getattr(self, "_resynth_resume_pos", None))
        self._resynth_resume_pos = None
        friendly = friendly_error(message)
        if friendly is not None:
            title, advice = friendly
            ConfirmDialog.show_error(self, title, advice, detail=message)
            return
        ConfirmDialog.show_error(
            self, "Không tạo được giọng đọc",
            "Có lỗi ngoài dự tính khi tạo giọng. Những câu đã xong vẫn được "
            "giữ lại, bạn có thể bấm đọc lại để tiếp tục.", detail=message)

    # -- Xuất video ----------------------------------------------------
    def _open_style_dialog(self) -> None:
        from autodub.media.subtitle import preset_style
        from autodub_gui.style_dialog import StyleDialog

        video = self._state.video_path if self._state else ""
        style = getattr(self, "_subtitle_style", None)
        if not style:
            # Chưa có kiểu riêng cho dự án: nếu bộ đang chọn trùng với bộ
            # trong Cài đặt thì lấy đủ tinh chỉnh từ đó (như lúc tạo dự
            # án), khác thì dùng bộ dựng sẵn.
            preset = self.export_panel.preset.current_key()
            try:
                from autodub.config import Settings
                settings = Settings.load()
                style = (settings.subtitle_style()
                         if preset == settings.subtitle_preset
                         else preset_style(preset))
            except Exception:  # noqa: BLE001 — cấu hình hỏng thì dùng bộ sẵn
                style = preset_style(preset)

        # Lấy câu phụ đề hiện đang hiện trong player làm chữ xem trước —
        # đúng hơn là placeholder "Xin chào, đây là phụ đề xem trước".
        preview_text = ""
        try:
            seg = self.player.current_segment()
            if seg is None and self._segments:
                seg = self._segments[0]
            if seg is not None:
                from autodub.text.srt import subtitle_text
                preview_text = subtitle_text(
                    seg, self._state.target.text_field) or ""
        except Exception:  # noqa: BLE001
            pass

        dialog = StyleDialog(video, style,
                             list(getattr(self, "_blur_regions", [])), self,
                             preview_text=preview_text)
        if not dialog.exec():
            return
        self._subtitle_style = dialog.style()
        # Tự chỉnh tay xong thì bộ kiểu không còn là bộ dựng sẵn nào nữa.
        self._subtitle_style["preset"] = "custom"
        self.export_panel.preset.set_key("custom")
        if video:
            self._blur_regions = dialog.regions()
        if self.export_panel.subtitle.current_key() != "burn":
            self.export_panel.subtitle.set_key("burn")
            TOASTS.info("Kiểu chữ tự chỉnh cần ghi thẳng vào hình, nên phụ đề "
                        "đã chuyển sang Ghi thẳng vào hình.")
        self._save_render_opts()
        self._apply_style_to_player()
        TOASTS.info("Bấm «Ghi lại phụ đề vào video» để thấy kiểu chữ mới trên "
                    "video ngay, không cần xuất lại cả phim.")

    def _export(self) -> None:
        from autodub_gui.workers import RebuildWorker

        if self._busy_warn():
            return
        if not self._work_dir:
            return
        self._flush_edits()
        if self.voice_panel.has_pending_voice_change():
            confirmed, _ = ConfirmDialog.ask(
                self, "Giọng mới chưa được áp dụng",
                f"Bạn đã chọn giọng {self.voice_panel.picker.voice()} nhưng "
                "chưa bấm «Lưu tất cả và đọc lại». Nếu xuất bây giờ, video "
                f"vẫn dùng giọng {self.voice_panel.project_voice()}.",
                kind="warning", confirm_label="Cứ xuất với giọng cũ",
                cancel_label="Để tôi đọc lại đã")
            if not confirmed:
                self._show_tab("voice")
                return
        if self._dirty_ids:
            confirmed, _ = ConfirmDialog.ask(
                self, "Còn câu chưa đọc lại",
                f"Bạn đã sửa {len(self._dirty_ids)} câu nhưng chưa tạo giọng "
                "mới cho chúng. Nếu xuất bây giờ, những câu đó vẫn dùng giọng "
                "cũ. Bạn muốn làm gì?",
                kind="warning", confirm_label="Cứ xuất video",
                cancel_label="Để tôi đọc lại đã")
            if not confirmed:
                self._show_tab("voice")
                return
        settings = self._render_settings()
        background = self.background_panel.values()
        worker = RebuildWorker(
            settings, self._work_dir, self.target_key(),
            self.voice_panel.project_voice(),
            background["bg_mode"], background["bg_duck_db"],
            self.export_panel.subtitle.current_key(),
            list(getattr(self, "_blur_regions", [])),
            getattr(self, "_subtitle_style", None), self)
        worker.log.connect(self.log.append_log)
        worker.finished_ok.connect(self._on_export_done)
        worker.failed.connect(self._on_export_failed)
        worker.cancelled.connect(self._on_export_cancelled)
        worker.finished.connect(lambda: self.export_panel.set_running(False))
        worker.progress.connect(self._on_progress_log)
        self.log.reset_log()
        self._narrator.reset()
        self.log.setVisible(True)
        self.export_panel.set_running(True)
        self.export_panel.set_status("Đang ghép âm thanh và hình ảnh…")
        self._rebuild_worker = worker
        # Nhả video đang mở: trình xuất sẽ ghi đè dubbed_video.mp4, mà trên
        # Windows tệp đang phát là tệp bị khóa (WinError 32).
        self._export_resume_pos = self.release_video()
        REGISTRY.start_job(
            ActiveJob(kind="rebuild", title=f"Xuất video {self._project.title}",
                      work_dir=self._work_dir),
            on_cancel=worker.cancel)
        worker.start()

    def _export_subtitles(self) -> None:
        """Ghi lại phụ đề vào video, giữ nguyên giọng đọc đã có.

        Đây là đường dùng khi bạn chỉ sửa chữ hoặc đổi kiểu chữ: chỉ vẽ lại
        chữ lên hình nên nhanh hơn nhiều, và tuyệt đối không cần chạy lại
        quy trình từ đầu.
        """
        from autodub_gui.workers import SubtitleWorker

        if self._busy_warn():
            return
        if not self._work_dir:
            return
        self._flush_edits()
        if self.export_panel.subtitle.current_key() == "none":
            TOASTS.warn("Kiểu phụ đề đang là Không gắn phụ đề — hãy chọn "
                        "Ghi thẳng vào hình rồi bấm lại.")
            return
        worker = SubtitleWorker(
            self._render_settings(), self._work_dir, self.target_key(),
            self.export_panel.subtitle.current_key(),
            list(getattr(self, "_blur_regions", [])),
            getattr(self, "_subtitle_style", None), self)
        worker.log.connect(self.log.append_log)
        worker.finished_ok.connect(self._on_subtitles_done)
        worker.failed.connect(self._on_export_failed)
        worker.cancelled.connect(self._on_export_cancelled)
        worker.finished.connect(
            lambda: self.export_panel.set_running(False, subtitles_only=True))
        worker.progress.connect(self._on_progress_log)
        self.log.reset_log()
        self._narrator.reset()
        self.log.setVisible(True)
        self.export_panel.set_running(True, subtitles_only=True)
        self.export_panel.set_status("Đang vẽ lại phụ đề lên video…")
        self._rebuild_worker = worker
        # Nhả video: bước này ghi đè dubbed_video.mp4 đang mở trong trình phát.
        self._export_resume_pos = self.release_video()
        REGISTRY.start_job(
            ActiveJob(kind="rebuild",
                      title=f"Ghi phụ đề {self._project.title}",
                      work_dir=self._work_dir),
            on_cancel=worker.cancel)
        worker.start()

    def _preview_segment(self) -> None:
        """Dựng nhanh vài giây quanh câu đang chọn để xem thử trước khi xuất.

        Không đụng tới dubbed_video.mp4 nên không cần nhả video đang phát;
        tệp xem thử mở bằng trình phát của hệ thống.
        """
        from autodub_gui.workers import SegmentPreviewWorker

        if self._busy_warn():
            return
        if not self._work_dir:
            return
        self._flush_edits()
        seg_id = self.subtitles.selected_id()
        if seg_id <= 0:
            seg = self.player.current_segment()
            if seg is None and self._segments:
                seg = self._segments[0]
            seg_id = int(seg.get("id", 0)) if seg else 0
        if seg_id <= 0:
            TOASTS.warn("Chưa có câu nào để xem thử — hãy chọn một câu ở "
                        "mục Phụ đề.")
            return
        if self._dirty_ids and seg_id in self._dirty_ids:
            TOASTS.warn(f"Câu {seg_id} vừa sửa chữ nhưng chưa đọc lại giọng — "
                        "đoạn xem thử sẽ dùng giọng cũ.")
        background = self.background_panel.values()
        worker = SegmentPreviewWorker(
            self._render_settings(), self._work_dir, seg_id,
            self.target_key(), background["bg_mode"],
            background["bg_duck_db"],
            self.export_panel.subtitle.current_key(),
            getattr(self, "_subtitle_style", None), self)
        worker.log.connect(self.log.append_log)
        worker.finished_ok.connect(self._on_preview_seg_done)
        worker.failed.connect(self._on_preview_seg_failed)
        worker.finished.connect(
            lambda: self.export_panel.set_previewing(False))
        self.export_panel.set_previewing(True)
        self.export_panel.set_status(
            f"Đang dựng đoạn xem thử quanh câu {seg_id}…")
        self._preview_seg_worker = worker
        worker.start()

    def _on_preview_seg_done(self, path: str) -> None:
        self.export_panel.set_status("Đã dựng xong đoạn xem thử.")
        TOASTS.success("Đoạn xem thử đã sẵn sàng.", action_label="Mở xem",
                       on_action=lambda: open_file(path))
        open_file(path)

    def _on_preview_seg_failed(self, message: str) -> None:
        self.export_panel.set_status("")
        ConfirmDialog.show_error(
            self, "Không dựng được đoạn xem thử",
            "Có lỗi khi dựng đoạn xem thử. Bạn vẫn có thể xuất cả video như "
            "bình thường.", detail=message)

    def _on_subtitles_done(self, path: str) -> None:
        self._sub_dirty_ids.clear()
        self._refresh_banner()
        REGISTRY.finish_job(True)
        self.export_panel.set_status(f"Đã ghi phụ đề vào: {path}")
        TOASTS.success("Phụ đề mới đã nằm trong video.",
                       action_label="Mở video",
                       on_action=lambda: open_file(path))
        self._reload_player(path)

    def _on_export_done(self, path: str) -> None:
        self._sub_dirty_ids.clear()
        self._refresh_banner()
        REGISTRY.finish_job(True)
        self.export_panel.set_status(f"Đã xuất xong: {path}")
        TOASTS.success("Đã xuất video mới.", action_label="Mở video",
                       on_action=lambda: open_file(path))
        self._reload_player(path)
        # Lượt xuất vừa ghi lại audio_vi_full.wav (và có thể cả nhạc nền đã
        # làm chậm) — nạp lại dạng sóng để band Giọng AI khớp bản mới.
        self._load_waveform()
        # Chụp bản vừa xuất vào lịch sử, rồi refresh danh sách.
        try:
            from autodub.editor import record_export_snapshot
            record_export_snapshot(self._work_dir)
        except Exception:
            pass
        self.export_panel.refresh_history(self._work_dir)

    def _reload_player(self, path: str) -> None:
        """Mở lại video kết quả để bạn xem ngay phụ đề vừa ghi."""
        self._export_resume_pos = None
        self.player.open(path)
        self.player.set_segments(self._segments,
                                 self._state.target.text_field)
        # Video vừa xuất có chữ ghi thẳng vào hình thì tắt lớp chữ xem trước,
        # tránh hai phụ đề chồng nhau.
        self._sync_overlay(path)

    def _on_export_cancelled(self) -> None:
        self.export_panel.set_status("Đã dừng theo yêu cầu.")
        self.restore_video(getattr(self, "_export_resume_pos", None))
        self._export_resume_pos = None

    def _on_export_failed(self, message: str) -> None:
        text, level = error_line(message)
        self.log.append_log(text, level)
        REGISTRY.finish_job(False, message[:120])
        self.export_panel.set_status("")
        self.restore_video(getattr(self, "_export_resume_pos", None))
        self._export_resume_pos = None
        friendly = friendly_error(message)
        if friendly is not None:
            title, advice = friendly
            ConfirmDialog.show_error(self, title, advice, detail=message)
            return
        ConfirmDialog.show_error(
            self, "Không xuất được video",
            "Có lỗi ngoài dự tính khi ghép video. Phần giọng đọc đã tạo vẫn "
            "còn nguyên, bạn có thể thử xuất lại.", detail=message)

    def _on_progress_log(self, event) -> None:
        """Kể lại tiến trình bằng lời thường vào Nhật ký."""
        result = self._narrator.narrate(event)
        if result is None:
            return
        text, level, is_progress = result
        self.log.append_log(text, level, is_progress=is_progress)

    # -- Xuất riêng phụ đề / âm thanh / lịch sử ---------------------------

    def _export_srt_file(self) -> None:
        """Xuất tệp .srt ra máy tính người dùng chọn."""
        from PySide6.QtWidgets import QFileDialog

        if not self._work_dir or not self._state:
            return
        title = (self._project.title or "subtitle").replace(" ", "_")
        path, _ = QFileDialog.getSaveFileName(
            self, "Lưu phụ đề SRT", f"{title}.srt",
            "SubRip subtitle (*.srt)")
        if not path:
            return
        self._run_export_subs_worker(path, "srt")

    def _export_ass_file(self) -> None:
        """Xuất tệp .ass (kiểu karaoke) ra máy tính người dùng chọn."""
        from PySide6.QtWidgets import QFileDialog

        if not self._work_dir or not self._state:
            return
        title = (self._project.title or "subtitle").replace(" ", "_")
        path, _ = QFileDialog.getSaveFileName(
            self, "Lưu phụ đề ASS", f"{title}.ass",
            "Advanced SubStation Alpha (*.ass)")
        if not path:
            return
        self._run_export_subs_worker(path, "ass")

    def _run_export_subs_worker(self, output_path: str,
                                subs_format: str) -> None:
        from autodub.workdir import data_path

        from autodub_gui.workers import ExportSubsFileWorker

        if self._busy_warn():
            return

        merge_dir = data_path(self._work_dir, "segments")
        worker = ExportSubsFileWorker(
            list(self._segments), self._work_dir, output_path,
            self._state.target.text_field,
            getattr(self, "_subtitle_style", None),
            subs_format=subs_format,
            merge_dir=merge_dir,
            parent=self)
        worker.log.connect(self.log.append_log)
        worker.finished_ok.connect(self._on_export_subs_file_done)
        worker.failed.connect(
            lambda msg: ConfirmDialog.show_error(
                self, "Không xuất được phụ đề", msg))
        worker.start()
        self._export_subs_file_worker = worker
        self.export_panel.set_status(
            f"Đang xuất phụ đề {'ASS' if subs_format == 'ass' else 'SRT'}…")

    def _on_export_subs_file_done(self, path: str) -> None:
        self.export_panel.set_status(f"Đã xuất: {path}")
        TOASTS.success(
            f"Đã lưu phụ đề.", action_label="Mở tệp",
            on_action=lambda: open_file(path))

    def _export_audio_mp3(self) -> None:
        """Xuất âm thanh lồng tiếng thành MP3."""
        from PySide6.QtWidgets import QFileDialog

        from autodub_gui.workers import ExportAudioWorker

        if not self._work_dir:
            return
        if self._busy_warn():
            return
        title = (self._project.title or "audio").replace(" ", "_")
        path, _ = QFileDialog.getSaveFileName(
            self, "Lưu âm thanh lồng tiếng MP3", f"{title}_vi.mp3",
            "MP3 audio (*.mp3)")
        if not path:
            return
        worker = ExportAudioWorker(self._work_dir, path, parent=self)
        worker.log.connect(self.log.append_log)
        worker.finished_ok.connect(self._on_export_audio_done)
        worker.failed.connect(
            lambda msg: ConfirmDialog.show_error(
                self, "Không xuất được âm thanh", msg))
        worker.start()
        self._export_audio_worker = worker
        self.export_panel.set_status("Đang chuyển đổi âm thanh thành MP3…")

    def _on_export_audio_done(self, path: str) -> None:
        self.export_panel.set_status(f"Đã xuất: {path}")
        TOASTS.success(
            "Đã lưu âm thanh MP3.", action_label="Mở tệp",
            on_action=lambda: open_file(path))
