# Privacy

**Privacy by design.** This extension is built so that it *cannot* learn anything about you or your code. The only data it sends is an anonymous count of usage, with no content and no personal identity attached — and you can turn even that off.

## What is sent

A single, anonymous **`session_start`** event ([Aptabase](https://aptabase.com)), fired on the **first real message** of a session — never the hidden plan-mode primer, and never empty or abandoned sessions. Its only purpose is to gauge how many people use the extension and which models/modes are popular.

The event carries:

| Field | Example | Why |
|---|---|---|
| Anonymous **install id** | a random GUID generated once on your machine | count distinct installs — **not** your account, email, or grok login |
| **mode / model / effort** | `agent` / `grok-build` / `high` | which features are used |
| **OS** + extension **version** | `Windows` / `1.5.1` | platform/version split |
| **Country** | derived by Aptabase from your IP | rough geography |

Country is the only thing derived from your IP, and the **IP itself is discarded — never stored**.

## What is never sent

- **No message content** — nothing you type, and nothing grok replies.
- **No code** — not a single line, ever.
- **No file names or paths**, no workspace name, no repo/branch.
- **No personal identity** — no account, email, grok login, machine name, or any way to tie the install id back to you.

There is no SDK and no third-party tracker — just one small, dependency-free HTTPS POST that is fire-and-forget (it can never slow down, surface to, or break a turn).

## How it's gated

Telemetry sends **only when both** of these are on:

1. VS Code's global telemetry setting — `telemetry.telemetryLevel` (anything other than `off`), and
2. the extension's own `grok.telemetry.enabled` (default `true`).

Either one set to off stops **all** sending.

> **Note on Aptabase build modes.** Events from a published/installed build report as **Release**; events from a development host (running the extension from source) report as **Debug**. In the Aptabase dashboard these are two separate streams toggled by the Bug/Rocket icon — Release data won't appear while the dashboard is in Debug view, and vice-versa.

## How to opt out

Do **either** of the following:

- Set `grok.telemetry.enabled` to `false` in VS Code settings, **or**
- Disable VS Code's global telemetry: set `telemetry.telemetryLevel` to `off`.

Either change takes effect immediately — no reload needed.
