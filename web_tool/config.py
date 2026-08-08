from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    root: Path
    data_dir: Path
    secrets_dir: Path
    jobs_dir: Path
    output_dir: Path
    models_dir: Path
    browser_dir: Path
    database_path: Path
    bind_host: str
    bind_port: int
    repo_root: Path

    @classmethod
    def from_env(cls) -> "Settings":
        repo_root = Path(__file__).resolve().parents[1]
        root = Path(os.environ.get("TOOL_ROOT", repo_root / ".tool-runtime"))
        host = os.environ.get("TOOL_BIND_HOST", "127.0.0.1").strip()
        try:
            port = int(os.environ.get("TOOL_BIND_PORT", "18793"))
        except ValueError as exc:
            raise ValueError("TOOL_BIND_PORT must be an integer") from exc
        return cls._create(root, host, port, repo_root)

    @classmethod
    def for_test(cls, root: Path) -> "Settings":
        return cls._create(root, "127.0.0.1", 18793, Path(__file__).resolve().parents[1])

    @classmethod
    def _create(cls, root: Path, host: str, port: int, repo_root: Path) -> "Settings":
        if not host:
            raise ValueError("TOOL_BIND_HOST must not be empty")
        if not 1 <= port <= 65535:
            raise ValueError("TOOL_BIND_PORT must be between 1 and 65535")
        root = root.expanduser().resolve()
        paths = {
            name: root / name
            for name in ("data", "secrets", "jobs", "output", "models", "browser")
        }
        for path in paths.values():
            path.mkdir(parents=True, exist_ok=True)
        return cls(
            root=root,
            data_dir=paths["data"],
            secrets_dir=paths["secrets"],
            jobs_dir=paths["jobs"],
            output_dir=paths["output"],
            models_dir=paths["models"],
            browser_dir=paths["browser"],
            database_path=paths["data"] / "tool.sqlite3",
            bind_host=host,
            bind_port=port,
            repo_root=repo_root.resolve(),
        )

