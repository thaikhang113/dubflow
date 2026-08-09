# End-User Doctor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Runtime Doctor clear and actionable for non-technical end users.

**Architecture:** Keep the current backend contract. Render a summary, severity-sorted workflow list, plain-language fixes and links to existing screens using vanilla JavaScript and CSS.

**Tech Stack:** Vanilla JavaScript, CSS, Python unittest.

## Global Constraints

- Work only on branch `tool`.
- Never display secret values.
- Add no dependency or backend route.
- Keep automatic Doctor refresh.

---

### Task 1: End-User Doctor UI

**Files:**
- Modify: `web_tool/static/app.js`
- Modify: `web_tool/static/styles.css`
- Modify: `web_tool/tests/test_static_ui.py`

**Interfaces:**
- Consumes: existing `GET /api/runtime/doctor` response.
- Produces: summary totals, sorted workflow rows, guidance and action buttons.

- [x] Add a static contract test for summary totals, guidance and action controls.
- [x] Run `python -m unittest -v web_tool.tests.test_static_ui` and verify failure.
- [x] Add minimal rendering and navigation code.
- [x] Add responsive CSS using existing colors and components.
- [x] Run full web tests and verify success.
- [x] Check desktop and mobile browser layouts.
- [ ] Commit and push `origin/tool`.
