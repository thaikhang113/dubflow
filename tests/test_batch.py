"""Tests for line-based batch input and crash-safe state (autodub.batch).

The pipeline is stubbed — no download, no ASR, no TTS.
"""
import json
import os

import pytest

from autodub.batch import STATE_FILENAME, parse_lines, run_batch
from autodub.config import Settings
from autodub.pipeline import DubRequest
from autodub.progress import PipelineCancelled


# ------------------------------------------------------------ parse_lines --- #

def test_parse_plain_urls():
    items = parse_lines("https://a.com/1\nhttps://a.com/2\n")
    assert [i.url for i in items] == ["https://a.com/1", "https://a.com/2"]
    assert all(i.voice is None for i in items)


def test_parse_skips_blanks_and_comments():
    items = parse_lines("""
        # danh sách video
        https://a.com/1

        https://a.com/2
    """)
    assert [i.url for i in items] == ["https://a.com/1", "https://a.com/2"]


@pytest.mark.parametrize("line,voice", [
    ("https://a.com/1 | Trúc Ly", "Trúc Ly"),
    ("https://a.com/1|Phạm Tuyên", "Phạm Tuyên"),
    ("https://a.com/1, Minh Đức", "Minh Đức"),
    ("https://a.com/1\tEmma", "Emma"),
    ("https://a.com/1  Ngọc Linh", "Ngọc Linh"),
])
def test_parse_voice_override(line, voice):
    """Tên giọng đi sau liên kết, phân tách bằng | , ; tab hoặc hai dấu cách."""
    items = parse_lines(line)
    assert len(items) == 1
    assert items[0].url == "https://a.com/1"
    assert items[0].voice == voice


def test_one_space_does_not_split_a_voice_name():
    """Tên giọng tiếng Việt có dấu cách bên trong — một dấu cách không tách."""
    items = parse_lines("https://a.com/1")
    assert items[0].voice is None


def test_parse_unknown_voice_is_kept_verbatim():
    """Tên lạ vẫn được giữ; lúc chạy nó tự rơi về giọng mặc định."""
    items = parse_lines("https://a.com/1 | Klingon")
    assert len(items) == 1
    assert items[0].voice == "Klingon"


def test_parse_drops_duplicates_keeping_first():
    items = parse_lines("https://a.com/1 | Trúc Ly\nhttps://a.com/1 | Mai Anh")
    assert len(items) == 1
    assert items[0].voice == "Trúc Ly"


def test_parse_accepts_a_list_of_lines():
    assert [i.url for i in parse_lines(["https://a.com/1"])] == ["https://a.com/1"]


def test_parse_empty_input():
    assert parse_lines("   \n\n# chỉ có ghi chú\n") == []


# --------------------------------------------------------------- run_batch --- #

class FakePipeline:
    """Records the requests it receives and replays scripted outcomes."""

    def __init__(self, outcomes=None, work_dirs=None):
        self.outcomes = outcomes or {}
        # url -> work_dir mà pipeline "đã tạo" cho lượt chạy đó (kể cả khi
        # lượt chạy đổ giữa chừng), giống pipeline thật đặt last_work_dir.
        self.work_dirs = work_dirs or {}
        self.seen: list[DubRequest] = []
        self.last_work_dir = ""

    def run(self, req):
        self.seen.append(req)
        self.last_work_dir = req.resume_dir or self.work_dirs.get(req.url, "wd")
        outcome = self.outcomes.get(req.url, "ok")
        if isinstance(outcome, Exception):
            raise outcome
        if outcome == "stalled":
            return type("R", (), {"status": "translation_pending",
                                  "work_dir": "wd", "report": None})()
        return type("R", (), {
            "status": "completed",
            "work_dir": "wd",
            "report": {
                "session_id": f"sess_{len(self.seen)}",
                "total_segments": 2,
                "total_original_duration": 4.0,
                "total_tts_duration": 4.1,
                "processing_time_seconds": 1.0,
            },
        })()


@pytest.fixture
def env(tmp_path):
    settings = Settings(output_dir=str(tmp_path))
    template = DubRequest(url="", voice="Phạm Tuyên", output_dir=str(tmp_path))
    return settings, template, str(tmp_path / STATE_FILENAME)


def read_state(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def test_runs_every_url_and_writes_state(env):
    settings, template, state_path = env
    pipe = FakePipeline()

    summary = run_batch("https://a.com/1\nhttps://a.com/2",
                        settings, template, pipeline=pipe)

    assert (summary.total, summary.success, summary.failed) == (2, 2, 0)
    assert [r.url for r in pipe.seen] == ["https://a.com/1", "https://a.com/2"]
    videos = read_state(state_path)["videos"]
    assert [v["status"] for v in videos] == ["success", "success"]
    assert videos[0]["segments"] == 2


def test_per_line_voice_overrides_template(env):
    settings, template, _ = env
    pipe = FakePipeline()

    run_batch("https://a.com/1\nhttps://a.com/2 | Trúc Ly",
              settings, template, pipeline=pipe)

    assert [r.voice for r in pipe.seen] == ["Phạm Tuyên", "Trúc Ly"]


def test_failure_is_recorded_and_batch_continues(env):
    settings, template, state_path = env
    pipe = FakePipeline({"https://a.com/1": RuntimeError("tải lỗi")})

    summary = run_batch("https://a.com/1\nhttps://a.com/2",
                        settings, template, pipeline=pipe)

    assert (summary.success, summary.failed) == (1, 1)
    videos = read_state(state_path)["videos"]
    assert videos[0]["status"] == "failed"
    assert "tải lỗi" in videos[0]["error"]
    assert videos[1]["status"] == "success"


def test_stalled_pipeline_counts_as_failure(env):
    settings, template, state_path = env
    pipe = FakePipeline({"https://a.com/1": "stalled"})

    summary = run_batch("https://a.com/1", settings, template, pipeline=pipe)

    assert summary.failed == 1
    assert read_state(state_path)["videos"][0]["status"] == "failed"


def test_resume_skips_completed_urls(env):
    settings, template, state_path = env
    run_batch("https://a.com/1", settings, template, pipeline=FakePipeline())

    pipe2 = FakePipeline()
    summary = run_batch("https://a.com/1\nhttps://a.com/2",
                        settings, template, pipeline=pipe2)

    assert [r.url for r in pipe2.seen] == ["https://a.com/2"]
    assert (summary.skipped, summary.success) == (1, 1)


def test_retry_done_reprocesses_everything(env):
    settings, template, _ = env
    run_batch("https://a.com/1", settings, template, pipeline=FakePipeline())

    pipe2 = FakePipeline()
    summary = run_batch("https://a.com/1", settings, template,
                        pipeline=pipe2, retry_done=True)

    assert [r.url for r in pipe2.seen] == ["https://a.com/1"]
    assert (summary.skipped, summary.success) == (0, 1)


def test_failed_urls_are_retried_on_resume(env):
    settings, template, _ = env
    run_batch("https://a.com/1", settings, template,
              pipeline=FakePipeline({"https://a.com/1": RuntimeError("x")}))

    pipe2 = FakePipeline()
    run_batch("https://a.com/1", settings, template, pipeline=pipe2)

    assert [r.url for r in pipe2.seen] == ["https://a.com/1"]


def test_failed_video_records_work_dir_for_resume(env, tmp_path):
    """Video hỏng giữ lại thư mục dở dang; chạy lại đi TIẾP đúng thư mục đó
    (resume_dir) thay vì tạo thư mục mới — không tải/nghe-chép lại từ đầu."""
    settings, template, state_path = env
    crash_dir = tmp_path / "20260101000000_vi"
    crash_dir.mkdir()
    pipe = FakePipeline({"https://a.com/1": RuntimeError("đứt mạng")},
                        work_dirs={"https://a.com/1": str(crash_dir)})

    run_batch("https://a.com/1", settings, template, pipeline=pipe)
    assert read_state(state_path)["videos"][0]["work_dir"] == str(crash_dir)

    pipe2 = FakePipeline()
    run_batch("https://a.com/1", settings, template, pipeline=pipe2)
    assert pipe2.seen[0].resume_dir == str(crash_dir)


def test_missing_work_dir_falls_back_to_fresh_run(env, tmp_path):
    """Thư mục dở dang đã bị xóa tay → chạy lại như video mới, không đổ lỗi."""
    settings, template, _ = env
    gone = str(tmp_path / "da_xoa")
    pipe = FakePipeline({"https://a.com/1": RuntimeError("x")},
                        work_dirs={"https://a.com/1": gone})
    run_batch("https://a.com/1", settings, template, pipeline=pipe)

    pipe2 = FakePipeline()
    run_batch("https://a.com/1", settings, template, pipeline=pipe2)
    assert pipe2.seen[0].resume_dir is None


def test_empty_list_does_nothing(env):
    settings, template, state_path = env
    pipe = FakePipeline()

    summary = run_batch("\n# nothing\n", settings, template, pipeline=pipe)

    assert summary.total == 0
    assert pipe.seen == []
    assert not os.path.exists(state_path)


def test_corrupt_state_file_does_not_block(env):
    settings, template, state_path = env
    with open(state_path, "w", encoding="utf-8") as f:
        f.write("{ not json")
    pipe = FakePipeline()

    summary = run_batch("https://a.com/1", settings, template, pipeline=pipe)

    assert summary.success == 1


def test_cancel_aborts_batch_without_marking_failure(env):
    settings, template, state_path = env
    pipe = FakePipeline({"https://a.com/2": PipelineCancelled("stop")})

    with pytest.raises(PipelineCancelled):
        run_batch("https://a.com/1\nhttps://a.com/2\nhttps://a.com/3",
                  settings, template, pipeline=pipe)

    videos = read_state(state_path)["videos"]
    assert videos[0]["status"] == "success"
    assert videos[1]["status"] == "processing"   # left mid-flight, resumable
    assert videos[2]["status"] == "waiting"
    assert len(pipe.seen) == 2                   # never reached the third URL


def test_observer_receives_events(env):
    settings, template, _ = env
    events = []

    run_batch("https://a.com/1", settings, template, pipeline=FakePipeline(),
              observer=lambda i, t, item, st, d: events.append((i, t, item.url, st)))

    assert events == [(0, 1, "https://a.com/1", "start"),
                      (0, 1, "https://a.com/1", "success")]
