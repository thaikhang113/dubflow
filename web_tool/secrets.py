import os
from pathlib import Path
import re
from urllib.parse import urlsplit
import urllib.error
import urllib.request
import uuid


PROVIDER_KINDS = {"openai_compatible", "ai33", "ollama"}
SAFE_NAME = re.compile(r"^[A-Za-z0-9_-]{1,100}$")


def sanitize(value: object) -> str:
    text = str(value or "")
    text = re.sub(
        r"(?i)(Authorization:\s*Bearer\s+)\S+",
        r"\1<redacted>",
        text,
    )
    text = re.sub(r"(?i)(Cookie:\s*)[^\r\n]+", r"\1<redacted>", text)
    text = re.sub(
        r"(?i)([?&](?:token|key|api_key|signature|sig)=)[^&\s]+",
        r"\1<redacted>",
        text,
    )
    text = re.sub(r"\bsk_[A-Za-z0-9]{12,}\b", "<redacted>", text)
    return text[:500]


def validate_provider(payload: dict) -> dict:
    name = str(payload.get("name") or "").strip()
    kind = str(payload.get("kind") or "").strip().lower()
    endpoint = str(payload.get("endpoint") or "").strip().rstrip("/")
    model = str(payload.get("model") or "").strip()
    if not 1 <= len(name) <= 80:
        raise ValueError("provider name must contain 1..80 characters")
    if kind not in PROVIDER_KINDS:
        raise ValueError("unsupported provider kind")
    if len(endpoint) > 2048:
        raise ValueError("provider endpoint is too long")
    try:
        parsed = urlsplit(endpoint)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("invalid provider endpoint") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or port is not None and not 1 <= port <= 65535
    ):
        raise ValueError("provider endpoint must be a plain http(s) URL")
    if len(model) > 200:
        raise ValueError("provider model is too long")
    try:
        timeout = int(payload.get("timeout_seconds", 90))
    except (TypeError, ValueError) as exc:
        raise ValueError("provider timeout must be an integer") from exc
    if not 1 <= timeout <= 600:
        raise ValueError("provider timeout must be between 1 and 600 seconds")
    return {
        "name": name,
        "kind": kind,
        "endpoint": endpoint,
        "model": model,
        "timeout_seconds": timeout,
    }


class SecretStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, name: str) -> Path:
        if not SAFE_NAME.fullmatch(name):
            raise ValueError("invalid secret name")
        return self.root / f"{name}.secret"

    def write(self, name: str, value: str) -> Path:
        value = str(value or "").strip()
        if not value:
            raise ValueError("secret must not be empty")
        target = self._path(name)
        temporary = self.root / f".{name}-{uuid.uuid4().hex}.tmp"
        temporary.write_text(value, encoding="utf-8")
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        try:
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        return target

    def read_status(self, name: str) -> dict:
        return {"configured": self._path(name).is_file()}

    def environment(self, name: str) -> dict[str, str]:
        path = self._path(name)
        if not path.is_file():
            return {}
        return {"PROVIDER_API_KEY": path.read_text(encoding="utf-8").strip()}

    def delete(self, name: str) -> None:
        self._path(name).unlink(missing_ok=True)


def test_provider_connection(provider: dict, secrets: SecretStore) -> dict:
    endpoint = provider["endpoint"].rstrip("/")
    if provider["kind"] == "ollama":
        url = endpoint + "/api/tags"
    elif provider["kind"] == "openai_compatible":
        url = endpoint + "/models"
    else:
        url = endpoint
    headers = {"Accept": "application/json"}
    key = secrets.environment(provider["id"]).get("PROVIDER_API_KEY", "")
    if key:
        headers["Authorization"] = f"Bearer {key}"
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=provider["timeout_seconds"]) as response:
            return {"ok": 200 <= response.status < 400, "message": f"HTTP {response.status}"}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "message": sanitize(f"HTTP {exc.code}: {exc.reason}")}
    except Exception as exc:
        return {"ok": False, "message": sanitize(exc)}
