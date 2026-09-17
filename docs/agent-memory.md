# Agent Memory Workflow

DubFlow development uses three context layers:

1. **GitNexus**: symbol graph, callers, execution flows, and pre-change impact.
2. **Loop Engineer**: local project state and repeatable work cadence.
3. **TencentDB Agent Memory**: durable architecture, decisions, bugs, tasks,
   tests, and release knowledge.

## Local Services

TencentDB Agent Memory runs outside DubFlow:

- Memory Core: `http://127.0.0.1:8420`
- Memory Hub: `http://127.0.0.1:8125`
- Knowledge service: `http://127.0.0.1:8424`
- Memory Proxy: `http://127.0.0.1:8096`

Proxy health check:

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8096/health
```

## Session Start

1. Read `STATE.md`.
2. Query relevant TencentDB memory.
3. Use GitNexus `context` for unfamiliar symbols.
4. Use GitNexus `impact` before editing any function, class, or method.

## Session End

Store only durable project knowledge:

- architecture or API decisions
- root cause and prevention for bugs
- test or release lessons
- repeatable workflow improvements

Do not store API keys, cookies, user media, model files, or generated output.

## Codex Proxy

Codex global config routes future sessions through the local TencentDB Memory
Proxy at `/codex/default`. Restart Codex after changing that config. Enter Plan
mode before the first proxied turn so TencentDB session initialization can ask
for Team, Agent, and Task.
