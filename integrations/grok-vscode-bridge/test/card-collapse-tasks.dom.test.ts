// DOM-level tests for the v1.4.19 card/UX work, driving the REAL media/chat.js:
//   - permission cards: continuation lands BELOW the card (commitAgentTurn),
//     and collapse to one muted line on answer
//   - restored plan cards render collapsed with a Show/Hide toggle
//   - <system-reminder> background-task turns never bubble into a restored chat
import { describe, it, expect } from "vitest";
import { bootWebview, dispatch, click } from "./webview-harness";

function children(doc: Document): HTMLElement[] {
  const messages = doc.getElementById("messages")!;
  return (Array.from(messages.children) as HTMLElement[]).filter((c) => c.id !== "welcome");
}

const permReq = {
  type: "permissionRequest",
  req: {
    id: 5,
    toolCall: { toolCallId: "x", kind: "execute", title: "Run npm test" },
    options: [
      { optionId: "a", kind: "allow_once", name: "Allow" },
      { optionId: "r", kind: "reject_once", name: "Reject" },
    ],
  },
};

describe("permission card ordering + collapse", () => {
  it("grok's continuation after the card renders BELOW it, not in the prior bubble", () => {
    const { window, doc } = bootWebview();
    dispatch(window, { type: "messageChunk", text: "before the tool" });
    dispatch(window, permReq);
    dispatch(window, { type: "messageChunk", text: "after approval" });

    const kinds = children(doc)
      .filter((c) => c.classList.contains("card") || c.classList.contains("agent"))
      .map((c) => (c.classList.contains("card") ? "card" : "agent"));
    // Two distinct agent bubbles, the permission card sandwiched between them.
    expect(kinds).toEqual(["agent", "card", "agent"]);
  });

  it("collapses to a muted 'Allowed' line and posts the answer on allow", () => {
    const { window, posted, doc } = bootWebview();
    dispatch(window, permReq);
    const allow = [...doc.querySelectorAll(".card.permission .card-actions button")]
      .find((b) => b.textContent === "Allow")!;
    click(window, allow);

    const card = doc.querySelector(".card.permission")!;
    expect(card.classList.contains("perm-resolved")).toBe(true);
    expect(card.querySelector(".card-actions")).toBeNull(); // buttons gone (non-interactive)
    const line = card.querySelector(".perm-resolved-line")!;
    expect(line.classList.contains("perm-allowed")).toBe(true);
    expect(line.querySelector(".perm-resolved-verb")!.textContent).toBe("Allowed");
    expect(line.querySelector(".perm-resolved-what")!.textContent).toBe("Run npm test");
    expect(posted).toContainEqual({ type: "permissionAnswer", requestId: 5, optionId: "a" });
  });

  it("collapses to 'Rejected' on reject", () => {
    const { window, doc } = bootWebview();
    dispatch(window, permReq);
    const reject = [...doc.querySelectorAll(".card.permission .card-actions button")]
      .find((b) => b.textContent === "Reject")!;
    click(window, reject);
    const line = doc.querySelector(".card.permission .perm-resolved-line")!;
    expect(line.classList.contains("perm-rejected")).toBe(true);
    expect(line.querySelector(".perm-resolved-verb")!.textContent).toBe("Rejected");
  });

  it("re-focus replay (permissionRequest + buffered permissionResolved) renders the card collapsed, not active", () => {
    const { window, doc } = bootWebview();
    // What focusSession replays from the buffer: the request, then the resolution
    // the host recorded when the user answered. The card must come back collapsed.
    dispatch(window, permReq);
    dispatch(window, { type: "permissionResolved", requestId: 5, optionId: "a" });
    const card = doc.querySelector(".card.permission")!;
    expect(card.classList.contains("perm-resolved")).toBe(true);
    expect(card.querySelector(".card-actions")).toBeNull(); // not active — no buttons
    expect(card.querySelector(".perm-resolved-verb")!.textContent).toBe("Allowed");
  });
});

describe("restored permission cards (resumed session)", () => {
  it("replays answered permissions as collapsed cards interleaved at their position", () => {
    const { window, doc } = bootWebview();
    // Host posts the saved permissions, then replays the conversation. The card
    // for afterUserMessage:1 should land after the first turn, before the 2nd user msg.
    dispatch(window, { type: "permissionHistoryQueue", permissions: [
      { title: "Run npm test", outcome: "allowed", afterUserMessage: 1 },
      { title: "Delete src/", outcome: "rejected", afterUserMessage: 1 },
    ]});
    dispatch(window, { type: "planHistoryQueue", plans: [] });
    dispatch(window, { type: "historyReplay", active: true });
    dispatch(window, { type: "userMessageChunk", text: "do the thing" });
    dispatch(window, { type: "messageChunk", text: "working on it" });
    dispatch(window, { type: "userMessageChunk", text: "next" });
    dispatch(window, { type: "messageChunk", text: "ok" });
    dispatch(window, { type: "historyReplay", active: false });

    const messages = doc.getElementById("messages")!;
    const seq = (Array.from(messages.children) as HTMLElement[])
      .filter((c) => c.id !== "welcome")
      .map((c) => {
        if (c.classList.contains("perm-resolved")) return "perm:" + c.querySelector(".perm-resolved-verb")!.textContent + ":" + c.querySelector(".perm-resolved-what")!.textContent;
        if (c.classList.contains("user")) return "user:" + c.querySelector(".body")!.textContent;
        if (c.classList.contains("agent")) return "agent:" + c.querySelector(".body")!.textContent;
        return "other";
      });
    expect(seq).toEqual([
      "user:do the thing",
      "agent:working on it",
      "perm:Allowed:Run npm test",
      "perm:Rejected:Delete src/",
      "user:next",
      "agent:ok",
    ]);
  });

  it("anchors a restored card to the exact tool it gated (renders when that tool_call replays)", () => {
    const { window, doc } = bootWebview();
    dispatch(window, { type: "permissionHistoryQueue", permissions: [
      { title: "Run npm test", outcome: "allowed", toolCallId: "tc-9", afterUserMessage: 1 },
    ]});
    dispatch(window, { type: "planHistoryQueue", plans: [] });
    dispatch(window, { type: "historyReplay", active: true });
    dispatch(window, { type: "userMessageChunk", text: "run the tests" });
    dispatch(window, { type: "messageChunk", text: "sure" });
    dispatch(window, { type: "toolCall", call: { toolCallId: "tc-9", title: "Run npm test", kind: "execute" } });
    // The card should already be present right after the gated tool — before the
    // next user message / end of replay.
    const permsAfterTool = doc.querySelectorAll(".card.permission.perm-resolved");
    expect(permsAfterTool).toHaveLength(1);
    expect(permsAfterTool[0].querySelector(".perm-resolved-what")!.textContent).toBe("Run npm test");
    dispatch(window, { type: "userMessageChunk", text: "thanks" });
    dispatch(window, { type: "historyReplay", active: false });
    // Not duplicated by the end-of-replay flush.
    expect(doc.querySelectorAll(".card.permission.perm-resolved")).toHaveLength(1);
  });

  it("anchors a card saved WITHOUT a toolCallId by matching the tool's title on its update", () => {
    const { window, doc } = bootWebview();
    dispatch(window, { type: "permissionHistoryQueue", permissions: [
      { title: "Execute `rm .env`", outcome: "allowed", afterUserMessage: 1 }, // old-build entry, no toolCallId
    ]});
    dispatch(window, { type: "planHistoryQueue", plans: [] });
    dispatch(window, { type: "historyReplay", active: true });
    dispatch(window, { type: "userMessageChunk", text: "remove it" });
    // tool_call is a generic "Shell" (no title match yet)…
    dispatch(window, { type: "toolCall", call: { toolCallId: "tc-x", title: "Shell", kind: "execute" } });
    expect(doc.querySelectorAll(".card.permission.perm-resolved")).toHaveLength(0);
    // …the update carries the real title → matches.
    dispatch(window, { type: "toolCallUpdate", call: { toolCallId: "tc-x", title: "Execute `rm .env`" } });
    const perms = doc.querySelectorAll(".card.permission.perm-resolved");
    expect(perms).toHaveLength(1);
    expect(perms[0].querySelector(".perm-resolved-what")!.textContent).toBe("Execute `rm .env`");
    dispatch(window, { type: "messageChunk", text: "done" });
    dispatch(window, { type: "historyReplay", active: false });
    expect(doc.querySelectorAll(".card.permission.perm-resolved")).toHaveLength(1); // not duplicated at flush
  });

  it("flushes permissions positioned after the last replayed user message at the end", () => {
    const { window, doc } = bootWebview();
    dispatch(window, { type: "permissionHistoryQueue", permissions: [
      { title: "Run build", outcome: "allowed", afterUserMessage: 1 },
    ]});
    dispatch(window, { type: "planHistoryQueue", plans: [] });
    dispatch(window, { type: "historyReplay", active: true });
    dispatch(window, { type: "userMessageChunk", text: "only one" });
    dispatch(window, { type: "messageChunk", text: "done" });
    dispatch(window, { type: "historyReplay", active: false });
    const last = [...doc.getElementById("messages")!.children].pop() as HTMLElement;
    expect(last.classList.contains("perm-resolved")).toBe(true);
    expect(last.querySelector(".perm-resolved-verb")!.textContent).toBe("Allowed");
  });
});

describe("restored plan card is collapsed by default", () => {
  it("hides the plan body behind a Show/Hide toggle", () => {
    const { window, doc } = bootWebview();
    dispatch(window, { type: "planHistory", text: "the restored plan body", verdict: "approved" });
    const card = doc.querySelector(".card.plan.plan-history")!;
    const body = card.querySelector(".plan-body") as HTMLElement;
    const toggle = card.querySelector(".plan-toggle") as HTMLButtonElement;
    // Verdict label + body text remain in the DOM (text accessible to tests),
    // but the body starts hidden.
    expect(card.querySelector(".plan-verdict-label")!.textContent).toBe("Approved");
    expect(body.textContent).toContain("the restored plan body");
    expect(body.hidden).toBe(true);
    expect(toggle.textContent).toBe("Show plan");

    click(window, toggle);
    expect(body.hidden).toBe(false);
    expect(toggle.textContent).toBe("Hide plan");

    click(window, toggle);
    expect(body.hidden).toBe(true);
    expect(toggle.textContent).toBe("Show plan");
  });
});

describe("<system-reminder> background-task turns are not chat bubbles on restore", () => {
  it("suppresses the reminder bubble but keeps grok's reply and real user turns", () => {
    const { window, doc } = bootWebview();
    dispatch(window, { type: "historyReplay", active: true });
    dispatch(window, { type: "userMessageChunk", text: "<system-reminder> task X completed" });
    dispatch(window, { type: "messageChunk", text: "ack" });
    dispatch(window, { type: "userMessageChunk", text: "a real question" });
    dispatch(window, { type: "messageChunk", text: "a real answer" });
    dispatch(window, { type: "historyReplay", active: false });
    const users = [...doc.querySelectorAll(".msg.user .body")].map((b) => b.textContent);
    expect(users).toEqual(["a real question"]);
  });
});
