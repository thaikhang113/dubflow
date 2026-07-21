// DOM-level tests for the plan-history restore flow: what the webview renders
// when the host sends `planHistoryQueue` (saved plans from a prior session)
// followed by a `session/load` replay. Drives the REAL media/chat.js so the
// interleaving logic that places plan cards inline with the conversation is
// covered end-to-end, including:
//
//   - empty queue → nothing renders
//   - positioned plans → interleaved at the right user-message boundary
//   - legacy plans (no afterUserMessage) → flushed at end of replay
//   - plans positioned AFTER the last replayed user message → flushed at end
//   - live user messages after restore → still drain the queue at their position
//   - clearMessages → queue + counter reset
//
// These tests cover the state-machine transitions for the v1.2 plan-mode work
// (Approve / Reject / Cancel verdicts + restore-into-prior-state); the bugs
// that surfaced in manual testing — "all plans dumped at the bottom", "plan
// content lost", "stuck in plan mode after Cancel restore" — would all show up
// here if regressed.
import { describe, it, expect } from "vitest";
import { bootWebview, dispatch, click } from "./webview-harness";

// All visible message children in DOM order, mapped to a compact label so
// assertions read like a transcript instead of a DOM dump.
function transcript(doc: Document): string[] {
  const messages = doc.getElementById("messages")!;
  const out: string[] = [];
  for (const child of Array.from(messages.children) as HTMLElement[]) {
    if (child.id === "welcome") continue;
    if (child.classList.contains("plan-history")) {
      const label = child.querySelector(".plan-verdict-label")?.textContent ?? "(no-verdict)";
      const body = child.querySelector(".plan-body")?.textContent?.trim() ?? "";
      out.push(`plan[${label}]: ${body}`);
    } else if (child.classList.contains("user")) {
      out.push(`user: ${child.querySelector(".body")?.textContent ?? ""}`);
    } else if (child.classList.contains("agent")) {
      out.push(`agent: ${child.querySelector(".body")?.textContent ?? ""}`);
    } else {
      out.push(`other: ${child.className}`);
    }
  }
  return out;
}

function plays(window: any, events: any[]) {
  for (const e of events) dispatch(window, e);
}

describe("plan-history queue (restore-flow rendering)", () => {
  it("empty queue: replay finishes with no plan-history cards", () => {
    const { window, doc } = bootWebview();
    plays(window, [
      { type: "planHistoryQueue", plans: [] },
      { type: "historyReplay", active: true },
      { type: "userMessageChunk", text: "hi" },
      { type: "messageChunk", text: "hello" },
      { type: "historyReplay", active: false },
    ]);
    expect(doc.querySelectorAll(".plan-history")).toHaveLength(0);
  });

  it("positioned plan interleaves between the two user messages it bracketed", () => {
    const { window, doc } = bootWebview();
    plays(window, [
      { type: "planHistoryQueue", plans: [
        { text: "first plan", verdict: "rejected", afterUserMessage: 1 },
      ]},
      { type: "historyReplay", active: true },
      { type: "userMessageChunk", text: "draft a plan" },
      { type: "messageChunk", text: "here's the plan" },
      { type: "userMessageChunk", text: "now what?" },
      { type: "messageChunk", text: "okay" },
      { type: "historyReplay", active: false },
    ]);
    expect(transcript(doc)).toEqual([
      "user: draft a plan",
      "agent: here's the plan",
      "plan[Rejected]: first plan",
      "user: now what?",
      "agent: okay",
    ]);
  });

  it("plan positioned AFTER the last replayed user message is flushed at end of replay", () => {
    const { window, doc } = bootWebview();
    plays(window, [
      { type: "planHistoryQueue", plans: [
        { text: "last plan", verdict: "abandoned", afterUserMessage: 1 },
      ]},
      { type: "historyReplay", active: true },
      { type: "userMessageChunk", text: "only one" },
      { type: "messageChunk", text: "agent reply" },
      { type: "historyReplay", active: false },
    ]);
    // afterUserMessage=1 means "drain when about to render user 2" — but there
    // IS no user 2. The end-of-replay flush picks it up so we don't lose it.
    expect(transcript(doc)).toEqual([
      "user: only one",
      "agent: agent reply",
      "plan[Cancelled]: last plan",
    ]);
  });

  it("legacy plans (no afterUserMessage) always flush at end of replay", () => {
    const { window, doc } = bootWebview();
    plays(window, [
      { type: "planHistoryQueue", plans: [
        { text: "ancient plan" }, // no verdict, no position
      ]},
      { type: "historyReplay", active: true },
      { type: "userMessageChunk", text: "msg1" },
      { type: "messageChunk", text: "a1" },
      { type: "userMessageChunk", text: "msg2" },
      { type: "historyReplay", active: false },
    ]);
    const t = transcript(doc);
    // The legacy plan ends up at the very bottom; no verdict label present.
    expect(t[t.length - 1]).toBe("plan[(no-verdict)]: ancient plan");
    expect(t.slice(0, -1)).toEqual([
      "user: msg1",
      "agent: a1",
      "user: msg2",
    ]);
  });

  it("multiple positioned plans interleave at their distinct positions", () => {
    const { window, doc } = bootWebview();
    plays(window, [
      { type: "planHistoryQueue", plans: [
        { text: "P1", verdict: "rejected", afterUserMessage: 1 },
        { text: "P2", verdict: "rejected", afterUserMessage: 2 },
        { text: "P3", verdict: "abandoned", afterUserMessage: 3 },
      ]},
      { type: "historyReplay", active: true },
      { type: "userMessageChunk", text: "u1" },
      { type: "messageChunk", text: "a1" },
      { type: "userMessageChunk", text: "u2" },
      { type: "messageChunk", text: "a2" },
      { type: "userMessageChunk", text: "u3" },
      { type: "messageChunk", text: "a3" },
      { type: "historyReplay", active: false },
    ]);
    expect(transcript(doc)).toEqual([
      "user: u1",
      "agent: a1",
      "plan[Rejected]: P1",
      "user: u2",
      "agent: a2",
      "plan[Rejected]: P2",
      "user: u3",
      "agent: a3",
      "plan[Cancelled]: P3", // flushed at end since there's no user 4
    ]);
  });

  it("strips the [Plan ...] protocol marker from a replayed verdict comment", () => {
    const { window, doc } = bootWebview();
    plays(window, [
      { type: "historyReplay", active: true },
      { type: "userMessageChunk", text: "real question" },
      { type: "messageChunk", text: "answer" },
      // grok echoes the wire-level prompt verbatim on replay, marker and all.
      { type: "userMessageChunk", text: "[Plan cancelled] tell me what you saw" },
      { type: "messageChunk", text: "acknowledged" },
      { type: "historyReplay", active: false },
    ]);
    expect(transcript(doc)).toEqual([
      "user: real question",
      "agent: answer",
      "user: tell me what you saw", // marker hidden, comment kept
      "agent: acknowledged",
    ]);
  });

  it("suppresses a marker-only verdict bubble, keeps grok's reply, and positions the plan before it", () => {
    const { window, doc } = bootWebview();
    plays(window, [
      { type: "planHistoryQueue", plans: [{ text: "PX", verdict: "abandoned", afterUserMessage: 1 }] },
      { type: "historyReplay", active: true },
      { type: "userMessageChunk", text: "make a plan" },
      { type: "messageChunk", text: "here is a plan" },
      { type: "userMessageChunk", text: "[Plan cancelled]" }, // marker-only: no comment
      { type: "messageChunk", text: "ok, cancelled" },
      { type: "historyReplay", active: false },
    ]);
    expect(transcript(doc)).toEqual([
      "user: make a plan",
      "agent: here is a plan",
      "plan[Cancelled]: PX",   // drained before the (suppressed) verdict turn
      "agent: ok, cancelled",  // grok's reply to the cancel still renders
    ]);
  });

  it("marker-only verdicts don't desync later plan positions (count stays aligned)", () => {
    const { window, doc } = bootWebview();
    plays(window, [
      { type: "planHistoryQueue", plans: [
        { text: "P1", verdict: "abandoned", afterUserMessage: 1 },
        { text: "P2", verdict: "rejected", afterUserMessage: 2 },
      ]},
      { type: "historyReplay", active: true },
      { type: "userMessageChunk", text: "u1" },
      { type: "messageChunk", text: "a1" },
      { type: "userMessageChunk", text: "[Plan cancelled]" }, // marker-only, not counted
      { type: "messageChunk", text: "a2" },
      { type: "userMessageChunk", text: "u2" },
      { type: "messageChunk", text: "a3" },
      { type: "userMessageChunk", text: "[Plan rejected] do better" },
      { type: "messageChunk", text: "a4" },
      { type: "historyReplay", active: false },
    ]);
    expect(transcript(doc)).toEqual([
      "user: u1",
      "agent: a1",
      "plan[Cancelled]: P1", // before the marker-only verdict (afterUserMessage 1)
      "agent: a2",
      "user: u2",
      "agent: a3",
      "plan[Rejected]: P2",  // before the reject-with-comment (afterUserMessage 2)
      "user: do better",     // marker stripped
      "agent: a4",
    ]);
  });

  it("multiple plans at the SAME position drain together (all rendered before next user msg)", () => {
    const { window, doc } = bootWebview();
    plays(window, [
      { type: "planHistoryQueue", plans: [
        { text: "first attempt", verdict: "rejected", afterUserMessage: 1 },
        { text: "second attempt", verdict: "rejected", afterUserMessage: 1 },
      ]},
      { type: "historyReplay", active: true },
      { type: "userMessageChunk", text: "u1" },
      { type: "messageChunk", text: "a1" },
      { type: "userMessageChunk", text: "u2" },
      { type: "historyReplay", active: false },
    ]);
    expect(transcript(doc)).toEqual([
      "user: u1",
      "agent: a1",
      "plan[Rejected]: first attempt",
      "plan[Rejected]: second attempt",
      "user: u2",
    ]);
  });

  it("queued plan-history cards open the matching plan file link", () => {
    const { window, posted, doc } = bootWebview();
    plays(window, [
      { type: "planHistoryQueue", plans: [
        {
          text: "first restored plan",
          verdict: "rejected",
          afterUserMessage: 0,
          planPath: "/tmp/grok/first-plan.md",
          planName: "first-plan.md",
        },
        {
          text: "second restored plan",
          verdict: "abandoned",
          afterUserMessage: 0,
          planPath: "/tmp/grok/second-plan.md",
          planName: "second-plan.md",
        },
      ]},
      { type: "userMessage", text: "continue", chips: [] },
    ]);

    const cards = [...doc.querySelectorAll(".card.plan.plan-history")] as HTMLElement[];
    expect(cards[0].querySelector(".plan-file-link code")!.textContent).toBe("first-plan.md");
    expect(cards[1].querySelector(".plan-file-link code")!.textContent).toBe("second-plan.md");
    click(window, cards[0].querySelector(".plan-file-link")!);
    click(window, cards[1].querySelector(".plan-file-link")!);

    expect(posted).toEqual([
      { type: "openFile", path: "/tmp/grok/first-plan.md" },
      { type: "openFile", path: "/tmp/grok/second-plan.md" },
    ]);
  });

  it("live user message after restore still drains queued plans at its position", () => {
    const { window, doc } = bootWebview();
    plays(window, [
      { type: "planHistoryQueue", plans: [
        { text: "saved-during-replay", verdict: "rejected", afterUserMessage: 1 },
      ]},
      { type: "historyReplay", active: true },
      { type: "userMessageChunk", text: "old" },
      { type: "messageChunk", text: "old-reply" },
      { type: "historyReplay", active: false },
    ]);
    // After replay, the plan was flushed at the end (no user 2 in replay).
    // Now a live user message arrives. The queue is empty, so nothing extra.
    dispatch(window, { type: "userMessage", text: "live", chips: [] });
    expect(transcript(doc)).toEqual([
      "user: old",
      "agent: old-reply",
      "plan[Rejected]: saved-during-replay",
      "user: live",
    ]);
  });

  it("if no flush happened (plan still queued at replay end), a live user msg drains it inline", () => {
    // This covers a corner where afterUserMessage > number of replayed users:
    // we flush at end of replay (the test above), but a more subtle case —
    // queue arrived but historyReplay was never toggled because the session
    // was created fresh — needs the live path to drain. Synthesize that here.
    const { window, doc } = bootWebview();
    plays(window, [
      { type: "planHistoryQueue", plans: [
        { text: "queued", verdict: "rejected", afterUserMessage: 0 },
      ]},
      // No historyReplay events. A live user message arrives next.
      { type: "userMessage", text: "fresh", chips: [] },
    ]);
    // afterUserMessage:0 ≤ initial userMsgCount (0): drains before "fresh" renders.
    expect(transcript(doc)).toEqual([
      "plan[Rejected]: queued",
      "user: fresh",
    ]);
  });

  it("clearMessages resets the queue and the user-message counter", () => {
    const { window, doc } = bootWebview();
    plays(window, [
      { type: "planHistoryQueue", plans: [
        { text: "stale", verdict: "rejected", afterUserMessage: 0 },
      ]},
      { type: "clearMessages" },
      // After clear, the queue should be gone — no plan card should render
      // when subsequent user messages arrive.
      { type: "userMessage", text: "u1", chips: [] },
    ]);
    expect(doc.querySelectorAll(".plan-history")).toHaveLength(0);
    expect(transcript(doc)).toEqual(["user: u1"]);
  });

  it("hides the primer + grok's ack on restore so only real user content renders", () => {
    const { window, doc } = bootWebview();
    // Simulate a replay where the FIRST recorded user message is the
    // extension's primer (which the CLI replays as user_message_chunk because
    // it was originally sent via session/prompt). The primer + grok's response
    // to it should be entirely invisible; the real conversation starts at the
    // next user message.
    plays(window, [
      { type: "historyReplay", active: true },
      { type: "userMessageChunk", text: "[grok-build-vscode primer v2]\n\nignore this on restore" },
      { type: "thoughtChunk", text: "the user wants me to acknowledge…" },
      { type: "messageChunk", text: "Acknowledged." },
      { type: "userMessageChunk", text: "actual first user message" },
      { type: "messageChunk", text: "real agent reply" },
      { type: "historyReplay", active: false },
    ]);
    // The primer's user bubble, its agent ack, and its thinking trace must all
    // be absent. Only the real exchange below should render.
    const t = transcript(doc);
    expect(t).toEqual([
      "user: actual first user message",
      "agent: real agent reply",
    ]);
    expect(doc.querySelectorAll(".msg.thinking").length).toBe(0);
  });

  it("matches any primer version (v1, v2, …) for forward compat", () => {
    const { window, doc } = bootWebview();
    plays(window, [
      { type: "historyReplay", active: true },
      { type: "userMessageChunk", text: "[grok-build-vscode primer v17] some future primer" },
      { type: "messageChunk", text: "Acknowledged." },
      { type: "userMessageChunk", text: "real msg" },
      { type: "historyReplay", active: false },
    ]);
    expect(transcript(doc).filter((s) => s.startsWith("user:"))).toEqual(["user: real msg"]);
  });

  it("the primer marker only suppresses during replay — a live user typing the marker is shown", () => {
    const { window, doc } = bootWebview();
    // Live user message (not during historyReplay) with the marker text. It's
    // theoretically possible for a user to paste the marker; we don't want to
    // hide their messages outside the restore flow.
    plays(window, [
      { type: "userMessage", text: "[grok-build-vscode primer v2] paste accident", chips: [] },
    ]);
    expect(transcript(doc)).toEqual([
      "user: [grok-build-vscode primer v2] paste accident",
    ]);
  });
});

describe("plan card verdict labels (live exit_plan_mode flow)", () => {
  it("each verdict click produces the matching status label on the resolved card", () => {
    const cases: Array<{ button: string; verdict: string; label: string }> = [
      { button: "Approve & implement", verdict: "approved",  label: "Approved" },
      { button: "Reject",              verdict: "rejected",  label: "Rejected" },
      { button: "Cancel",              verdict: "abandoned", label: "Cancelled" },
    ];
    for (const c of cases) {
      const { window, posted, doc } = bootWebview();
      dispatch(window, { type: "exitPlanRequest", req: { id: 1, plan: "p" } });
      const btn = [...doc.querySelectorAll(".card.plan .card-actions button")]
        .find((b) => b.textContent === c.button) as HTMLButtonElement;
      btn.dispatchEvent(new (window as any).MouseEvent("click", { bubbles: true, cancelable: true }));

      const card = doc.querySelector(".card.plan")!;
      expect(card.classList.contains("resolved")).toBe(true);
      // Buttons/comment box are removed; a colored verdict label is shown.
      expect(card.querySelector(".card-actions")).toBeNull();
      const label = card.querySelector(".plan-verdict-label")!;
      expect(label.textContent).toBe(c.label);
      expect(label.classList.contains("plan-verdict-" + c.verdict)).toBe(true);
      expect(posted[0]).toMatchObject({ verdict: c.verdict });
    }
  });
});

describe("agentReset (used by host to drop the false-approval ramble)", () => {
  it("removes the in-flight agent bubble from the DOM", () => {
    const { window, doc } = bootWebview();
    dispatch(window, { type: "messageChunk", text: "the plan was approv..." });
    expect(doc.querySelector(".msg.agent")).not.toBeNull();

    dispatch(window, { type: "agentReset" });
    expect(doc.querySelector(".msg.agent")).toBeNull();
  });

  it("subsequent messageChunks create a fresh agent bubble (state cleared)", () => {
    const { window, doc } = bootWebview();
    dispatch(window, { type: "messageChunk", text: "approved..." });
    const firstBubble = doc.querySelector(".msg.agent");
    expect(firstBubble).not.toBeNull();

    dispatch(window, { type: "agentReset" });
    expect(doc.querySelector(".msg.agent")).toBeNull(); // the old one is gone

    dispatch(window, { type: "messageChunk", text: "actually, the plan is rejected" });
    const after = doc.querySelectorAll(".msg.agent");
    // Exactly ONE fresh agent bubble; it's a different element from the first
    // (the false-approval text didn't leak into the new bubble).
    expect(after).toHaveLength(1);
    expect(after[0]).not.toBe(firstBubble);
  });
});
