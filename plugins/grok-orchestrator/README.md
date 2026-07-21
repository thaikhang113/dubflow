# Grok Orchestrator

Repository-scoped Codex plugin and local broker for sharing one isolated Grok ACP session between Codex and VS Code. Natural-language invocation is enabled only when the user explicitly mentions Grok or delegates work to it, for example: `Lấy plan vừa lập bảo Grok code đi`.

## Architecture

```text
Codex MCP client ─┐
                  ├─ authenticated Unix socket ─ broker ─ one Grok ACP process
VS Code external ─┘                              ├─ disposable git worktree
                                                 └─ bubblewrap command sandbox
```

The broker owns session state, filtered append-only events, permission decisions, and the Grok process. Clients receive only `state`, `message`, `permission_requested`, `tool_started`, `tool_finished`, `file_changed`, `test_result`, `turn_completed`, and `error` events. Thoughts, raw environments, and credential-shaped values are never forwarded.

The socket is `${XDG_RUNTIME_DIR}/openclaw-grok-broker.sock`; the broker fails closed when `XDG_RUNTIME_DIR` is unavailable rather than falling back to shared `/tmp`. Persistent session metadata/worktrees are under `${XDG_STATE_HOME:-~/.local/state}/openclaw-grok-broker/`. Broker-owned directories use mode `0700`; the token, socket, session files, and event journals use `0600`.

## Build and validate

```bash
cd server
npm install
npm run typecheck
npm test
```

Validate the plugin and delegation skill:

```bash
python3 ~/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py ..
python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py ../skills/delegate-to-grok
```

## Deployment gate

Do not install the systemd unit, register the plugin, or switch VS Code to external mode until unit/mock/integration/adversarial tests pass and a deliberate live ACP smoke test has been approved. The checked-in service pins an absolute Grok binary and expected version and disables Grok auto-update.

After the gate, install the user unit from `service/openclaw-grok-broker.service`, then configure the VS Code fork with:

```json
{
  "grok.connectionMode": "external",
  "grok.externalSteeringEnabled": false
}
```

External mode is monitor-first. Enabling `grok.externalSteeringEnabled` permits revision messages, permission decisions, and cancellation from the sidebar; it does not broaden broker policy.

## Rollback

Keep `grok.connectionMode` at its default `internal` value, stop/disable the user broker unit if it was installed, and unregister the repo-scoped plugin. Session worktrees are preserved when they contain changes; review and remove them manually rather than deleting broker state blindly.
