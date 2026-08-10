from contextlib import contextmanager
import importlib.util
import os
from pathlib import Path
import threading

from .pipeline import build_job_command


class MonitorAttention(RuntimeError):
    pass


@contextmanager
def _environment(values):
    previous = {key: os.environ.get(key) for key in values}
    os.environ.update({key: str(value) for key, value in values.items()})
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _load_discovery(settings):
    path = settings.repo_root / "skills" / "content-monitor" / "content-monitor.py"
    spec = importlib.util.spec_from_file_location("web_tool_content_monitor", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("ContentMonitorUnavailable")
    module = importlib.util.module_from_spec(spec)
    environment = {
        "OPENCLAW_STATE_DIR": settings.data_dir / "monitor",
        "OPENCLAW_HOST_HOME": settings.root,
        "OPENCLAW_WORKSPACE_ROOT": settings.repo_root,
        "TELEGRAM_CONFIG": settings.secrets_dir / "telegram.json",
        "CONTENT_MONITOR_CDP_URL": "http://127.0.0.1:9222",
    }
    with _environment(environment):
        spec.loader.exec_module(module)

    def discover(channel, count=10):
        messages = []
        original_log = module.log
        module.log = lambda message, *_args: messages.append(str(message))
        try:
            videos = module.fetch_latest_videos_for_channel(channel, count=count)
        finally:
            module.log = original_log
        combined = " ".join(messages).lower()
        if not videos and any(
            marker in combined
            for marker in ("captcha", "login", "xac minh", "verify", "dang nhap")
        ):
            platform = channel.get("platform", "").capitalize()
            raise MonitorAttention(f"{platform}CaptchaOrLoginRequired")
        return videos

    return discover


class MonitorScheduler:
    def __init__(self, store, settings, discovery=None, on_enqueue=None):
        self.store = store
        self.settings = settings
        self.discovery = discovery or _load_discovery(settings)
        self.on_enqueue = on_enqueue
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop,
            name="channel-monitor",
            daemon=True,
        )
        self._thread.start()
        self.notify()

    def stop(self):
        self._stop.set()
        self.notify()
        if self._thread:
            self._thread.join(5)

    def notify(self):
        self._wake.set()

    def _loop(self):
        while not self._stop.is_set():
            self.run_due_once()
            self._wake.wait(30)
            self._wake.clear()

    def run_due_once(self):
        channels = self.store.due_channels()
        for channel in channels:
            self.run_channel_once(channel["id"])
        return {"checked": len(channels)}

    def run_channel_once(self, channel_id: str) -> dict | None:
        channel = self.store.get_channel(channel_id)
        if channel is None:
            return None
        if not channel["enabled"]:
            return channel
        try:
            whisper_model = self.store.get_settings(
                {"whisper_model": "medium"}
            )["whisper_model"]
            videos = self.discovery(channel, count=10) or []
            enqueued = 0
            for video in videos:
                video_id = str(video.get("id") or "").strip()
                source = str(video.get("url") or "").strip()
                if not video_id or not source:
                    continue
                request = {
                    "platform": channel["platform"],
                    "source": source,
                    "provider_id": channel["provider_id"] or "",
                    "model": channel["model"],
                    "voice": channel["voice"],
                    "series_id": channel["series_id"],
                    "preset": channel["preset"],
                    "channel_id": channel["id"],
                    "source_title": str(video.get("title") or "").strip(),
                    "whisper_model": whisper_model,
                }
                provider = (
                    self.store.get_provider(channel["provider_id"])
                    if channel["provider_id"]
                    else None
                )
                if provider is None:
                    default_id = self.store.get_settings(
                        {'default_provider_id': ''}
                    )['default_provider_id']
                    provider = self.store.get_provider(default_id) if default_id else None
                    if provider:
                        request['provider_id'] = provider['id']
                if provider:
                    role = (
                        "tts_provider_id"
                        if provider["kind"] == "ai33"
                        else "translation_provider_id"
                    )
                    request[role] = provider["id"]
                ai33 = [
                    candidate
                    for candidate in self.store.list_providers()
                    if candidate['kind'] == 'ai33' and candidate['configured']
                ]
                if (
                    'tts_provider_id' not in request
                    and str(request.get('voice') or '').lower().startswith('ai33:')
                    and len(ai33) == 1
                ):
                    request['tts_provider_id'] = ai33[0]['id']
                build_job_command(request, self.settings)
                job = self.store.enqueue_seen_video(
                    channel["platform"],
                    video_id,
                    source,
                    request,
                )
                if job:
                    enqueued += 1
                    if self.on_enqueue:
                        self.on_enqueue(job)
            return self.store.finish_channel_check(
                channel_id,
                state="ready",
                result=f"{len(videos)} found, {enqueued} queued",
            )
        except MonitorAttention as exc:
            return self.store.finish_channel_check(
                channel_id,
                state="needs_attention",
                error_code=str(exc)[:200],
                result="Login or captcha requires attention.",
            )
        except Exception as exc:
            return self.store.finish_channel_check(
                channel_id,
                state="error",
                error_code=type(exc).__name__,
                result=str(exc)[:500],
            )
