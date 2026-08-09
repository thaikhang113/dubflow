# Ollama On-Demand Design

## Goal

Let a non-technical user install and select local Ollama from the Providers screen.

## Flow

1. User starts the existing localhost host helper.
2. User clicks **Cài Ollama local** in Providers.
3. Helper runs fixed Docker Compose commands to start only the `ollama` profile service and pull `qwen2.5:3b`.
4. Web creates or reuses an Ollama provider at `http://ollama:11434`.
5. Web selects that provider and model as defaults, then refreshes Doctor.

## Security

- Keep helper bound to `127.0.0.1:18794`.
- Require the existing local Origin allowlist.
- Do not mount the Docker socket into the web container.
- Do not accept command, service, model, path or endpoint input.
- Return status and short error codes, not Docker output.

## User Experience

- Show an indeterminate install state while Docker starts and the model downloads.
- Prevent duplicate clicks.
- Preserve existing settings and provider records.
- Explain when Docker or the host helper is unavailable.

## Verification

- Unit test exact allowlisted Docker commands and failure redaction.
- Static UI test install button and fixed endpoint/model.
- Full web tests remain green.
- Real Docker verification starts Ollama and confirms `qwen2.5:3b` is available.
