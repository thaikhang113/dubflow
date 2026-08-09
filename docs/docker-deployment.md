# Safe local Docker deployment

The Compose service is intentionally reachable only from the local machine. Its
default URL is `http://127.0.0.1:18793`; it is not an Internet-facing deployment.
All runtime state is kept outside the repository at
`/home/haonguyen/.openclaw/tool-runtime` (override only with
`TOOL_RUNTIME_DIR`). This includes the SQLite database, job state, provider
settings, browser profile, outputs, models, and secrets.

## Start and verify

```bash
docker compose config
docker compose up -d --build tool
curl --fail http://127.0.0.1:18793/
curl --fail http://127.0.0.1:18793/api/health
```

If local port 18793 is already deliberately in use, select another loopback
port without changing the file:

```bash
TOOL_PORT=18795 docker compose up -d --build tool
```

The container has a host-gateway alias for local providers. Supported,
non-secret defaults are `OLLAMA_API_BASE=http://host.docker.internal:11434`,
`NINEROUTER_API_BASE=http://host.docker.internal:20128/v1`,
`OCR_VISION_API_BASE=http://host.docker.internal:20128/v1`, and
`AI33_API_BASE=https://api.ai33.pro`. Configure/select providers through the
web Settings UI; the application persists those choices in the runtime mount.

The existing optional services remain available: add `--profile ollama` to run
the local Ollama service, or `--profile trend` to run the trend database.

## Pipeline service contracts

When ASR/TTS services run beside the pipeline, use service DNS names and ports:

- `qwen-asr:8000`: `POST /v1/transcribe` with JSON
  `{"audio_path": "...", "language": "zh"}`. Response segments require
  integer `start_ms`, `end_ms`, and `text`.
- `vieneu:8000`: `GET /health` is ready only when JSON `{"ready": true}`.
  `POST /v1/synthesize` accepts JSON `{"text": "...", "voice": "...",
  "style": "story"}` and returns WAV bytes.

Pipeline defaults are `vieneu:hong-chau` and `story`. No Compose changes are
part of this integration fix.

## Secrets and shutdown

Enter credentials only in the runtime Settings UI. When needed, the supported
credential variable names are `AI33_API_KEY`, `NINEROUTER_API_KEY`,
`OCR_VISION_API_KEY`, and `RESONA_API_TOKEN`; this deployment deliberately
does not pass them through Compose. Secrets, cookies, browser/channel state,
and all operational runtime data are never committed to Git.

Stop the local container with:

```bash
docker compose stop tool
```

To remove the container while retaining runtime state, run:

```bash
docker compose down
```
