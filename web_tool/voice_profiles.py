import json
import subprocess
import uuid
from pathlib import Path

MAX_BYTES = 25 * 1024 * 1024
MIN_SECONDS = 3.0
MAX_SECONDS = 8.0
ALLOWED_EXTENSIONS = {".wav", ".mp3", ".m4a", ".flac"}


def _duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode or not result.stdout.strip():
        raise ValueError("voice sample is not valid audio")
    try:
        return float(result.stdout.strip())
    except ValueError as exc:
        raise ValueError("voice sample duration is invalid") from exc


def save_profile(root: Path, name: str, filename: str, data: bytes) -> dict:
    name = str(name or "").strip()
    suffix = Path(filename or "").suffix.lower()
    if not name or len(name) > 100:
        raise ValueError("voice profile name must be between 1 and 100 characters")
    if suffix not in ALLOWED_EXTENSIONS:
        raise ValueError("voice sample must be WAV, MP3, M4A, or FLAC")
    if not data or len(data) > MAX_BYTES:
        raise ValueError("voice sample must be between 1 byte and 25 MB")

    profile_id = uuid.uuid4().hex
    profile_dir = (root / profile_id).resolve()
    profile_dir.mkdir(parents=True, exist_ok=False)
    temporary = profile_dir / ".source"
    reference = profile_dir / "reference.wav"
    try:
        temporary.write_bytes(data)
        duration = _duration(temporary)
        if not MIN_SECONDS <= duration <= MAX_SECONDS:
            raise ValueError("voice sample must be between 3 and 8 seconds")
        result = subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-i",
                str(temporary),
                "-ac",
                "1",
                "-ar",
                "48000",
                "-c:a",
                "pcm_s16le",
                str(reference),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode or not reference.is_file():
            raise ValueError("voice sample conversion failed")
        profile = {
            "id": profile_id,
            "name": name,
            "reference_audio": str(reference),
            "duration_seconds": duration,
            "sample_rate": 48000,
            "channels": 1,
        }
        (profile_dir / "profile.json").write_text(
            json.dumps(profile, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return profile
    except Exception:
        for path in profile_dir.glob("*"):
            path.unlink(missing_ok=True)
        profile_dir.rmdir()
        raise
    finally:
        temporary.unlink(missing_ok=True)


def list_profiles(root: Path) -> list[dict]:
    profiles = []
    for metadata in sorted(root.glob("*/profile.json")):
        try:
            profiles.append(json.loads(metadata.read_text(encoding="utf-8")))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    return profiles


def resolve_profile(root: Path, profile_id: str) -> dict:
    profile_id = str(profile_id or "").strip()
    if not profile_id or Path(profile_id).name != profile_id:
        raise ValueError("invalid voice profile id")
    metadata = (root / profile_id / "profile.json").resolve()
    if metadata.parent.parent != root.resolve() or not metadata.is_file():
        raise ValueError("voice profile not found")
    profile = json.loads(metadata.read_text(encoding="utf-8"))
    reference = Path(profile["reference_audio"]).resolve()
    if reference.parent != metadata.parent or not reference.is_file():
        raise ValueError("voice profile audio not found")
    return profile


def delete_profile(root: Path, profile_id: str) -> bool:
    profile = resolve_profile(root, profile_id)
    profile_dir = Path(profile["reference_audio"]).parent
    for path in profile_dir.glob("*"):
        path.unlink(missing_ok=True)
    profile_dir.rmdir()
    return True
