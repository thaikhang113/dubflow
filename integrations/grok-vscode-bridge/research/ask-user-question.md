# `ask_user_question` — the ACP wire format (issue #12)

When Grok's `ask_user_question` tool fires over `grok agent stdio`, the client must
answer a server→client request or the tool reports:

```
Tool `ask_user_question` failed: Client returned an invalid response to user
question: missing field `outcome` at line 1 column 2
```

`line 1 column 2` is the `}` of the bare `{}` the old catch-all
([acp.ts](../src/acp.ts) `handleServerRequest`) replied with — it has no `outcome`
field, so Grok's serde deserializer rejects it. This is **not** in the published
[Agent Client Protocol](https://agentclientprotocol.com) schema; it's an xAI
extension, so the shape below was recovered directly rather than from docs.

## How it was discovered (no live probe needed)

1. **Session logs** (`~/.grok/sessions/<cwd>/<id>/`) gave the *request* the model
   sends and confirmed the error:
   - `chat_history.jsonl` — the `tool_calls[].arguments` for `ask_user_question`:
     `{ "questions": [ { "question", "options": [ {label, description} ], "multiSelect" } ] }`
   - same file — the failing `tool_result`: *"missing field `outcome`…"*
   - `events.jsonl` — `tool_started`/`permission_resolved decision:allow`/`tool_completed`
     (Grok auto-permits the *tool*, then issues the ACP request).

   The session logs are Grok's internal chat record — they do **not** contain the
   ACP method name or the response struct.

2. **The binary** (`~/.grok/bin/grok.exe`, a Rust build) holds both as string
   literals. Extracted with the bundled ripgrep (`~/.grok/vendor/rg-15.0.0-override`),
   treating the exe as text:

   ```bash
   rg -a -o -N "(_?x\.ai/[A-Za-z0-9_./]+)"                  grok.exe   # method names
   rg -a -o -N "[ -~]{0,30}AskUserQuestion[A-Za-z]{0,30}"   grok.exe   # struct names
   rg -a -o -N "(accepted|skip_interview|chat_about_this)"  grok.exe   # serde tag values
   ```

   Key hits:
   - `x.ai/ask_user_questionAskUserQuestionExtRequest` → method **`x.ai/ask_user_question`**,
     request struct `AskUserQuestionExtRequest` (same pattern as
     `x.ai/exit_plan_mode` → `ExitPlanModeExtRequest`).
   - `internally tagged enum AskUserQuestionExtResponse` → the response is an
     **internally-tagged enum on field `outcome`**.
   - variants `AskUserQuestionExtResponse::Accepted` (`with 2 elements`),
     `::ChatAboutThis`, `::SkipInterview`; serde tag values `accepted`,
     `chat_about_this`, `skip_interview`, `cancelled`.
   - field-name pool `…answersannotationschat_about_thispartial_answersskip_interviewcancelledcontent…`
     and `QuestionAnnotation with 2 elements` (→ `notes`, `preview`).

## Request (server → client)

Method `x.ai/ask_user_question` (also accept the `_x.ai/` prefix for symmetry with
`exit_plan_mode`):

```json
{
  "sessionId": "…",
  "questions": [
    {
      "question": "If you could master one random skill…?",
      "options": [
        { "label": "Speaking fluent dolphin", "description": "…", "preview": "…" }
      ],
      "multiSelect": false
    }
  ]
}
```

Note: Grok's question input has **no `header`** field (unlike some AskUserQuestion
tools). `preview` is optional.

## Response (client → server) — `AskUserQuestionExtResponse`

Internally tagged on `outcome`:

| `outcome` | extra fields | meaning |
|---|---|---|
| `accepted` | `answers`, `annotations` | user answered |
| `cancelled` | — | user dismissed |
| `skip_interview` | `partial_answers` | (not used by this client) |
| `chat_about_this` | `content` | user typed free-form instead (not used) |

The client only sends `accepted` (Submit) and `cancelled` (Skip):

```json
{ "outcome": "accepted", "answers": { "<question text>": "<chosen label>" }, "annotations": {} }
{ "outcome": "cancelled" }
```

`answers` is keyed by the exact question text → chosen option **label**
(`HashMap<String,String>`); multi-select labels are joined with `", "`.
`annotations` is keyed by question → `{ notes?, preview? }`; we send `{}`.

**Inferred, not byte-confirmed:** the *keying* of `answers`/`annotations` (by
question text) and the multi-select join. The field names, method name, enum tag,
and variant tags are all from the binary; the keying matches the standard
AskUserQuestion contract (the field set — `answers`, `annotations`, `notes`,
`preview`, `multiSelect`, `label`, `description` — is identical). If a future Grok
expects an array or index-keyed map, only multi-question / multi-select cases would
fail to deserialize; single-select (the common case) is unaffected.

## Implementation

- [src/acp-dispatch.ts](../src/acp-dispatch.ts) — `makeQuestionResponse`,
  `makeQuestionCancelledResponse` (pure).
- [src/acp.ts](../src/acp.ts) — `x.ai/ask_user_question` handler emits
  `questionRequest`; `respondQuestion` / `respondQuestionCancelled` write the reply.
- [src/sidebar.ts](../src/sidebar.ts) — routes `questionRequest` to the webview
  (shown in every mode — a question is read-only and needs a human); handles
  `questionAnswer` / `questionCancel`.
- [media/chat.js](../media/chat.js) — `addQuestionCard` (single question +
  single-select resolves on one click; otherwise pick across questions + Submit;
  Skip → cancel). Answer map built by `buildQuestionAnswers` in
  [media/webview-helpers.js](../media/webview-helpers.js) (pure, unit-tested).

Tests: `test/acp-dispatch.test.ts`, `test/webview-helpers.test.ts`,
`test/question-card.dom.test.ts`, and the `SCENARIO_ASK_QUESTION` round-trip in
`test/acp-integration.test.ts` (fake CLI).
