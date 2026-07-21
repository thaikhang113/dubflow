// DOM-level test of the plan-review card — drives the REAL shipped media/chat.js
// inside a happy-dom window, dispatches the same messages sidebar.ts posts
// (exitPlanRequest / planNotice / planBlocked), clicks the rendered buttons, and
// asserts on the postMessage payload that goes back to the extension host.
//
// This covers the regression-prone webview logic that a pure unit test can't:
//   - "Keep planning" sends verdict:"rejected", and includes `comment` ONLY when
//     the feedback textarea is non-empty (the `...(comment ? {comment} : {})` spread)
//   - "Approve & implement" sends verdict:"approved" and never a comment
//   - after a click the card resolves and both buttons + textarea disable
//   - planNotice / planBlocked render a .plan-notice with the right text
//
// What it deliberately does NOT cover: real VS Code rendering, CSS, the actual
// acquireVsCodeApi bridge, and the round-trip to client.setMode/client.prompt.
// Those need a human or the @vscode/test-electron suite (roadmap item #1).
import { describe, it, expect } from "vitest";
import { bootWebview, dispatch, click } from "./webview-harness";

describe("plan card (real chat.js in a DOM)", () => {
  it("renders a plan card with body, feedback textarea, and three action buttons", () => {
    const { window, doc } = bootWebview();
    dispatch(window, {
      type: "exitPlanRequest",
      req: {
        id: 7,
        plan: "1. add subtract()\n2. add test",
        planPath: "/tmp/grok/plan2.md",
        planName: "plan2.md",
      },
    });

    const card = doc.querySelector(".card.plan");
    expect(card).not.toBeNull();
    expect(card!.querySelector(".plan-body")!.textContent).toContain("add subtract()");
    expect(card!.querySelector(".plan-file-link code")!.textContent).toBe("plan2.md");
    expect(card!.querySelector("textarea.plan-feedback")).not.toBeNull();
    const labels = [...card!.querySelectorAll(".card-actions button")].map((b) => b.textContent);
    expect(labels).toEqual(["Approve & implement", "Reject", "Cancel"]);
  });

  it("opens the live plan link without resolving the approval card", () => {
    const plan = "# Plan\n\n- inspect\n- edit\n\n```ts\nconst x = 1;\n```";
    const { window, posted, doc } = bootWebview();
    dispatch(window, {
      type: "exitPlanRequest",
      req: { id: 8, plan, planPath: "/tmp/grok/plan2.md", planName: "plan2.md" },
    });

    const card = doc.querySelector(".card.plan")!;
    const feedback = card.querySelector("textarea.plan-feedback") as HTMLTextAreaElement;
    feedback.value = "  keep this comment  ";
    const link = card.querySelector(".plan-file-link") as HTMLAnchorElement;
    expect(link.title).toBe("/tmp/grok/plan2.md");
    click(window, link);

    expect(posted).toEqual([{ type: "openFile", path: "/tmp/grok/plan2.md" }]);
    expect(card.classList.contains("resolved")).toBe(false);
    expect(card.querySelector(".plan-verdict-label")).toBeNull();
    const approve = [...card.querySelectorAll(".card-actions button")]
      .find((b) => b.textContent === "Approve & implement") as HTMLButtonElement;
    expect(approve.disabled).toBe(false);
    expect(feedback.disabled).toBe(false);
    expect(feedback.value).toBe("  keep this comment  ");
  });

  it("planResolved collapses a replayed plan card so it can't come back actionable", () => {
    // Re-focus replay order after a live Cancel: the buffered exitPlanRequest
    // (which rebuilds the actionable card) followed by the buffered resolution.
    const { window, doc } = bootWebview();
    dispatch(window, { type: "exitPlanRequest", req: { id: 21, plan: "p" } });
    dispatch(window, { type: "planResolved", requestId: 21, verdict: "abandoned" });

    const card = doc.querySelector(".card.plan")!;
    expect(card.classList.contains("resolved")).toBe(true);
    expect(card.querySelector(".card-actions")).toBeNull();
    expect(card.querySelector("textarea.plan-feedback")).toBeNull();
    expect(card.querySelector(".plan-verdict-label")!.textContent).toBe("Cancelled");

    // No plan-file link on this card (snapshot creation failed) → the text
    // stays reachable behind the Show/Hide fallback toggle.
    const body = card.querySelector(".plan-body") as HTMLElement;
    const toggle = card.querySelector(".plan-toggle") as HTMLButtonElement;
    expect(body.hidden).toBe(true);
    expect(toggle.textContent).toBe("Show plan");
    click(window, toggle);
    expect(body.hidden).toBe(false);
    expect(toggle.textContent).toBe("Hide plan");
  });

  it("a resolved card with a plan-file link drops the inline plan entirely (the file IS the plan)", () => {
    const { window, doc } = bootWebview();
    dispatch(window, {
      type: "exitPlanRequest",
      req: { id: 23, plan: "1. step", planPath: "/tmp/grok/plan9.md", planName: "plan9.md" },
    });
    const approve = [...doc.querySelectorAll(".card.plan .card-actions button")]
      .find((b) => b.textContent === "Approve & implement") as HTMLButtonElement;
    click(window, approve);

    const card = doc.querySelector(".card.plan")!;
    expect(card.classList.contains("resolved")).toBe(true);
    expect(card.querySelector(".plan-body")).toBeNull();
    expect(card.querySelector(".plan-toggle")).toBeNull();
    expect(card.querySelector(".plan-file-link code")!.textContent).toBe("plan9.md");
    expect(card.querySelector(".plan-verdict-label")!.textContent).toBe("Approved");
  });

  it("planResolved is idempotent after a live click already collapsed the card", () => {
    const { window, doc } = bootWebview();
    dispatch(window, { type: "exitPlanRequest", req: { id: 22, plan: "p" } });
    const cancel = [...doc.querySelectorAll(".card.plan .card-actions button")]
      .find((b) => b.textContent === "Cancel") as HTMLButtonElement;
    click(window, cancel); // live collapse
    dispatch(window, { type: "planResolved", requestId: 22, verdict: "abandoned" }); // buffered echo

    const card = doc.querySelector(".card.plan")!;
    expect(card.querySelectorAll(".plan-verdict-label")).toHaveLength(1); // no double label
  });

  it("'Reject' with empty feedback sends verdict:rejected and NO comment key", () => {
    const { window, posted, doc } = bootWebview();
    dispatch(window, { type: "exitPlanRequest", req: { id: 11, plan: "p" } });

    const reject = [...doc.querySelectorAll(".card.plan .card-actions button")]
      .find((b) => b.textContent === "Reject") as HTMLButtonElement;
    click(window, reject);

    expect(posted).toHaveLength(1);
    expect(posted[0]).toMatchObject({ type: "exitPlanAnswer", requestId: 11, verdict: "rejected" });
    expect("comment" in posted[0]).toBe(false);
  });

  it("'Reject' with feedback text includes the trimmed comment", () => {
    const { window, posted, doc } = bootWebview();
    dispatch(window, { type: "exitPlanRequest", req: { id: 12, plan: "p" } });

    const card = doc.querySelector(".card.plan")!;
    (card.querySelector("textarea.plan-feedback") as HTMLTextAreaElement).value = "  use a __tests__ folder  ";
    const reject = [...card.querySelectorAll(".card-actions button")]
      .find((b) => b.textContent === "Reject") as HTMLButtonElement;
    click(window, reject);

    expect(posted[0]).toEqual({
      type: "exitPlanAnswer",
      requestId: 12,
      verdict: "rejected",
      comment: "use a __tests__ folder",
    });
  });

  it("'Approve & implement' sends verdict:approved without a comment when textarea is empty", () => {
    const { window, posted, doc } = bootWebview();
    dispatch(window, { type: "exitPlanRequest", req: { id: 13, plan: "p" } });

    const approve = [...doc.querySelectorAll(".card.plan .card-actions button")]
      .find((b) => b.textContent === "Approve & implement") as HTMLButtonElement;
    click(window, approve);

    expect(posted[0]).toMatchObject({ type: "exitPlanAnswer", requestId: 13, verdict: "approved" });
    expect("comment" in posted[0]).toBe(false);
  });

  it("'Approve & implement' includes the trimmed comment when the user types one (so nuance like 'skip tests' reaches grok)", () => {
    const { window, posted, doc } = bootWebview();
    dispatch(window, { type: "exitPlanRequest", req: { id: 14, plan: "p" } });

    const card = doc.querySelector(".card.plan")!;
    (card.querySelector("textarea.plan-feedback") as HTMLTextAreaElement).value = "  use sqlite instead of postgres  ";
    const approve = [...card.querySelectorAll(".card-actions button")]
      .find((b) => b.textContent === "Approve & implement") as HTMLButtonElement;
    click(window, approve);

    expect(posted[0]).toEqual({
      type: "exitPlanAnswer",
      requestId: 14,
      verdict: "approved",
      comment: "use sqlite instead of postgres",
    });
  });

  it("'Cancel' with empty feedback sends verdict:abandoned and NO comment key", () => {
    const { window, posted, doc } = bootWebview();
    dispatch(window, { type: "exitPlanRequest", req: { id: 15, plan: "p" } });

    const cancel = [...doc.querySelectorAll(".card.plan .card-actions button")]
      .find((b) => b.textContent === "Cancel") as HTMLButtonElement;
    click(window, cancel);

    expect(posted[0]).toMatchObject({ type: "exitPlanAnswer", requestId: 15, verdict: "abandoned" });
    expect("comment" in posted[0]).toBe(false);
  });

  it("'Cancel' with feedback includes the trimmed comment (so the user's reason reaches grok)", () => {
    const { window, posted, doc } = bootWebview();
    dispatch(window, { type: "exitPlanRequest", req: { id: 16, plan: "p" } });

    const card = doc.querySelector(".card.plan")!;
    (card.querySelector("textarea.plan-feedback") as HTMLTextAreaElement).value = "  too ambitious for v1  ";
    const cancel = [...card.querySelectorAll(".card-actions button")]
      .find((b) => b.textContent === "Cancel") as HTMLButtonElement;
    click(window, cancel);

    expect(posted[0]).toEqual({
      type: "exitPlanAnswer",
      requestId: 16,
      verdict: "abandoned",
      comment: "too ambitious for v1",
    });
  });

  it("resolves the card: drops buttons + comment box, shows the colored verdict label", () => {
    const { window, doc } = bootWebview();
    dispatch(window, { type: "exitPlanRequest", req: { id: 14, plan: "p" } });

    const card = doc.querySelector(".card.plan")!;
    const buttons = [...card.querySelectorAll(".card-actions button")] as HTMLButtonElement[];
    const rejectBtn = buttons.find((b) => b.textContent === "Reject")!;
    click(window, rejectBtn);

    expect(card.classList.contains("resolved")).toBe(true);
    // Collapses to the same clean representation as a restored history card:
    // buttons + comment box removed, a single colored verdict label remains.
    expect(card.querySelector(".card-actions")).toBeNull();
    expect(card.querySelector("textarea.plan-feedback")).toBeNull();
    const label = card.querySelector(".plan-verdict-label")!;
    expect(label.textContent).toBe("Rejected");
    expect(label.classList.contains("plan-verdict-rejected")).toBe(true);
  });

  it("renders a read-only plan-history card: file link + verdict, no inline plan text", () => {
    const { window, doc } = bootWebview();
    dispatch(window, {
      type: "planHistory",
      text: "# Restored plan\n- step 1",
      verdict: "rejected",
      planPath: "/tmp/grok/restored-plan.md",
      planName: "restored-plan.md",
    });

    const cards = doc.querySelectorAll(".card.plan.plan-history");
    expect(cards).toHaveLength(1);
    const card = cards[0];
    // The plan-file link IS the plan — no inline body / toggle when it exists.
    expect(card.querySelector(".plan-body")).toBeNull();
    expect(card.querySelector(".plan-toggle")).toBeNull();
    expect(card.querySelector(".plan-file-link code")!.textContent).toBe("restored-plan.md");
    expect(card.querySelector(".plan-verdict-label")!.textContent).toBe("Rejected");
    expect(card.querySelector(".card-actions")).toBeNull();
    expect(card.querySelector("textarea")).toBeNull();
  });

  it("opens a restored plan link", () => {
    const { window, posted, doc } = bootWebview();
    dispatch(window, {
      type: "planHistory",
      text: "# Restored plan\n- step 1",
      verdict: "approved",
      planPath: "/tmp/grok/restored-plan.md",
      planName: "restored-plan.md",
    });

    const link = doc.querySelector(".card.plan.plan-history .plan-file-link") as HTMLAnchorElement;
    click(window, link);

    expect(posted).toEqual([{ type: "openFile", path: "/tmp/grok/restored-plan.md" }]);
  });

  it("renders a plan-notice for planNotice and the blocked-command/-write variants", () => {
    const { window, doc } = bootWebview();
    dispatch(window, { type: "planNotice", text: "Staying in Plan mode — nothing was written." });
    dispatch(window, { type: "planBlocked", kind: "terminal", target: "npm install" });
    dispatch(window, { type: "planBlocked", kind: "write", target: "src/app.ts" });

    const notices = [...doc.querySelectorAll(".plan-notice")].map((n) => n.textContent);
    expect(notices).toHaveLength(3);
    expect(notices[0]).toContain("Staying in Plan mode");
    expect(notices[1]).toContain("Plan mode blocked a command: npm install");
    expect(notices[2]).toContain("Plan mode blocked a write to src/app.ts");
  });
});
