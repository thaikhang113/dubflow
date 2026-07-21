<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **auto-vietsub-chinese-video** (4441 symbols, 11386 relationships, 300 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> Index stale? Run `node .gitnexus/run.cjs analyze` from the project root — it auto-selects an available runner. No `.gitnexus/run.cjs` yet? `npx gitnexus analyze` (npm 11 crash → `npm i -g gitnexus`; #1939).

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows. For regression review, compare against the default branch: `detect_changes({scope: "compare", base_ref: "main"})`.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `query({search_query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `context({name: "symbolName"})`.
- For security review, `explain({target: "fileOrSymbol"})` lists taint findings (source→sink flows; needs `analyze --pdg`).

## Never Do

- NEVER edit a function, class, or method without first running `impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `rename` which understands the call graph.
- NEVER commit changes without running `detect_changes()` to check affected scope.

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/auto-vietsub-chinese-video/context` | Codebase overview, check index freshness |
| `gitnexus://repo/auto-vietsub-chinese-video/clusters` | All functional areas |
| `gitnexus://repo/auto-vietsub-chinese-video/processes` | All execution flows |
| `gitnexus://repo/auto-vietsub-chinese-video/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
|------|---------------------|
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->

<!-- BEGIN AGENT-SKILLS-GUARDRAILS -->
# Agent Skills Guardrails

Use selected workflows from `/home/haonguyen/agent-skills`.

Before applying a workflow, read the matching `SKILL.md` from `/home/haonguyen/agent-skills/skills/<workflow>/SKILL.md` if it exists. If the file does not exist, report it instead of inventing the workflow.

Default workflows:
- `context-engineering`
- `debugging-and-error-recovery`
- `test-driven-development`
- `incremental-implementation`
- `code-review-and-quality`
- `security-and-hardening`
- `observability-and-instrumentation`
- `git-workflow-and-versioning`

Context rules:
- Do not read the full `/home/haonguyen/CONTEXT_TRANSFER.md`.
- Use `tail -120 /home/haonguyen/CONTEXT_TRANSFER.md` or `rg -n "<task_keyword>" /home/haonguyen/CONTEXT_TRANSFER.md`.
- Main code repo: `/home/haonguyen/.openclaw/workspace`.

Safety rules:
- Run `git status --short` before editing.
- Do not read, print, copy, or modify cookies, tokens, API keys, `.env`, proxy configs, Telegram token files, browser profile/session files, or 9Router secrets.
- Do not restart OpenClaw, 9Router, dashboard, host-runner, watcher, or content-monitor unless explicitly asked.
- Do not commit or push unless explicitly asked.

Code-change workflow:
- Before editing, state likely touched files and intended validation.
- Prefer small incremental diffs.
- After editing, run relevant syntax checks such as `bash -n <file>` or `python3 -m py_compile <file>`.
- Show `git diff --stat` and summarize rollback.
- Do not claim success without validation evidence.

Video pipeline gates:
- A non-empty SRT is not enough.
- `vietnamese.srt` must be Vietnamese, not mostly Chinese.
- `dub.srt` must not have stuck/overlong cues.
- TTS must pass coverage checks.
- `final_video_vi.mp4` must exist before reporting success.
- Failed OCR/translate/TTS should become needs-attention/manual-translate, not successful processed film.
<!-- END AGENT-SKILLS-GUARDRAILS -->
