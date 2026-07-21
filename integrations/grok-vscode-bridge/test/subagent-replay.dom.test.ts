// Replays a REAL Composer-agent wire capture through the shipped chat.js:
// test/fixtures/composer-subagent-session.jsonl holds the (trimmed) tool
// records of the "10 tool calls + 5 subagents in mixed order" demo session
// that produced the original mess — false Subagent cards from Greps titled
// with subagent-ish search patterns, and Task delegations that never complete
// on the tool channel (Composer's completion arrives ONLY via the
// subagent_spawned/subagent_finished lifecycle events).
import { describe, it, expect } from "vitest";
import * as fs from "node:fs";
import * as path from "node:path";
import { bootWebview, dispatch } from "./webview-harness";

const RECORDS = fs
  .readFileSync(path.join(__dirname, "fixtures", "composer-subagent-session.jsonl"), "utf8")
  .split("\n")
  .filter(Boolean)
  .map((l) => JSON.parse(l));

function replayAll(window: any) {
  for (const rec of RECORDS) {
    dispatch(window, { type: rec.sessionUpdate === "tool_call" ? "toolCall" : "toolCallUpdate", call: rec });
  }
}

describe("composer-agent mixed 10-tools + 5-subagents session (real wire replay)", () => {
  it("cards exactly the 6 Task delegations — subagent-titled Greps stay in the tool groups", () => {
    const { window, doc } = bootWebview();
    replayAll(window);

    const cards = [...doc.querySelectorAll(".subagent-card")];
    expect(cards).toHaveLength(6);
    const titles = cards.map((c) => c.querySelector(".subagent-title")!.textContent);
    expect(titles).toContain("Demo subagent file count");
    expect(titles).toContain("Subagent 1: count tests");
    expect(titles).toContain("Subagent 5: docs files");
    // The Greps whose PATTERNS were subagent-ish must not have become cards.
    expect(titles).not.toContain("spawn_subagent");
    expect(titles).not.toContain("isSubagentToolCall");
    // And ordinary tools still landed in generic groups.
    expect(doc.querySelector(".tool-group")).not.toBeNull();
  });

  it("Task cards complete from the untitled completion update without losing their titles", () => {
    const { window, doc } = bootWebview();
    replayAll(window);

    // Composer's completion is a THIRD update per delegation: status completed,
    // NO _meta, title "" (must not downgrade the shown title), the output as
    // rawOutput {type:"Text", text} / content text wrapped in the CLI envelope.
    const cards = [...doc.querySelectorAll(".subagent-card")];
    expect(cards.every((c) => c.classList.contains("subagent-done"))).toBe(true);
    expect(cards.every((c) => !c.querySelector(".blink-dots"))).toBe(true);

    const first = cards[0];
    // The untitled completion update did NOT wipe the description.
    expect(first.querySelector(".subagent-title")!.textContent).toBe("Demo subagent file count");
    const body = first.querySelector(".subagent-result") as HTMLElement;
    expect(body.hidden).toBe(true); // collapsed until clicked
    expect(body.textContent).toContain("Output of the subagent:");
    // The CLI envelope is stripped from the child's words.
    expect(body.textContent).not.toContain("This is the output of the subagent:");
    expect(body.textContent).not.toContain("<response>");
  });

  it("the subagent_finished lifecycle event fills in the duration Composer's completion lacks", () => {
    const { window, doc } = bootWebview();
    replayAll(window);
    const first = doc.querySelector(".subagent-card")!;
    expect(first.querySelector(".subagent-time")!.textContent).toBe(""); // no duration on the tool channel

    dispatch(window, {
      type: "subagentUpdate",
      update: { sessionUpdate: "subagent_spawned", subagent_id: "child-1", subagent_type: "generalPurpose" },
    });
    dispatch(window, {
      type: "subagentUpdate",
      update: { sessionUpdate: "subagent_finished", subagent_id: "child-1", status: "completed", duration_ms: 7343 },
    });
    // spawned tags FIFO — but every card is already done, so the late finish
    // only fills the duration of the matching (first) card.
    expect(first.querySelector(".subagent-time")!.textContent).toBe("· 7s");
  });

  it("the lifecycle event is a completion backstop when the tool channel never completes", () => {
    const { window, doc } = bootWebview();
    dispatch(window, {
      type: "toolCall",
      call: {
        toolCallId: "t-solo",
        title: "Task",
        _meta: { "x.ai/tool": { name: "Task" } },
        rawInput: { description: "Count things", subagent_type: "generalPurpose", prompt: "count" },
      },
    });
    const card = doc.querySelector(".subagent-card")!;
    expect(card.querySelector(".blink-dots")).not.toBeNull();

    dispatch(window, { type: "subagentUpdate", update: { sessionUpdate: "subagent_spawned", subagent_id: "c9" } });
    dispatch(window, {
      type: "subagentUpdate",
      update: { sessionUpdate: "subagent_finished", subagent_id: "c9", status: "completed", duration_ms: 2100, output: "response:\n<response>\nAll counted.\n</response>" },
    });
    expect(card.classList.contains("subagent-done")).toBe(true);
    expect(card.querySelector(".blink-dots")).toBeNull();
    expect(card.querySelector(".subagent-time")!.textContent).toBe("· 2s");
    const body = card.querySelector(".subagent-result") as HTMLElement;
    expect(body.textContent).toContain("All counted.");
    expect(body.textContent).not.toContain("<response>");
  });

  it("a background spawn completes from the poller's TaskOutput, not its started-ack", () => {
    // Real grok-build background shape (accredia session): spawn_subagent with
    // background:true "completes" instantly with a started-ack; the child's
    // real output arrives minutes later on the get_command_or_subagent_output
    // poller (the lifecycle events are logged by the CLI but not transmitted).
    const { window, doc } = bootWebview();
    dispatch(window, {
      type: "toolCall",
      call: {
        toolCallId: "bg-spawn",
        title: "spawn_subagent",
        _meta: { "x.ai/tool": { name: "spawn_subagent" } },
        rawInput: { prompt: "say hi", description: "Simple subagent greeting demo", subagent_type: "general-purpose", background: true },
      },
    });
    dispatch(window, {
      type: "toolCallUpdate",
      call: {
        toolCallId: "bg-spawn",
        title: "Simple subagent greeting demo",
        rawInput: { variant: "Task", description: "Simple subagent greeting demo", subagent_type: "general-purpose", run_in_background: true, task_id: "019f52f1" },
      },
    });
    dispatch(window, {
      type: "toolCallUpdate",
      call: {
        toolCallId: "bg-spawn",
        status: "completed",
        title: "",
        rawOutput: { type: "Text", text: "Subagent started in background.\nsubagent_id: 019f52f1\ntype: general-purpose\n\nUse get_command_or_subagent_output with task_ids=[\"019f52f1\"] and timeout_ms to wait for results." },
      },
    });

    const card = doc.querySelector(".subagent-card")!;
    // Still running — the ack is not the result.
    expect(card.classList.contains("subagent-done")).toBe(false);
    expect(card.querySelector(".blink-dots")).not.toBeNull();

    // The poller (a DIFFERENT toolCallId) completes with the real output.
    dispatch(window, {
      type: "toolCallUpdate",
      call: {
        toolCallId: "poller-1",
        status: "completed",
        title: "Get task output: 019f52f1",
        rawOutput: {
          type: "TaskOutput",
          Result: {
            task_id: "019f52f1",
            command: "[subagent:general-purpose] Simple subagent greeting demo",
            status: "completed",
            duration_secs: 70.472,
            output: "Hi! I'm a Grok Build subagent.\n\n<subagent_meta>id=019f52f1, type=general-purpose</subagent_meta>",
          },
        },
      },
    });
    expect(card.classList.contains("subagent-done")).toBe(true);
    expect(card.querySelector(".subagent-time")!.textContent).toBe("· 70s");
    expect(card.querySelector(".subagent-result")!.textContent).toContain("Hi! I'm a Grok Build subagent.");
    expect(card.querySelector(".subagent-result")!.textContent).not.toContain("started in background");
    expect(card.querySelector(".subagent-result")!.textContent).not.toContain("subagent_meta");
  });

  it("historyReplay end settles never-completed delegation rows (no dots on restored history)", () => {
    const { window, doc } = bootWebview();
    dispatch(window, { type: "historyReplay", active: true });
    replayAll(window);
    dispatch(window, { type: "historyReplay", active: false });
    expect(doc.querySelectorAll(".subagent-card .blink-dots")).toHaveLength(0);
  });
});
