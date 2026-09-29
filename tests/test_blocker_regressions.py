"""Hồi quy cho các lỗi CHẶN đã xác nhận ở tầng media (t2) và runtime (t3).

Mỗi bài khoá đúng một hành vi đã gây hỏng thật trên máy này; ghi rõ số hiệu
phát hiện để lần sau không ai "sửa lùi".
"""
from __future__ import annotations

import http.client
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from autodub.cancel import cancel_processes
from autodub.media import downloader
from autodub.progress import PipelineCancelled


# --------------------------------------------------------------------------- #
# M1/M8 — phân loại lỗi tải: chuỗi thật của sự cố Bilibili 1080p phải là TẠM THỜI
# --------------------------------------------------------------------------- #

#: Nguyên văn hai chuỗi lỗi của sự cố "975 bytes read, 469233162 more expected".
REAL_INCOMPLETE = (
    "ERROR: [download] Got error: 975 bytes read, 469233162 more expected. "
    "Giving up after 5 retries"
)
REAL_CONNECTION_BROKEN = (
    "('Connection broken: IncompleteRead(975 bytes read, 469233162 more "
    "expected)', IncompleteRead(975 bytes read, 469233162 more expected))"
)


def test_real_bilibili_error_strings_are_transient():
    """Hai chuỗi lỗi thật phải được coi là tạm thời — regex cũ trả False."""
    assert downloader.is_transient_download_error(RuntimeError(REAL_INCOMPLETE))
    assert downloader.is_transient_download_error(
        RuntimeError(REAL_CONNECTION_BROKEN))


def test_incomplete_read_exception_is_transient():
    exc = http.client.IncompleteRead(b"x" * 10, 500)
    assert downloader.is_transient_download_error(exc)


def test_network_exceptions_are_transient():
    assert downloader.is_transient_download_error(ConnectionResetError("reset"))
    assert downloader.is_transient_download_error(TimeoutError("timed out"))


def test_http_status_classification():
    assert downloader.is_transient_download_error(RuntimeError("HTTP Error 503"))
    assert downloader.is_transient_download_error(RuntimeError("HTTP Error 412"))
    # Vĩnh viễn: thử lại chỉ tốn thời gian.
    assert not downloader.is_transient_download_error(RuntimeError("HTTP Error 403"))
    assert not downloader.is_transient_download_error(
        RuntimeError("ERROR: Video unavailable"))


def test_extract_info_retries_connection_broken(monkeypatch):
    """Lần đứt kết nối đầu tiên KHÔNG được kết thúc job."""
    calls = []

    class Ydl:
        def extract_info(self, url, download):
            calls.append(url)
            if len(calls) == 1:
                raise RuntimeError(REAL_CONNECTION_BROKEN)
            return {"id": "BV-ok"}

    sleeps = []
    monkeypatch.setattr(downloader.time, "sleep", sleeps.append)

    result = downloader._extract_info_with_retry(Ydl(), "https://bilibili.test",
                                                 attempts=3)

    assert result["id"] == "BV-ok"
    assert len(calls) == 2
    assert sleeps == [2]


# --------------------------------------------------------------------------- #
# M2 — douyin: tải thiếu phải NỔ, không được os.replace() rồi báo thành công
# --------------------------------------------------------------------------- #

class _FakeResponse:
    def __init__(self, body: bytes, declared: int):
        self._body = body
        self.headers = {"Content-Length": str(declared),
                        "Content-Type": "video/mp4"}

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size=0):
        for start in range(0, len(self._body), chunk_size or len(self._body)):
            yield self._body[start:start + (chunk_size or len(self._body))]


def _mp4_bytes(size: int) -> bytes:
    return b"\x00\x00\x00\x18ftypisom" + b"\x00" * (size - 16)


def test_download_stream_rejects_truncated_body(monkeypatch, tmp_path):
    from autodub.media import douyin

    body = _mp4_bytes(200_000)
    monkeypatch.setattr(
        douyin, "_requests_client",
        lambda _cookies=None: type("C", (), {
            "get": lambda *_a, **_k: _FakeResponse(body, 1_000_000)})())

    dest = tmp_path / "video.mp4"
    with pytest.raises(RuntimeError, match="closed the connection early"):
        douyin._download_stream("https://cdn.test/v.mp4", dest)

    assert not dest.exists()
    assert not Path(str(dest) + ".part").exists()


def test_download_stream_accepts_complete_body(monkeypatch, tmp_path):
    from autodub.media import douyin

    body = _mp4_bytes(200_000)
    monkeypatch.setattr(
        douyin, "_requests_client",
        lambda _cookies=None: type("C", (), {
            "get": lambda *_a, **_k: _FakeResponse(body, len(body))})())

    dest = tmp_path / "video.mp4"
    size = douyin._download_stream("https://cdn.test/v.mp4", dest)

    assert size == len(body)
    assert dest.read_bytes() == body


# --------------------------------------------------------------------------- #
# M4/R7 — retry_failed giữ nguyên thư mục làm việc cũ (không mất .part)
# --------------------------------------------------------------------------- #

def test_retry_failed_keeps_work_dir(tmp_path):
    from autodub.config import Settings
    from autodub.openclaw_tool import handle

    queue = tmp_path / "queue"
    work_dir = tmp_path / "work" / "001"
    work_dir.mkdir(parents=True)
    partial = work_dir / "video.mp4.part"
    partial.write_bytes(b"x" * 1024)

    submitted = handle({
        "action": "submit",
        "links": ["https://example.com/a"],
        "options": {"translate_enabled": False},
    }, queue_root=str(queue), settings=Settings())
    batch_id = submitted["batch_id"]
    manifest_path = queue / "batches" / f"{batch_id}.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["jobs"][0]["request"]["output_dir"] = str(work_dir)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False),
                             encoding="utf-8")

    job_id = manifest["job_ids"][0]
    status_path = queue / "status" / f"{job_id}.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    status.update({"status": "failed", "error": "Connection broken"})
    status_path.write_text(json.dumps(status, ensure_ascii=False),
                           encoding="utf-8")

    result = handle({"action": "retry_failed", "batch_id": batch_id},
                    queue_root=str(queue), settings=Settings())

    assert result["ok"] is True
    assert len(result["job_ids"]) == 1
    replacement = json.loads(
        (queue / "inbox" / f"{result['job_ids'][0]}.json").read_text(
            encoding="utf-8"))
    assert replacement["request"]["output_dir"] == str(work_dir)
    assert replacement["request"]["url"] == "https://example.com/a"
    assert partial.exists()          # .part đã tải dở vẫn còn nguyên


def test_retry_failed_retries_translate_pending(tmp_path):
    """translate_pending là trạng thái chờ, phải có đường thoát."""
    from autodub.config import Settings
    from autodub.openclaw_tool import handle

    queue = tmp_path / "queue"
    submitted = handle({
        "action": "submit",
        "links": ["https://example.com/a"],
        "options": {"translate_enabled": False},
    }, queue_root=str(queue), settings=Settings())
    batch_id = submitted["batch_id"]
    manifest = json.loads(
        (queue / "batches" / f"{batch_id}.json").read_text(encoding="utf-8"))
    job_id = manifest["job_ids"][0]
    status_path = queue / "status" / f"{job_id}.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    status.update({"status": "translate_pending", "percent": 100})
    status_path.write_text(json.dumps(status, ensure_ascii=False),
                           encoding="utf-8")

    result = handle({"action": "retry_failed", "batch_id": batch_id},
                    queue_root=str(queue), settings=Settings())

    assert len(result["job_ids"]) == 1
    assert result["job_ids"][0] != job_id


def test_cancel_does_not_raise_when_status_file_missing(tmp_path):
    """Job kẹt ở inbox/ chưa có status: cancel phải chạy, không ném lỗi."""
    from autodub.config import Settings
    from autodub.openclaw_tool import handle

    queue = tmp_path / "queue"
    submitted = handle({
        "action": "submit",
        "links": ["https://example.com/a"],
        "options": {"translate_enabled": False},
    }, queue_root=str(queue), settings=Settings())
    batch_id = submitted["batch_id"]
    manifest = json.loads(
        (queue / "batches" / f"{batch_id}.json").read_text(encoding="utf-8"))
    for job_id in manifest["job_ids"]:
        (queue / "status" / f"{job_id}.json").unlink()

    result = handle({"action": "cancel", "batch_id": batch_id},
                    queue_root=str(queue), settings=Settings())

    assert result["ok"] is True
    # Job đã an vị ngay tại chỗ, và API phải NÓI ĐÚNG như vậy (t10).
    assert result["cancelled"] == manifest["job_ids"]
    assert result["still_running"] == []


# --------------------------------------------------------------------------- #
# R4 — URL rác phải bị từ chối ngay tại biên, không tạo batch
# --------------------------------------------------------------------------- #

def test_submit_rejects_non_url_links(tmp_path):
    from autodub.config import Settings
    from autodub.openclaw_tool import handle

    queue = tmp_path / "queue"
    with pytest.raises(ValueError, match="Link không hợp lệ"):
        handle({"action": "submit", "links": ["not a url"], "options": {}},
               queue_root=str(queue), settings=Settings())

    assert not list((queue / "batches").glob("*.json")) if (
        queue / "batches").exists() else True


def test_submit_rejects_non_http_scheme(tmp_path):
    from autodub.config import Settings
    from autodub.openclaw_tool import handle

    with pytest.raises(ValueError, match="Link không hợp lệ"):
        handle({"action": "submit", "links": ["ftp://example.com/a"]},
               queue_root=str(tmp_path / "queue"), settings=Settings())


def test_submit_keeps_valid_links(tmp_path):
    from autodub.config import Settings
    from autodub.openclaw_tool import handle

    result = handle({
        "action": "submit",
        "links": ["https://example.com/a", "http://example.com/b"],
        "options": {},
    }, queue_root=str(tmp_path / "queue"), settings=Settings())

    assert result["ok"] is True
    assert result["status"] == "queued"


# --------------------------------------------------------------------------- #
# R5 — batch không tồn tại phải là 404, không phải 400
# --------------------------------------------------------------------------- #

def test_missing_batch_raises_batch_not_found(tmp_path):
    from autodub.config import Settings
    from autodub.openclaw_tool import BatchNotFound, handle

    with pytest.raises(BatchNotFound):
        handle({"action": "status", "batch_id": "batch-nope"},
               queue_root=str(tmp_path / "queue"), settings=Settings())


def test_http_missing_batch_is_404(tmp_path):
    import urllib.error
    import urllib.request

    from autodub.openclaw_runtime import OpenClawRuntime

    runtime = OpenClawRuntime(data_dir=tmp_path)
    runtime.start(worker=False)
    try:
        request = urllib.request.Request(
            runtime.endpoint + "/v1/batches/batch-nope",
            headers={"Authorization": f"Bearer {runtime.token}"})
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            urllib.request.urlopen(request, timeout=3)
        assert excinfo.value.code == 404
    finally:
        runtime.stop()


# --------------------------------------------------------------------------- #
# R1 — thay giọng im lặng: phải để lại WARNING trong log
# --------------------------------------------------------------------------- #

def test_resolve_logs_when_voice_is_substituted(tmp_path, caplog):
    from autodub.config import Settings
    from autodub.speech.tts import voices

    settings = Settings(vieneu_model_dir=str(tmp_path / "vieneu"))
    with caplog.at_level("WARNING", logger="autodub.voices"):
        resolved = voices.resolve(settings, "Pháº¡m TuyÃªn")

    assert resolved                       # vẫn trả về một giọng dùng được
    assert any("Pháº¡m TuyÃªn" in record.getMessage()
               for record in caplog.records), caplog.text


def test_resolve_is_silent_for_a_known_voice(tmp_path, caplog):
    from autodub.config import Settings
    from autodub.speech.tts import voices

    settings = Settings(vieneu_model_dir=str(tmp_path / "vieneu"))
    known = voices.catalog(settings)[0].name
    with caplog.at_level("WARNING", logger="autodub.voices"):
        assert voices.resolve(settings, known) == known
    assert not caplog.records


# --------------------------------------------------------------------------- #
# R2 — CLI không được chết vì console Windows cp1252
# --------------------------------------------------------------------------- #

def test_cli_survives_cp1252_stdout(tmp_path):
    """Console Windows mặc định là cp1252: in kết quả có tiếng Việt không
    được làm tiến trình chết (trước đây exit code 1, stdout cụt)."""
    payload_path = tmp_path / "payload.json"
    payload_path.write_text(json.dumps({
        "action": "prepare",
        "text": "Làm video này https://example.com/a",
    }), encoding="utf-8")
    out_path = tmp_path / "stdout.txt"
    script = (
        "import sys, io;"
        "sys.stdout = open(sys.argv[2], 'w', encoding='cp1252');"
        "sys.stdin = io.StringIO("
        "    open(sys.argv[1], encoding='utf-8').read());"
        "sys.argv = ['openclaw_tool'];"
        "from autodub.openclaw_tool import main;"
        "raise SystemExit(main())"
    )
    # Giải mã phía cha bằng utf-8: log của con có thể chứa byte ngoài cp1252,
    # và lỗi giải mã ở luồng đọc sẽ biến stderr thành None (che mất kết quả).
    proc = subprocess.run(
        [sys.executable, "-c", script, str(payload_path), str(out_path)],
        cwd=str(Path(__file__).resolve().parents[1]),
        capture_output=True, encoding="utf-8", errors="replace", timeout=120)

    assert proc.returncode == 0, proc.stderr
    assert "UnicodeEncodeError" not in proc.stderr
    result = json.loads(out_path.read_text(encoding="utf-8"))
    assert result["ok"] is True
    assert result["links"] == ["https://example.com/a"]


# --------------------------------------------------------------------------- #
# R6 — tắt ứng dụng không phải "người dùng hủy"
# --------------------------------------------------------------------------- #

def test_watch_cancel_reports_shutdown_reason(tmp_path):
    from autodub.remote_worker import _watch_cancel

    cancel_event = threading.Event()
    stop_event = threading.Event()
    stop_event.set()
    reason_box = ["user"]

    _watch_cancel(tmp_path, "job-1", cancel_event, stop_event, None, reason_box)

    assert cancel_event.is_set()
    assert reason_box[0] == "shutdown"


def test_watch_cancel_reports_user_reason(tmp_path):
    from autodub.remote_worker import _watch_cancel

    marker = tmp_path / "cancel" / "job-1"
    marker.parent.mkdir(parents=True)
    marker.write_text("", encoding="ascii")
    cancel_event = threading.Event()
    reason_box = ["user"]

    _watch_cancel(tmp_path, "job-1", cancel_event, None, None, reason_box)

    assert reason_box[0] == "user"


def test_interrupted_batch_is_retryable_and_not_running() -> None:
    """Batch bị app tắt giữa chừng phải hiện là \"Tạm dừng\" (không phải
    \"Đang chạy\" mãi) và có nút Thử lại — đây là đường thoát duy nhất.

    Ca thật: tắt app khi job đang chạy, mở lại thì batch kẹt ở \"Đang chạy\"
    vĩnh viễn, không có nút nào bấm được.
    """
    from autodub.openclaw_tool import _aggregate_status

    assert _aggregate_status([{"status": "interrupted"}]) == "interrupted"
    assert _aggregate_status(
        [{"status": "interrupted"}, {"status": "cancelled"}]) == "interrupted"
    assert _aggregate_status(
        [{"status": "interrupted"}, {"status": "failed"}]) == "failed"
    # "interrupted" một mình không được coi là còn chạy.
    assert _aggregate_status([{"status": "interrupted"}]) != "running"


def test_gui_offers_retry_for_interrupted_batch() -> None:
    """openclaw_page phải có nhãn + nút Thử lại cho trạng thái mới."""
    import inspect

    from autodub_gui.pages import openclaw_page

    assert openclaw_page.OpenClawPage._status_label("interrupted") == "Tạm dừng"
    assert openclaw_page.OpenClawPage._status_label("translate_pending") \
        == "Chờ dịch"
    source = inspect.getsource(openclaw_page.OpenClawPage._refresh_batches)
    assert "\"interrupted\"" in source
    assert "retry-failed" in source


# --------------------------------------------------------------------------- #
# R18 — CỜ HỦY TOÀN CỤC rò rỉ sang lượt chạy sau (lỗi chặn nặng nhất tìm được)
# --------------------------------------------------------------------------- #

def test_global_cancel_flag_would_break_the_next_run(tmp_path):
    """Cơ chế lỗi: _REQUESTED là event TOÀN CỤC, không bao giờ tự tắt.

    Một khi nó bật, mọi run_registered() sau đó ném PipelineCancelled ngay —
    kể cả ở tiến trình GUI vẫn sống. Bài này khoá CƠ CHẾ để bản sửa bên dưới
    có nghĩa.
    """
    from autodub.cancel import clear_cancel_request, run_registered

    clear_cancel_request()
    try:
        cancel_processes()
        with pytest.raises(PipelineCancelled):
            run_registered([sys.executable, "-c", "pass"],
                           capture_output=True, text=True, timeout=30)
    finally:
        clear_cancel_request()


def test_pipeline_crash_does_not_leak_global_cancel_flag(tmp_path):
    """Pipeline đổ giữa chừng KHÔNG được bật cờ hủy toàn cục.

    Ca thật: một lượt pipeline lỗi (đĩa đầy khi lưu transcript) bật cờ toàn
    cục qua cancel_processes() không scope; MỌI lượt chạy sau trong cùng
    tiến trình GUI chết ngay ở bước kiểm tra hủy đầu tiên.
    """
    from autodub.cancel import clear_cancel_request, is_cancel_requested
    from autodub.config import Settings
    from autodub.pipeline import DubPipeline, DubRequest

    clear_cancel_request()
    pipeline = DubPipeline(Settings(), progress=lambda _event: None,
                           cancel_event=threading.Event())

    class _Future:
        def cancel(self):
            pass

        def add_done_callback(self, _cb):
            pass

    pipeline._active_bg_future = _Future()
    pipeline.last_work_dir = ""

    def boom(_req):
        raise RuntimeError("disk full")

    pipeline._run_impl = boom
    with pytest.raises(RuntimeError, match="disk full"):
        pipeline.run(DubRequest(file_path=str(tmp_path / "video.mp4")))

    assert not is_cancel_requested(), (
        "pipeline.run() đổ đã bật cờ hủy TOÀN CỤC — lượt chạy sau sẽ chết ngay")


def test_gui_workers_clear_global_cancel_flag_at_run_start() -> None:
    """Mọi worker GUI phải xoá cờ toàn cục ở đầu run(), không chỉ scope."""
    import inspect

    from autodub_gui import workers

    for worker in (workers.DubWorker, workers.BatchWorker,
                   workers.SaveAllWorker, workers.ExportAudioWorker):
        source = inspect.getsource(worker.run)
        assert "clear_cancel_request()" in source, (
            f"{worker.__name__}.run không xoá cờ hủy toàn cục")

# --------------------------------------------------------------------------- #
# M1 — 'read timed out' vẫn phải là lỗi TẠM THỜI (sự cố mất kết nối thật)
# --------------------------------------------------------------------------- #

def test_read_timed_out_is_transient():
    """'read timed out' là ca đứt kết nối thật, phải thử lại.

    Bản đầu của is_transient_download_error() chỉ nhận đúng mã HTTP trong
    danh sách nên chuỗi này trả False (đo thật: probe in ra False) — mất
    đúng một nửa ca đứt kết nối mà lỗi này sinh ra để cứu.
    """
    assert downloader.is_transient_download_error(RuntimeError("read timed out"))
    assert downloader.is_transient_download_error(
        RuntimeError("HTTPSConnectionPool(host='x', port=443): Read timed out."))


def test_http_412_keeps_retrying():
    """Giữ nguyên hành vi cũ: Bilibili 412 vẫn được thử lại."""
    assert downloader.is_transient_download_error(
        RuntimeError("Unable to download JSON metadata: HTTP Error 412"))

# --------------------------------------------------------------------------- #
# t7 — SÁU LỖI CHẶN CÒN LẠI CỦA VÒNG 1 (review-final xác nhận)
# --------------------------------------------------------------------------- #


def test_f2_default_voice_exists_in_catalog(tmp_path):
    """F2: DEFAULT_VOICE phải là tên CÓ THẬT trong danh mục giọng.

    Tên mặc định được ghi thẳng vào .env khi người dùng chưa chọn giọng
    (voice_library/settings_panels/new_project_steps đều lấy hằng số này),
    nên một cái tên không tồn tại làm mọi lượt chạy in cảnh báo rồi âm thầm
    đổi sang giọng khác.
    """
    from autodub.config import Settings
    from autodub.speech.tts import voices
    from autodub.speech.tts.capcut_catalog import DEFAULT_CAPCUT_VOICE

    settings = Settings(vieneu_model_dir=str(tmp_path / "vieneu"))
    names = {v.name for v in voices.catalog(settings)}
    assert names, "danh mục rỗng: bộ giọng CapCut phải luôn có mặt"
    assert DEFAULT_CAPCUT_VOICE in names
    assert voices.DEFAULT_VOICE in names, (
        f"DEFAULT_VOICE={voices.DEFAULT_VOICE!r} không có trong danh mục")
    # Và vì nó có thật, resolve() không bao giờ phải rơi qua nó.
    assert voices.resolve(settings, None) == voices.DEFAULT_VOICE


def test_f2_default_voice_exists_on_a_bare_machine(tmp_path, monkeypatch):
    """F2: giọng mặc định phải có NGAY trên máy chưa tải voices.zip.

    voice_library/settings_panels/new_project_steps ghi thẳng DEFAULT_VOICE
    vào .env khi người dùng chưa chọn giọng. Nếu nó chỉ có trong voices.zip
    (thứ phải tải thêm) thì máy mới cài sẽ ghi một cái tên không tồn tại và
    lượt chạy đầu tiên im lặng đổi sang giọng khác.
    """
    from autodub.config import Settings
    from autodub.speech.tts import voices
    from autodub.speech.tts.capcut_catalog import DEFAULT_CAPCUT_VOICE

    # Thư mục model rỗng = chưa tải voices.zip; chỉ còn Voice.json đóng gói.
    bare = Settings(vieneu_model_dir=str(tmp_path / "khong-co-gi"))
    capcut_only = {v.name for v in voices.catalog(bare)}
    assert capcut_only == set(__import__(
        "autodub.speech.tts.capcut_catalog", fromlist=["names"]).names())
    assert voices.DEFAULT_VOICE in capcut_only, (
        f"DEFAULT_VOICE={voices.DEFAULT_VOICE!r} không có trên máy chưa tải "
        "voices.zip — .env sẽ ghi một tên không tồn tại")
    assert DEFAULT_CAPCUT_VOICE in capcut_only


def test_f6_export_state_never_persists_null_ocr_enabled(tmp_path):
    """F6: render_opts.json không được nhận ocr_enabled = null.

    Job hàng đợi không truyền khoá này, nên req.ocr_enabled = None. Ghi
    thẳng None xuống đĩa thì lần đọc sau `bool(opts.get(...))` = False và
    OCR tự tắt im lặng ở mọi lượt sau trên cùng thư mục dự án.
    """
    from autodub.config import Settings
    from autodub.editor import load_render_opts, save_render_opts
    from autodub.pipeline import DubRequest, ocr_enabled_for_request

    work_dir = str(tmp_path)
    settings = Settings(ocr_enabled=True)
    request = DubRequest(file_path=str(tmp_path / "video.mp4"))
    assert request.ocr_enabled is None

    resolved = ocr_enabled_for_request(settings, request)
    assert resolved is True

    # Đúng đường đi của pipeline: giá trị ĐÃ RESOLVE được ghi xuống đĩa.
    save_render_opts(work_dir, {"ocr_enabled": resolved})
    opts = load_render_opts(work_dir)
    assert opts["ocr_enabled"] is True
    assert opts["ocr_enabled"] is not None

    # Và cấu hình tắt thì phải ghi false thật, không phải null.
    off_dir = tmp_path / "off"
    off_dir.mkdir()
    save_render_opts(str(off_dir), {
        "ocr_enabled": ocr_enabled_for_request(
            Settings(ocr_enabled=False), request),
    })
    assert load_render_opts(str(off_dir))["ocr_enabled"] is False


def test_f6_pipeline_writes_resolved_ocr_enabled(tmp_path, monkeypatch):
    """F6: chính pipeline.py phải ghi bool đã resolve, không ghi None."""
    import inspect

    from autodub import pipeline as pipeline_module

    source = inspect.getsource(pipeline_module)
    assert '"ocr_enabled": req.ocr_enabled' not in source, (
        "pipeline.py vẫn ghi thẳng req.ocr_enabled (có thể là None) xuống đĩa")
    assert source.count('"ocr_enabled": ocr_enabled_for_request(') >= 2

def _submit_batch(queue_root: str, *, links: list[str]) -> dict:
    """Gửi một batch qua đúng API công khai của openclaw_tool."""
    from autodub.config import Settings
    from autodub.openclaw_tool import handle

    result = handle(
        {"action": "submit", "links": links,
         "options": {"voice": "Thanh Lan", "subtitle_mode": "none"}},
        queue_root=queue_root,
        settings=Settings(),
    )
    assert result["ok"] is True
    return result

def _make_stuck_batch(tmp_path, *, age_s: float = 600.0, status: str = "running"):
    """Dựng đúng cảnh app bị giết cứng: job nằm trong running/, status 'running'."""
    import json
    import os
    import time

    queue_root = tmp_path / "queue"
    (queue_root / "running").mkdir(parents=True)
    batch = _submit_batch(str(queue_root),
                          links=["https://example.com/a.mp4"])
    job_id = batch["job_ids"][0]
    running_path = queue_root / "running" / f"{job_id}.json"
    inbox_path = queue_root / "inbox" / f"{job_id}.json"
    if inbox_path.exists():
        os.replace(inbox_path, running_path)
    status_path = queue_root / "status" / f"{job_id}.json"
    status_path.write_text(json.dumps({
        "job_id": job_id, "status": status, "step": "pipeline",
        "percent": 42, "detail": "", "error": "",
    }), encoding="utf-8")
    stamp = time.time() - age_s
    os.utime(status_path, (stamp, stamp))
    os.utime(running_path, (stamp, stamp))
    return queue_root, batch["batch_id"], job_id


def test_f3_running_batch_is_not_stuck_forever(tmp_path):
    """F3: batch kẹt ở 'running' sau khi app bị giết cứng phải cứu được.

    Không có worker nào sống, tệp job nằm trong running/ và không ai ghi
    trạng thái kết thúc: API cũ để batch đó kẹt VĨNH VIỄN ở 'running' vì
    'running' không nằm trong nhóm đáng thử lại và không đường nào đóng nó.
    """
    from autodub.openclaw_tool import handle, load_batch_status

    queue_root, batch_id, job_id = _make_stuck_batch(tmp_path)
    assert load_batch_status(str(queue_root), batch_id)["status"] == "running"

    # (a) cancel phải đóng được job mồ côi.
    handle({"action": "cancel", "batch_id": batch_id},
           queue_root=str(queue_root))
    after_cancel = load_batch_status(str(queue_root), batch_id)
    assert "running" not in after_cancel["counts"], (
        f"batch vẫn kẹt 'running' sau cancel: {after_cancel['counts']}")
    assert after_cancel["status"] != "running"
    assert after_cancel["jobs"][0]["status"] == "cancelled"


def test_f3_retry_failed_rescues_an_orphaned_running_job(tmp_path):
    """F3: retry-failed cũng phải cứu được job mồ côi ở 'running'."""
    from autodub.openclaw_tool import handle, load_batch_status

    queue_root, batch_id, job_id = _make_stuck_batch(tmp_path)
    result = handle({"action": "retry_failed", "batch_id": batch_id},
                    queue_root=str(queue_root))
    assert result["ok"] is True
    assert result["job_ids"], "retry-failed không tạo job thay thế nào"

    status = load_batch_status(str(queue_root), batch_id)
    assert "running" not in status["counts"], (
        f"vẫn kẹt 'running': {status['counts']}")


def test_f3_recover_orphans_on_startup_is_idempotent(tmp_path):
    """F3(b): quét running/ lúc khởi động, và chạy lần hai không đổi gì."""
    from autodub.openclaw_tool import (
        load_batch_status,
        recover_orphan_running,
    )

    queue_root, batch_id, job_id = _make_stuck_batch(tmp_path)
    recovered = recover_orphan_running(str(queue_root))
    assert recovered == [job_id]

    status = load_batch_status(str(queue_root), batch_id)
    assert status["status"] == "interrupted", (
        f"batch không được đánh dấu 'interrupted': {status['status']}")
    assert "running" not in status["counts"]
    assert status["jobs"][0]["detail"]

    # Idempotent: lần hai không còn gì để cứu.
    assert recover_orphan_running(str(queue_root)) == []


def test_f3_a_live_running_job_is_not_ripped_away(tmp_path):
    """F3: job ĐANG chạy thật (nhịp tim còn đập) không được coi là mồ côi.

    t10 đổi phép thử từ mtime sang nhịp tim + PID, nên bài này phải dựng
    một tệp nhịp tim thật thay vì chỉ 'chạm' tệp cho mới.
    """
    from autodub.openclaw_tool import load_batch_status, recover_orphan_running
    from autodub.remote_worker import cancel_job, job_is_live

    queue_root, batch_id, job_id = _make_stuck_batch(tmp_path, age_s=0.0)
    _install_heartbeat(queue_root, job_id)
    assert job_is_live(str(queue_root), job_id)
    assert recover_orphan_running(str(queue_root)) == []
    assert load_batch_status(str(queue_root), batch_id)["status"] == "running"

    cancel_job(str(queue_root), job_id)
    still = load_batch_status(str(queue_root), batch_id)
    assert still["status"] == "running", (
        "cancel đã đóng một job đang chạy thật — worker còn sống sẽ ghi đè")
    assert (queue_root / "cancel" / job_id).exists()

def _queue_with_one_job(tmp_path, job_id: str, payload) -> Path:
    queue_root = tmp_path / "queue"
    for sub in ("inbox", "running", "status", "cancel"):
        (queue_root / sub).mkdir(parents=True, exist_ok=True)
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    (queue_root / "inbox" / f"{job_id}.json").write_text(raw, encoding="utf-8")
    return queue_root


def _run_worker_until_settled(queue_root, job_id, *, timeout=10.0):
    """Chạy worker thật trên hàng đợi tạm; trả (trạng thái, worker)."""
    from autodub.config import Settings
    from autodub.remote_worker import run_worker

    stop = threading.Event()
    worker = threading.Thread(
        target=run_worker,
        args=(str(queue_root), Settings(), stop, 0.05),
        daemon=True,
    )
    worker.start()
    status_path = queue_root / "status" / f"{job_id}.json"
    deadline = time.time() + timeout
    settled = None
    while time.time() < deadline:
        if status_path.exists():
            settled = json.loads(status_path.read_text(encoding="utf-8"))
            if settled.get("status") in {"failed", "cancelled", "interrupted", "done"}:
                break
        if not worker.is_alive():
            break
        time.sleep(0.05)
    stop.set()
    worker.join(timeout=5)
    return settled, worker


def test_f4_reason_box_is_bound_before_anything_in_the_try_can_raise(
        tmp_path, monkeypatch):
    """F4: reason_box phải được gán TRƯỚC khối try của vòng xử lý job.

    Lệnh hủy ném ra từ một câu lệnh BÊN TRONG khối try nhưng TRƯỚC dòng gán
    reason_box (đọc/dựng request, dựng settings) làm nhánh
    'except PipelineCancelled' đọc biến chưa gán: worker chết bằng NameError
    và job ở lại 'running' vĩnh viễn.
    """
    import autodub.remote_worker as remote_worker

    job_id = "batch-abc-001"
    queue_root = _queue_with_one_job(tmp_path, job_id, {
        "job_id": job_id,
        "request": {"url": "https://example.com/a.mp4"},
    })

    def cancel_midway(payload, settings):
        raise PipelineCancelled("Video download cancelled")

    monkeypatch.setattr(remote_worker, "settings_from_payload", cancel_midway)

    status, worker = _run_worker_until_settled(queue_root, job_id)
    assert status is not None, "worker không ghi trạng thái nào"
    # Trước bản sửa: NameError thoát khỏi run_worker, trạng thái kẹt 'running'.
    assert status["status"] == "cancelled", (
        f"job kẹt ở {status['status']!r} thay vì 'cancelled'")
    assert not list((queue_root / "running").glob("*.json"))


def test_f4_a_broken_job_file_still_fails_cleanly(tmp_path):
    """F4 đối chứng: tệp job JSON hỏng vẫn phải ra 'failed', không làm chết worker."""
    job_id = "batch-abc-002"
    queue_root = _queue_with_one_job(tmp_path, job_id, "{ this is not json")
    status, worker = _run_worker_until_settled(queue_root, job_id)
    assert status is not None and status["status"] == "failed"
    assert not list((queue_root / "running").glob("*.json"))


def test_f4_a_non_object_job_payload_still_fails_cleanly(tmp_path):
    """F4 đối chứng: JSON hợp lệ nhưng không phải object -> 'failed'."""
    job_id = "batch-abc-003"
    queue_root = _queue_with_one_job(tmp_path, job_id, [1, 2, 3])
    status, worker = _run_worker_until_settled(queue_root, job_id)
    assert status is not None and status["status"] == "failed"


def test_f5_cancel_during_separation_raises_pipeline_cancelled(tmp_path, monkeypatch):
    """F5 CASE B: cờ hủy bật trong lúc tách nhạc -> PipelineCancelled LAN RA.

    Trước bản sửa, 'except Exception' bao ngoài nuốt PipelineCancelled và trả
    {'vocals': None, 'no_vocals': None} — người dùng bấm Dừng mà pipeline vẫn
    chạy tiếp bằng nền im lặng.
    """
    from autodub import cancel as cancel_mod
    from autodub.media import vocal_separator
    from autodub.progress import PipelineCancelled

    input_wav = tmp_path / "audio.wav"
    input_wav.write_bytes(b"RIFF0000WAVE")
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    def fake_gpu(input_wav, vocals_out, no_vocals_out, model_name):
        return False        # không có venv GPU -> rơi xuống đường CPU

    def fake_cpu(input_wav, vocals_out, no_vocals_out, model_name):
        # Đây là chỗ lệnh hủy thật sự nổi lên (run_registered).
        raise PipelineCancelled("Video download cancelled")

    monkeypatch.setattr(vocal_separator, "_run_demucs_gpu_worker", fake_gpu)
    monkeypatch.setattr(vocal_separator, "_run_demucs", fake_cpu)

    cancel_mod.clear_cancel_request()
    try:
        with pytest.raises(PipelineCancelled):
            vocal_separator.separate_vocals(
                str(input_wav), str(output_dir), demucs_cache=None)
    finally:
        cancel_mod.clear_cancel_request()


def test_f5_cancel_while_demucs_is_missing_still_raises(tmp_path, monkeypatch):
    """F5 CASE A: máy CHƯA cài Demucs thì lỗi là RuntimeError, không phải
    PipelineCancelled — nhánh 'except PipelineCancelled' không cứu được.

    Trên bản cài chưa setup .venv-demucs, MỌI video đi đúng đường này, nên
    nếu chỉ bắt PipelineCancelled thì người dùng mới vẫn bị nuốt lệnh hủy.
    """
    from autodub import cancel as cancel_mod
    from autodub.media import vocal_separator
    from autodub.progress import PipelineCancelled

    input_wav = tmp_path / "audio.wav"
    input_wav.write_bytes(b"RIFF0000WAVE")
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    monkeypatch.setattr(vocal_separator, "_run_demucs_gpu_worker",
                        lambda *a, **k: False)

    def missing_demucs(*args, **kwargs):
        # Đúng thứ _run_demucs ném khi demucs_venv_python() trả ''.
        raise RuntimeError("Chưa cài Demucs. Chạy lại first-run setup để cài "
                           ".venv-demucs.")

    monkeypatch.setattr(vocal_separator, "_run_demucs", missing_demucs)

    # Đối chứng 1: KHÔNG hủy -> vẫn fallback êm như cũ (không hồi quy).
    cancel_mod.clear_cancel_request()
    fell_back = vocal_separator.separate_vocals(
        str(input_wav), str(output_dir), demucs_cache=None)
    assert fell_back == {"vocals": None, "no_vocals": None}

    # Đối chứng 2: có hủy -> PHẢI ném, không được nuốt thành nền im lặng.
    from autodub.cancel import cancel_processes

    cancel_mod.clear_cancel_request()
    cancel_processes()
    try:
        with pytest.raises(PipelineCancelled):
            vocal_separator.separate_vocals(
                str(input_wav), str(output_dir), demucs_cache=None)
    finally:
        cancel_mod.clear_cancel_request()

# --------------------------------------------------------------------------- #
# F3 (t10) — phép thử 'còn sống' phải là TÍN HIỆU THẬT (nhịp tim + PID)
#
# Bản t7 dùng ngưỡng mtime 300s. Nó sai cả hai chiều và đã gây hỏng thật:
#   - job bị giết cứng 60 giây trước vẫn 'trông như đang sống' -> batch kẹt
#     'running' tới hết 5 phút, mà quét chỉ chạy lúc khởi động nên kẹt LUÔN;
#   - job đang chạy thật ở bước im lặng dài (>5 phút không sự kiện tiến trình,
#     Demucs/ASR video dài) bị coi là mồ côi, bị đổi thành 'interrupted' DÙ VẪN
#     ĐANG CHẠY, rồi retry-failed tạo job mới giữ nguyên output_dir -> hai job
#     ghi cùng một thư mục.
# --------------------------------------------------------------------------- #


def _install_heartbeat(queue_root, job_id, *, pid=None, age_s=0.0):
    """Ghi tệp nhịp tim cho job, giả lập tuổi và pid chỉ định."""
    from autodub.remote_worker import _heartbeat_path

    path = _heartbeat_path(Path(queue_root), job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "pid": os.getpid() if pid is None else pid,
        "ts": time.time() - age_s,
        "job_id": job_id,
    }), encoding="utf-8")
    return path


def test_f3_orphan_is_settled_one_minute_after_a_hard_kill(tmp_path):
    """F3 (t10) TIÊU CHÍ 1: giết cứng rồi mở lại sau 60 GIÂY -> đóng NGAY.

    Đây đúng là kịch bản t7 bỏ sót: tệp mới 60 giây tuổi nên ngưỡng mtime
    300s coi là 'còn sống', và vì quét chỉ chạy lúc khởi động nên batch kẹt
    vĩnh viễn ở 'running'.
    """
    from autodub.openclaw_tool import (
        handle,
        load_batch_status,
        recover_orphan_running,
    )

    # 60 giây: không có nhịp tim nào -> mồ côi, dù tệp còn 'mới'.
    queue_root, batch_id, job_id = _make_stuck_batch(tmp_path, age_s=60.0)
    assert not (queue_root / "running" / f"{job_id}.heartbeat").exists()
    assert load_batch_status(str(queue_root), batch_id)["status"] == "running"

    # (a) quét lúc mở app phải cứu được NGAY, không chờ 5 phút.
    assert recover_orphan_running(str(queue_root)) == [job_id]
    after_scan = load_batch_status(str(queue_root), batch_id)
    assert after_scan["status"] == "interrupted", (
        f"batch vẫn ở {after_scan['status']!r} sau khi quét")
    assert "running" not in after_scan["counts"]

    # (b) retry-failed phải cứu tiếp được từ 'interrupted'.
    retried = handle({"action": "retry_failed", "batch_id": batch_id},
                     queue_root=str(queue_root))
    assert retried["job_ids"], "retry-failed không cứu được job đã interrupted"
    assert "running" not in load_batch_status(
        str(queue_root), batch_id)["counts"]


def test_f3_cancel_settles_an_orphan_and_says_so(tmp_path):
    """F3 (t10) TIÊU CHÍ 1: cancel trên job mồ côi phải đóng thật, và báo đúng.

    API cũ LUÔN trả ok=True kèm cancelled=[...] bất kể cancel_job có thật sự
    đóng được job hay không, nên báo 'đã hủy xong' trong khi batch vẫn
    'running'.
    """
    from autodub.openclaw_tool import handle, load_batch_status

    queue_root, batch_id, job_id = _make_stuck_batch(tmp_path, age_s=60.0)
    result = handle({"action": "cancel", "batch_id": batch_id},
                    queue_root=str(queue_root))

    after = load_batch_status(str(queue_root), batch_id)
    assert "running" not in after["counts"], (
        f"cancel báo ok nhưng batch vẫn kẹt: {after['counts']}")
    assert after["jobs"][0]["status"] == "cancelled"
    # Nói đúng sự thật: đã đóng thật, không phải mới cắm cờ.
    assert result["cancelled"] == [job_id]
    assert result["still_running"] == []


def test_f3_a_long_silent_but_live_job_is_never_closed(tmp_path):
    """F3 (t10) TIÊU CHÍ 2: job SỐNG ở bước im lặng dài KHÔNG bị đóng oan.

    Sự kiện tiến trình cuối cách đây 600 giây (Demucs/ASR video dài) nhưng
    nhịp tim còn đập: ngưỡng mtime 300s coi đây là mồ côi và đóng oan.
    """
    from autodub.openclaw_tool import (
        load_batch_status,
        recover_orphan_running,
    )
    from autodub.remote_worker import cancel_job, job_is_live

    queue_root, batch_id, job_id = _make_stuck_batch(tmp_path, age_s=600.0)
    _install_heartbeat(queue_root, job_id)
    assert job_is_live(str(queue_root), job_id), "nhịp tim còn đập mà báo chết"

    assert recover_orphan_running(str(queue_root)) == [], (
        "quét đã đóng một job đang chạy thật")
    assert load_batch_status(str(queue_root), batch_id)["status"] == "running"

    # cancel trên job còn sống chỉ được CẮM CỜ, không ghi trạng thái kết thúc.
    assert cancel_job(str(queue_root), job_id) is False
    assert load_batch_status(str(queue_root), batch_id)["status"] == "running"
    assert (queue_root / "cancel" / job_id).exists()


def test_f3_retry_failed_never_creates_a_duplicate_for_a_live_job(tmp_path):
    """F3 (t10) TIÊU CHÍ 3: job ĐANG CHẠY THẬT thì retry-failed không được
    tạo job trùng và không được thêm tệp nào vào inbox/.

    Lỗi cũ: job bị đổi thành 'interrupted' dù vẫn đang chạy, rồi một job mới
    giữ nguyên request (kèm output_dir) được tạo -> hai job ghi cùng thư mục.
    """
    from autodub.openclaw_tool import handle, load_batch_status

    queue_root, batch_id, job_id = _make_stuck_batch(tmp_path, age_s=600.0)
    _install_heartbeat(queue_root, job_id)
    inbox_before = sorted(p.name for p in (queue_root / "inbox").glob("*.json"))

    result = handle({"action": "retry_failed", "batch_id": batch_id},
                    queue_root=str(queue_root))

    assert result["job_ids"] == [], (
        f"đã tạo job trùng cho job đang chạy: {result['job_ids']}")
    inbox_after = sorted(p.name for p in (queue_root / "inbox").glob("*.json"))
    assert inbox_after == inbox_before, (
        f"retry-failed đã thêm tệp vào inbox: {inbox_after}")
    # Job cũ phải NGUYÊN VẸN — không bị đổi thành 'interrupted'.
    assert load_batch_status(str(queue_root), batch_id)["status"] == "running"
    assert (queue_root / "status" / f"{job_id}.json").read_text(
        encoding="utf-8").find("interrupted") == -1


def test_f3_a_heartbeat_with_a_dead_pid_is_an_orphan(tmp_path):
    """F3 (t10): nhịp tim còn MỚI nhưng PID đã chết vẫn là mồ côi.

    Luồng worker chết vì lỗi để lại tệp nhịp tim vừa ghi; chỉ kiểm tra tuổi
    tệp là không đủ, phải kiểm tra cả tiến trình còn sống hay không.
    """
    import subprocess

    from autodub.openclaw_tool import load_batch_status, recover_orphan_running
    from autodub.remote_worker import job_is_live

    queue_root, batch_id, job_id = _make_stuck_batch(tmp_path, age_s=0.0)
    dead = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    dead.terminate()
    dead.wait(timeout=10)
    time.sleep(0.5)
    _install_heartbeat(queue_root, job_id, pid=dead.pid)

    assert job_is_live(str(queue_root), job_id) is False, (
        "PID đã chết mà vẫn báo job còn sống")
    assert recover_orphan_running(str(queue_root)) == [job_id]
    assert load_batch_status(str(queue_root), batch_id)["status"] == "interrupted"


def test_f3_a_stale_heartbeat_is_an_orphan(tmp_path):
    """F3 (t10): PID còn sống nhưng nhịp đã cũ (>45s) vẫn là mồ côi.

    Ca này bắt được tiến trình bị treo cứng (deadlock) hoặc bị đình chỉ:
    tiến trình vẫn tồn tại nên phép thử PID đơn thuần sẽ nói dối.
    """
    from autodub.remote_worker import _HEARTBEAT_STALE_S, job_is_live

    queue_root, batch_id, job_id = _make_stuck_batch(tmp_path, age_s=0.0)
    _install_heartbeat(queue_root, job_id, age_s=_HEARTBEAT_STALE_S + 5.0)
    assert job_is_live(str(queue_root), job_id) is False


def test_f3_pid_liveness_probe_never_kills_the_process(tmp_path):
    """F3 (t10) AN TOÀN WINDOWS: phép thử PID không được giết tiến trình.

    ``os.kill(pid, 0)`` trên Windows gọi TerminateProcess. Nếu ai đó 'sửa'
    _pid_alive thành os.kill thì tiến trình đang chạy thật sẽ bị giết ngay
    trong lúc dò — bài này khoá lại đúng ranh giới đó.
    """
    import subprocess

    from autodub.remote_worker import _pid_alive

    victim = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        time.sleep(0.5)
        assert _pid_alive(victim.pid) is True
        assert victim.poll() is None, "phép thử PID đã GIẾT tiến trình đang sống"
        assert _pid_alive(os.getpid()) is True
        assert _pid_alive(0) is False
        assert _pid_alive(-1) is False
        assert _pid_alive(999_999_999) is False
    finally:
        victim.terminate()
        victim.wait(timeout=10)


def test_f3_worker_stops_the_heartbeat_when_the_job_ends(tmp_path):
    """F3 (t10): nhịp tim phải được dọn ở finally, kể cả khi job lỗi.

    Để lại tệp nhịp tim sau khi job kết thúc là gieo một job 'trông như đang
    sống' cho lần quét sau — PID cũ có thể được cấp lại cho tiến trình khác.
    """
    from autodub.openclaw_tool import load_batch_status
    from autodub.remote_worker import _heartbeat_path

    batch = _submit_batch(str(tmp_path / "queue"),
                          links=["https://example.com/a.mp4"])
    queue_root = tmp_path / "queue"
    job_id = batch["job_ids"][0]
    _run_worker_until_settled(queue_root, job_id, timeout=90.0)

    status = load_batch_status(str(queue_root),
                               batch["batch_id"])["jobs"][0]["status"]
    assert status != "running", "job không kết thúc sau khi worker chạy"
    assert not _heartbeat_path(queue_root, job_id).exists(), (
        "nhịp tim còn sót lại sau khi job kết thúc")

def test_f3_periodic_scan_settles_an_orphan_while_the_app_is_alive(tmp_path):
    """F3 (t10): quét ĐỊNH KỲ đóng được job mồ côi mà KHÔNG cần khởi động lại app.

    Luồng worker có thể chết vì lỗi trong khi app vẫn sống, để lại job trong
    running/ mà không ai đóng. Nếu chỉ quét lúc khởi động thì batch đó kẹt
    'running' cho tới khi người dùng tắt/mở lại app.
    """
    import autodub.openclaw_runtime as runtime_module
    from autodub.config import Settings
    from autodub.openclaw_tool import handle, load_batch_status

    original = runtime_module._ORPHAN_SCAN_INTERVAL_S
    runtime_module._ORPHAN_SCAN_INTERVAL_S = 0.2
    runtime = runtime_module.OpenClawRuntime(
        Settings, data_dir=str(tmp_path / "data"))
    try:
        runtime.start(worker=False)
        queue_root = runtime.queue_root
        for sub in ("inbox", "running", "status", "cancel", "batches"):
            (queue_root / sub).mkdir(parents=True, exist_ok=True)

        submitted = handle({
            "action": "submit", "links": ["https://example.com/a.mp4"],
            "options": {"voice": "Thanh Lan"},
        }, queue_root=str(queue_root), settings=Settings())
        job_id = submitted["job_ids"][0]
        batch_id = submitted["batch_id"]
        # Job mồ côi xuất hiện SAU khi app đã chạy, không có nhịp tim.
        os.replace(queue_root / "inbox" / f"{job_id}.json",
                   queue_root / "running" / f"{job_id}.json")
        (queue_root / "status" / f"{job_id}.json").write_text(json.dumps({
            "job_id": job_id, "status": "running", "step": "pipeline",
            "error": "",
        }), encoding="utf-8")
        assert load_batch_status(
            str(queue_root), batch_id)["status"] == "running"

        deadline = time.time() + 20.0
        seen = "running"
        while time.time() < deadline and seen == "running":
            seen = load_batch_status(str(queue_root), batch_id)["status"]
            time.sleep(0.1)

        assert seen == "interrupted", (
            f"quét định kỳ không đóng được job mồ côi: {seen!r}")
    finally:
        runtime_module._ORPHAN_SCAN_INTERVAL_S = original
        runtime.stop()



# --------------------------------------------------------------------------- #
# P10-audit DF-01/DF-02 — nut Dung o buoc OCR / logo / clone giong / vision
#
# Loi da xac nhan tren cay 3.0.28: bon cho dung 'except Exception' bao ngoai, ma
# PipelineCancelled ke thua Exception, nen lenh huy bi ha cap thanh canh bao:
#   autodub/pipeline.py:550 (OCR), :582 (OCR logo), :765 (clone giong), :1129
#   (vision logo).
# He qua that: autodub_gui/workers.py:104 'except PipelineCancelled' khong bao gio
# chay -> bam Dung ma giao dien van bao dang chay, pipeline van di tiep.
#
# Cùng loại với bài F5 (tách nhạc) ở trên; khoá lại để không ai sửa lùi.
# --------------------------------------------------------------------------- #


class _FakeReq:
    """DubRequest rút gọn: chỉ cần vision_enabled / blur_regions / ocr_backend."""

    def __init__(self, blur_regions=None, vision_enabled=True):
        self.blur_regions = list(blur_regions or [])
        self.vision_enabled = vision_enabled
        self.ocr_backend = None


class _FakeRep:
    """ProgressReporter giả: ghi lại sự kiện để kiểm chứng, check_cancelled là no-op."""

    def __init__(self):
        self.events = []

    def emit(self, stage, status, detail=""):
        self.events.append((stage, status, detail))

    def check_cancelled(self):
        from autodub.progress import PipelineCancelled

        if _fake_rep_cancelled:
            raise PipelineCancelled("Pipeline cancelled by user")


_fake_rep_cancelled = False


def _run_detect(tmp_path, monkeypatch, *, ocr_exc=None, logo_exc=None,
                vision_enabled=True, ocr_enabled=True):
    """Gọi thẳng _detect_blur_regions với các bước phụ được giả lập.

    Trả về (blur_regions, rep, detected_logo_regions) hoặc ném lỗi ra ngoài.
    """
    from autodub import pipeline as pipeline_mod
    from autodub.media import ocr as ocr_mod
    from autodub.media import ocr_regions as reg_mod

    monkeypatch.setattr(
        pipeline_mod, "ocr_enabled_for_request", lambda *_a, **_k: ocr_enabled)
    monkeypatch.setattr(reg_mod, "load_regions", lambda *_a, **_k: None)
    monkeypatch.setattr(reg_mod, "save_regions", lambda *_a, **_k: None)
    monkeypatch.setattr(
        ocr_mod, "detect_regions_with_logo",
        lambda *_a, **_k: (_raise(ocr_exc) or ([], [])),
    )
    monkeypatch.setattr(
        ocr_mod, "detect_logo_regions",
        lambda *_a, **_k: (_raise(logo_exc) or []),
    )

    import autodub.media.video as video_mod
    monkeypatch.setattr(video_mod, "probe_dimensions", lambda *_a, **_k: (1920, 1080))
    monkeypatch.setattr(video_mod, "probe_duration_s", lambda *_a, **_k: 60.0)

    req = _FakeReq(vision_enabled=vision_enabled)
    rep = _FakeRep()
    blur = []
    detected = pipeline_mod._detect_blur_regions(
        rep=rep,
        settings=object(),
        req=req,
        video_path=str(tmp_path / "v.mp4"),
        ocr_path=str(tmp_path / "ocr_regions.json"),
        logo_ocr_path=str(tmp_path / "ocr_logo_regions.json"),
        blur_regions=blur,
        source_logo_auto=vision_enabled,
    )
    return blur, rep, detected


def _raise(exc):
    """Ném exc nếu có; trả về None nếu không — dùng để giả lập bước lỗi."""

    if exc is not None:
        raise exc
    return None


def test_df01_ocr_cancel_propagates_instead_of_warning(tmp_path, monkeypatch):
    """DF-01: huỷ ở bước OCR phải LAN RA, không bị nuốt thành cảnh báo.

    Đây là lỗi thật đã xác nhận trên 3.0.28: người dùng bấm Dừng trong khi OCR
    đang chạy -> PipelineCancelled bị hạ cấp thành 'warning' -> pipeline đi tiếp,
    autodub_gui/workers.py:104 không bao giờ nhận được tín hiệu huỷ.
    """
    from autodub.progress import PipelineCancelled

    with pytest.raises(PipelineCancelled):
        _run_detect(
            tmp_path, monkeypatch,
            ocr_exc=PipelineCancelled("Pipeline cancelled by user"),
        )


def test_df01_ocr_plain_error_is_still_skipped_quietly(tmp_path, monkeypatch):
    """Đối chứng âm: lỗi THƯỜNG ở bước OCR vẫn được bỏ qua êm như cũ.

    OCR là bước tuỳ chọn — thiếu PaddleOCR không được làm hỏng cả lượt chạy.
    Bản sửa chỉ được phép nổi lên với PipelineCancelled.
    """
    blur, rep, _detected = _run_detect(
        tmp_path, monkeypatch, ocr_exc=RuntimeError("PaddleOCR chua duoc cai."))

    warnings = [e for e in rep.events if e[1] == "warning"]
    assert warnings, f"lỗi thường phải phát cảnh báo, có: {rep.events}"
    assert blur == [], "lỗi thường không được thêm vùng blur nào"


def test_df02_logo_cancel_propagates_instead_of_info(tmp_path, monkeypatch):
    """DF-02: huỷ ở bước OCR logo cũng phải LAN RA, không chỉ ghi log info."""
    from autodub.progress import PipelineCancelled

    with pytest.raises(PipelineCancelled):
        _run_detect(
            tmp_path, monkeypatch,
            logo_exc=PipelineCancelled("Pipeline cancelled by user"),
        )


def test_df02_logo_plain_error_is_still_skipped_quietly(tmp_path, monkeypatch):
    """Đối chứng âm: lỗi THƯỜNG ở bước OCR logo vẫn được bỏ qua êm."""
    blur, rep, _detected = _run_detect(
        tmp_path, monkeypatch, logo_exc=RuntimeError("khong co logo"))

    done = [e for e in rep.events if e[0] == "ocr" and e[1] == "done"]
    assert done, f"OCR chính vẫn phải báo xong, có: {rep.events}"
    assert blur == [], "lỗi logo không được thêm vùng blur nào"


def test_df01_detect_helper_is_reachable_without_a_full_pipeline():
    """Khoá lại lý do tách hàm: khối OCR phải gọi được mà không cần chạy pipeline.

    Nếu ai đó gộp _detect_blur_regions trở lại vào _run_impl, bài này đỏ — vì khi
    đó không còn bài test nào chạm tới được khối bắt lỗi này nữa.
    """
    from autodub import pipeline as pipeline_mod

    assert callable(getattr(pipeline_mod, "_detect_blur_regions", None)), (
        "khối OCR đã bị gộp lại vào _run_impl — mất khả năng kiểm thử"
    )
    import inspect

    sig = inspect.signature(pipeline_mod._detect_blur_regions)
    for name in ("rep", "settings", "req", "video_path", "ocr_path",
                 "logo_ocr_path", "blur_regions", "source_logo_auto"):
        assert name in sig.parameters, f"thiếu tham số {name} — không còn test được"
