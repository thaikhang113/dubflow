from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import uuid


JOB_UPDATE_FIELDS = {
    "state",
    "action",
    "job_dir",
    "pid",
    "error_code",
    "message",
    "progress",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    state TEXT NOT NULL,
                    action TEXT NOT NULL DEFAULT '',
                    platform TEXT NOT NULL,
                    source TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    job_dir TEXT NOT NULL DEFAULT '',
                    pid INTEGER,
                    error_code TEXT NOT NULL DEFAULT '',
                    message TEXT NOT NULL DEFAULT '',
                    progress INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS jobs_state_created
                    ON jobs(state, created_at, id);
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS providers (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    endpoint TEXT NOT NULL,
                    model TEXT NOT NULL DEFAULT '',
                    timeout_seconds INTEGER NOT NULL DEFAULT 90,
                    has_secret INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS channels (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    url TEXT NOT NULL,
                    interval_minutes INTEGER NOT NULL,
                    enabled INTEGER NOT NULL,
                    provider_id TEXT,
                    model TEXT NOT NULL DEFAULT '',
                    voice TEXT NOT NULL DEFAULT '',
                    series_id TEXT NOT NULL DEFAULT '',
                    preset_json TEXT NOT NULL DEFAULT '{}',
                    next_check_at TEXT NOT NULL,
                    last_checked_at TEXT NOT NULL DEFAULT '',
                    last_result TEXT NOT NULL DEFAULT '',
                    state TEXT NOT NULL DEFAULT 'ready',
                    error_code TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS channels_due
                    ON channels(enabled, next_check_at);
                CREATE TABLE IF NOT EXISTS seen_videos (
                    platform TEXT NOT NULL,
                    video_id TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL,
                    PRIMARY KEY(platform, video_id)
                );
                """
            )

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _job(row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        job = dict(row)
        job["request"] = json.loads(job.pop("request_json"))
        return job

    def enqueue_job(self, request: dict) -> dict:
        platform = str(request.get("platform") or "").strip()
        source = str(request.get("source") or "").strip()
        if not platform or not source:
            raise ValueError("platform and source are required")
        timestamp = _now()
        with self._connect() as connection:
            job_id = self._insert_job(connection, request, timestamp)
            row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return self._job(row)

    @staticmethod
    def _insert_job(connection, request: dict, timestamp: str) -> str:
        job_id = f"job-{uuid.uuid4().hex}"
        connection.execute(
            """
            INSERT INTO jobs (
                id, created_at, updated_at, state, platform, source, request_json
            ) VALUES (?, ?, ?, 'queued', ?, ?, ?)
            """,
            (
                job_id,
                timestamp,
                timestamp,
                str(request["platform"]).strip(),
                str(request["source"]).strip(),
                json.dumps(request, ensure_ascii=False, sort_keys=True),
            ),
        )
        return job_id

    def get_job(self, job_id: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return self._job(row)

    def list_jobs(self, limit: int = 100) -> list[dict]:
        limit = max(1, min(500, int(limit)))
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM jobs ORDER BY rowid DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._job(row) for row in rows]

    def update_job(self, job_id: str, **fields) -> dict:
        unknown = set(fields) - JOB_UPDATE_FIELDS
        if unknown:
            raise ValueError(f"unsupported job fields: {', '.join(sorted(unknown))}")
        if not fields:
            job = self.get_job(job_id)
            if job is None:
                raise KeyError(job_id)
            return job
        fields["updated_at"] = _now()
        assignments = ", ".join(f"{name} = ?" for name in fields)
        values = list(fields.values()) + [job_id]
        with self._connect() as connection:
            cursor = connection.execute(
                f"UPDATE jobs SET {assignments} WHERE id = ?",
                values,
            )
            if cursor.rowcount != 1:
                raise KeyError(job_id)
            row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return self._job(row)

    def claim_next_job(self) -> dict | None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            paused = connection.execute(
                "SELECT value FROM settings WHERE key = 'queue_paused'"
            ).fetchone()
            if paused and paused["value"] == "1":
                return None
            running = connection.execute(
                "SELECT 1 FROM jobs WHERE state = 'running' LIMIT 1"
            ).fetchone()
            if running:
                return None
            row = connection.execute(
                """
                SELECT * FROM jobs
                WHERE state = 'queued'
                ORDER BY rowid
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                return None
            timestamp = _now()
            connection.execute(
                """
                UPDATE jobs
                SET state = 'running', action = '', updated_at = ?
                WHERE id = ? AND state = 'queued'
                """,
                (timestamp, row["id"]),
            )
            claimed = connection.execute(
                "SELECT * FROM jobs WHERE id = ?",
                (row["id"],),
            ).fetchone()
        return self._job(claimed)

    def recover_running_jobs(self) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE jobs
                SET state = 'needs_attention',
                    action = 'resume',
                    pid = NULL,
                    error_code = 'WorkerInterrupted',
                    message = 'Container stopped while job was running; resume from checkpoint.',
                    updated_at = ?
                WHERE state = 'running'
                """,
                (_now(),),
            )
            return cursor.rowcount

    def set_queue_paused(self, paused: bool) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO settings(key, value) VALUES('queue_paused', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                ("1" if paused else "0",),
            )

    def queue_paused(self) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM settings WHERE key = 'queue_paused'"
            ).fetchone()
        return bool(row and row["value"] == "1")

    def get_settings(self, defaults: dict) -> dict:
        with self._connect() as connection:
            rows = connection.execute("SELECT key, value FROM settings").fetchall()
        values = dict(defaults)
        values.update({
            row["key"]: row["value"]
            for row in rows
            if row["key"] in defaults
        })
        return values

    def set_settings(self, values: dict) -> None:
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO settings(key, value) VALUES(?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                [(str(key), str(value)) for key, value in values.items()],
            )

    def requeue_for_resume(self, job_id: str, request: dict) -> dict:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE jobs
                SET state = 'queued',
                    action = '',
                    request_json = ?,
                    pid = NULL,
                    error_code = '',
                    message = 'Queued for resume.',
                    updated_at = ?
                WHERE id = ? AND state IN ('needs_attention', 'failed', 'cancelled')
                """,
                (
                    json.dumps(request, ensure_ascii=False, sort_keys=True),
                    _now(),
                    job_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError("job cannot be resumed")
            row = connection.execute(
                "SELECT * FROM jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
        return self._job(row)

    def cancel_waiting_job(self, job_id: str) -> dict:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE jobs
                SET state = 'cancelled',
                    action = '',
                    pid = NULL,
                    message = 'Cancelled by user.',
                    updated_at = ?
                WHERE id = ? AND state IN ('queued', 'paused', 'needs_attention')
                """,
                (_now(), job_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("job cannot be cancelled")
            row = connection.execute(
                "SELECT * FROM jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
        return self._job(row)

    @staticmethod
    def _provider(row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        provider = dict(row)
        provider["configured"] = bool(provider.pop("has_secret"))
        return provider

    def create_provider(self, values: dict, has_secret: bool) -> dict:
        provider_id = f"provider-{uuid.uuid4().hex}"
        timestamp = _now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO providers (
                    id, name, kind, endpoint, model, timeout_seconds,
                    has_secret, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    provider_id,
                    values["name"],
                    values["kind"],
                    values["endpoint"],
                    values["model"],
                    values["timeout_seconds"],
                    1 if has_secret else 0,
                    timestamp,
                    timestamp,
                ),
            )
            row = connection.execute(
                "SELECT * FROM providers WHERE id = ?",
                (provider_id,),
            ).fetchone()
        return self._provider(row)

    def get_provider(self, provider_id: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM providers WHERE id = ?",
                (provider_id,),
            ).fetchone()
        return self._provider(row)

    def list_providers(self) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM providers ORDER BY rowid DESC"
            ).fetchall()
        return [self._provider(row) for row in rows]

    def update_provider(
        self,
        provider_id: str,
        values: dict,
        has_secret: bool | None = None,
    ) -> dict | None:
        timestamp = _now()
        with self._connect() as connection:
            current = connection.execute(
                "SELECT has_secret FROM providers WHERE id = ?",
                (provider_id,),
            ).fetchone()
            if current is None:
                return None
            configured = current["has_secret"] if has_secret is None else int(has_secret)
            connection.execute(
                """
                UPDATE providers
                SET name = ?,
                    kind = ?,
                    endpoint = ?,
                    model = ?,
                    timeout_seconds = ?,
                    has_secret = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    values["name"],
                    values["kind"],
                    values["endpoint"],
                    values["model"],
                    values["timeout_seconds"],
                    configured,
                    timestamp,
                    provider_id,
                ),
            )
            row = connection.execute(
                "SELECT * FROM providers WHERE id = ?",
                (provider_id,),
            ).fetchone()
        return self._provider(row)

    def delete_provider(self, provider_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM providers WHERE id = ?",
                (provider_id,),
            )
        return cursor.rowcount == 1

    @staticmethod
    def _channel(row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        channel = dict(row)
        channel["enabled"] = bool(channel["enabled"])
        channel["preset"] = json.loads(channel.pop("preset_json"))
        return channel

    def create_channel(self, values: dict) -> dict:
        channel_id = f"channel-{uuid.uuid4().hex}"
        timestamp = _now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO channels (
                    id, name, platform, url, interval_minutes, enabled,
                    provider_id, model, voice, series_id, preset_json,
                    next_check_at, state
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    channel_id,
                    values["name"],
                    values["platform"],
                    values["url"],
                    values["interval_minutes"],
                    int(values.get("enabled", True)),
                    values.get("provider_id") or None,
                    values.get("model", ""),
                    values.get("voice", ""),
                    values.get("series_id", ""),
                    json.dumps(values.get("preset") or {}, ensure_ascii=False, sort_keys=True),
                    timestamp,
                    "ready" if values.get("enabled", True) else "disabled",
                ),
            )
            row = connection.execute(
                "SELECT * FROM channels WHERE id = ?",
                (channel_id,),
            ).fetchone()
        return self._channel(row)

    def get_channel(self, channel_id: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM channels WHERE id = ?",
                (channel_id,),
            ).fetchone()
        return self._channel(row)

    def list_channels(self) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM channels ORDER BY rowid DESC"
            ).fetchall()
        return [self._channel(row) for row in rows]

    def due_channels(self, now: str | None = None) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM channels
                WHERE enabled = 1 AND next_check_at <= ?
                ORDER BY next_check_at, rowid
                """,
                (now or _now(),),
            ).fetchall()
        return [self._channel(row) for row in rows]

    def update_channel(self, channel_id: str, values: dict) -> dict | None:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE channels
                SET name = ?, platform = ?, url = ?, interval_minutes = ?,
                    enabled = ?, provider_id = ?, model = ?, voice = ?,
                    series_id = ?, preset_json = ?,
                    state = CASE WHEN ? THEN 'ready' ELSE 'disabled' END,
                    error_code = CASE WHEN ? THEN error_code ELSE '' END
                WHERE id = ?
                """,
                (
                    values["name"],
                    values["platform"],
                    values["url"],
                    values["interval_minutes"],
                    int(values.get("enabled", True)),
                    values.get("provider_id") or None,
                    values.get("model", ""),
                    values.get("voice", ""),
                    values.get("series_id", ""),
                    json.dumps(values.get("preset") or {}, ensure_ascii=False, sort_keys=True),
                    int(values.get("enabled", True)),
                    int(values.get("enabled", True)),
                    channel_id,
                ),
            )
            if cursor.rowcount != 1:
                return None
            row = connection.execute(
                "SELECT * FROM channels WHERE id = ?",
                (channel_id,),
            ).fetchone()
        return self._channel(row)

    def set_channel_enabled(self, channel_id: str, enabled: bool) -> dict | None:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE channels
                SET enabled = ?,
                    state = CASE WHEN ? THEN 'ready' ELSE 'disabled' END,
                    error_code = CASE WHEN ? THEN '' ELSE error_code END,
                    next_check_at = CASE WHEN ? THEN ? ELSE next_check_at END
                WHERE id = ?
                """,
                (
                    int(enabled),
                    int(enabled),
                    int(enabled),
                    int(enabled),
                    _now(),
                    channel_id,
                ),
            )
            if cursor.rowcount != 1:
                return None
            row = connection.execute(
                "SELECT * FROM channels WHERE id = ?",
                (channel_id,),
            ).fetchone()
        return self._channel(row)

    def schedule_channel_now(self, channel_id: str) -> dict | None:
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE channels SET next_check_at = ? WHERE id = ? AND enabled = 1",
                (_now(), channel_id),
            )
            if cursor.rowcount != 1:
                return None
            row = connection.execute(
                "SELECT * FROM channels WHERE id = ?",
                (channel_id,),
            ).fetchone()
        return self._channel(row)

    def finish_channel_check(
        self,
        channel_id: str,
        *,
        state: str,
        error_code: str = "",
        result: str = "",
    ) -> dict | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT interval_minutes FROM channels WHERE id = ?",
                (channel_id,),
            ).fetchone()
            if row is None:
                return None
            checked = datetime.now(timezone.utc)
            next_check = checked + timedelta(minutes=row["interval_minutes"])
            connection.execute(
                """
                UPDATE channels
                SET state = ?, error_code = ?, last_result = ?,
                    last_checked_at = ?, next_check_at = ?
                WHERE id = ?
                """,
                (
                    state,
                    error_code,
                    result,
                    checked.isoformat(),
                    next_check.isoformat(),
                    channel_id,
                ),
            )
            updated = connection.execute(
                "SELECT * FROM channels WHERE id = ?",
                (channel_id,),
            ).fetchone()
        return self._channel(updated)

    def enqueue_seen_video(
        self,
        platform: str,
        video_id: str,
        source_url: str,
        request: dict,
    ) -> dict | None:
        timestamp = _now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO seen_videos(
                    platform, video_id, source_url, first_seen_at
                ) VALUES (?, ?, ?, ?)
                """,
                (platform, video_id, source_url, timestamp),
            )
            if cursor.rowcount != 1:
                return None
            job_id = self._insert_job(connection, request, timestamp)
            row = connection.execute(
                "SELECT * FROM jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
        return self._job(row)

    def delete_channel(self, channel_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM channels WHERE id = ?",
                (channel_id,),
            )
        return cursor.rowcount == 1
