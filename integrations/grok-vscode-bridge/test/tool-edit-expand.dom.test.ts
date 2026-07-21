// DOM-level tests for edit review surfaces, driving the REAL shipped
// media/chat.js in a happy-dom window.
//
// #30: a permission that resolves to a *single* edit must stay expandable so its
// diff remains reviewable, both live and after a session restore. closeToolGroup
// must NOT flatten a lone edit into a `.tool-flat` (which would drop the diff
// attached to the tool-item in the body).
//
// #45: under Auto accept (no permission card), an edit still has to be reviewable
// in chat. Every edit row shows an always-visible `+A −R` count (rolled up onto
// the collapsed group header too) and an expandable inline diff — computed from
// the region grok sends (oldText/newText) — sharing the command IN/OUT expand
// machinery. The native "open diff →" link stays.
import { describe, it, expect } from "vitest";
import { bootWebview, dispatch, click } from "./webview-harness";

const DIFF = { type: "diff", path: "src/foo.ts", oldText: "a\nb", newText: "a\nB\nc" };
const EDIT_CALL = { toolCallId: "tc1", kind: "edit", title: "Edit src/foo.ts" };
// "a\nb" -> "a\nB\nc": 'a' context, 'b' removed, 'B'+'c' added → +2 −1.

describe("single-edit tool group stays expandable + reviewable (#30, #45)", () => {
  it("keeps a lone edit as an expandable group with its inline diff, not a flat row (live)", () => {
    const { window, posted, doc } = bootWebview();

    dispatch(window, { type: "toolCall", call: EDIT_CALL });
    dispatch(window, { type: "toolCallUpdate", call: { toolCallId: "tc1", content: [DIFF] } });
    dispatch(window, { type: "promptComplete", meta: {} }); // turn boundary → closeToolGroup

    const group = doc.querySelector(".tool-group");
    expect(group).not.toBeNull(); // NOT collapsed into a bare `.tool-flat`
    expect(doc.querySelector(".tool-flat")).toBeNull();

    const item = group!.querySelector(".tool-item") as HTMLElement;
    expect(item.classList.contains("has-details")).toBe(true); // rides the command detail machinery
    expect(item.querySelector(".tool-chevron")).not.toBeNull();

    // Always-visible +A −R on the row.
    expect(item.querySelector(".diff-stat-add")!.textContent).toBe("+2");
    expect(item.querySelector(".diff-stat-del")!.textContent).toBe("−1");

    // Rolled up onto the (collapsed) group header: "Edited 1 file · +2 −1".
    const header = group!.querySelector(".tool-group-label")!;
    expect(header.textContent).toContain("Edited 1 file");
    expect(header.querySelector(".diff-stat-add")!.textContent).toBe("+2");

    // The inline diff itself (Codex-style gutter rows) lives in the row's detail.
    const diffBlock = item.querySelector(".tool-item-details .tool-diff-region") as HTMLElement;
    expect(diffBlock).not.toBeNull();
    const adds = [...diffBlock.querySelectorAll(".tdl-add .tdl-code")].map((s) => s.textContent);
    const dels = [...diffBlock.querySelectorAll(".tdl-del .tdl-code")].map((s) => s.textContent);
    expect(adds).toEqual(["B", "c"]);
    expect(dels).toEqual(["b"]);
    // Color-blind affordance: +/- glyph by the border; region-relative line numbers.
    expect([...diffBlock.querySelectorAll(".tdl-add .tdl-sign")].map((s) => s.textContent)).toEqual(["+", "+"]);
    expect(diffBlock.querySelector(".tdl-del .tdl-sign")!.textContent).toBe("-");
    expect([...diffBlock.querySelectorAll(".tdl .tdl-num")].map((s) => s.textContent)).toEqual(["1", "2", "2", "3"]);

    // "open diff →" still opens the native editor with the region.
    const link = group!.querySelector(".tool-group-body .preview-link") as HTMLButtonElement;
    expect(link.textContent).toContain("open diff");
    click(window, link);
    const openDiffs = posted.filter((m: any) => m.type === "openDiff");
    expect(openDiffs).toHaveLength(1);
    expect(openDiffs[0]).toMatchObject({ path: "src/foo.ts", oldText: "a\nb", newText: "a\nB\nc" });
  });

  it("collapsed by default; expanding the group then the row reveals the diff", () => {
    const { window, doc } = bootWebview();

    dispatch(window, { type: "toolCall", call: EDIT_CALL });
    dispatch(window, { type: "toolCallUpdate", call: { toolCallId: "tc1", content: [DIFF] } });
    dispatch(window, { type: "promptComplete", meta: {} });

    const group = doc.querySelector(".tool-group") as HTMLElement;
    const body = group.querySelector(".tool-group-body") as HTMLElement;
    const item = group.querySelector(".tool-item") as HTMLElement;
    const details = item.querySelector(".tool-item-details") as HTMLElement;
    expect(body.hidden).toBe(true); // group collapsed by default (setting off)
    expect(details.hidden).toBe(true); // diff collapsed by default

    click(window, group.querySelector(".tool-group-header")!);
    expect(body.hidden).toBe(false);

    click(window, item); // expand the row
    expect(details.hidden).toBe(false);
    expect(item.classList.contains("expanded")).toBe(true);

    click(window, item); // collapse again
    expect(details.hidden).toBe(true);
  });

  it("clicking 'open diff →' inside the detail does not toggle the row", () => {
    const { window, doc, posted } = bootWebview();
    dispatch(window, { type: "toolCall", call: EDIT_CALL });
    dispatch(window, { type: "toolCallUpdate", call: { toolCallId: "tc1", content: [DIFF] } });
    dispatch(window, { type: "promptComplete", meta: {} });

    const item = doc.querySelector(".tool-item") as HTMLElement;
    const details = item.querySelector(".tool-item-details") as HTMLElement;
    click(window, item); // open the row
    expect(details.hidden).toBe(false);
    click(window, details.querySelector(".preview-link")!);
    expect(details.hidden).toBe(false); // still open — the button doesn't collapse the row
    expect(posted.filter((m: any) => m.type === "openDiff")).toHaveLength(1);
  });

  it("does not double-render the diff when the same update replays (idempotent)", () => {
    const { window, doc } = bootWebview();
    dispatch(window, { type: "toolCall", call: EDIT_CALL });
    dispatch(window, { type: "toolCallUpdate", call: { toolCallId: "tc1", content: [DIFF] } });
    dispatch(window, { type: "toolCallUpdate", call: { toolCallId: "tc1", content: [DIFF] } }); // replay
    dispatch(window, { type: "promptComplete", meta: {} });

    const item = doc.querySelector(".tool-item") as HTMLElement;
    expect(item.querySelectorAll(".tool-item-details")).toHaveLength(1);
    expect(item.querySelectorAll(".diff-stat")).toHaveLength(1);
  });

  it("a new file (empty oldText) reads as pure additions, no phantom removal", () => {
    const { window, doc } = bootWebview();
    dispatch(window, { type: "toolCall", call: { toolCallId: "n1", kind: "edit", title: "Edit new.ts" } });
    dispatch(window, {
      type: "toolCallUpdate",
      call: { toolCallId: "n1", content: [{ type: "diff", path: "new.ts", oldText: "", newText: "x\ny" }] },
    });
    dispatch(window, { type: "promptComplete", meta: {} });

    const item = doc.querySelector(".tool-item") as HTMLElement;
    expect(item.querySelector(".diff-stat-add")!.textContent).toBe("+2");
    expect(item.querySelector(".diff-stat-del")!.textContent).toBe("−0");
  });

  it("pre-expands the diff when grok.expandCommandOutputs (Expand tool details) is on", () => {
    const { window, doc } = bootWebview();
    dispatch(window, {
      type: "initialState",
      effort: "", cwd: "/w", useCtrlEnter: false, extVersion: "0",
      showThinking: false, expandCommandOutputs: true,
    });
    dispatch(window, { type: "toolCall", call: EDIT_CALL });
    dispatch(window, { type: "toolCallUpdate", call: { toolCallId: "tc1", content: [DIFF] } });
    dispatch(window, { type: "promptComplete", meta: {} });

    const group = doc.querySelector(".tool-group") as HTMLElement;
    // The edit group is has-details, so the setting auto-opens the group AND the diff.
    expect((group.querySelector(".tool-group-body") as HTMLElement).hidden).toBe(false);
    expect((group.querySelector(".tool-item-details") as HTMLElement).hidden).toBe(false);
  });

  it("still flattens a lone non-edit (a read) into a `.tool-flat`", () => {
    const { window, doc } = bootWebview();
    dispatch(window, { type: "toolCall", call: { toolCallId: "r1", kind: "read", title: "Read src/foo.ts" } });
    dispatch(window, { type: "promptComplete", meta: {} });

    expect(doc.querySelector(".tool-flat")).not.toBeNull();
    expect(doc.querySelector(".tool-group")).toBeNull();
  });

  it("survives restore: a completed edit that carries its own diff still shows the inline diff + open diff", () => {
    const { window, posted, doc } = bootWebview();

    // grok's REAL session/load wire: a completed edit replays as a SINGLE
    // `tool_call` — kind:"edit", status:"completed" — carrying the diff in its own
    // `content`, with NO follow-up `tool_call_update`. So diff extraction must run
    // on the `tool_call` itself (#30).
    const REPLAYED_EDIT = { ...EDIT_CALL, status: "completed", content: [DIFF] };

    dispatch(window, { type: "historyReplay", active: true });
    dispatch(window, {
      type: "permissionHistoryQueue",
      permissions: [{ toolCallId: "tc1", title: "Edit src/foo.ts", outcome: "allowed" }],
    });
    dispatch(window, { type: "toolCall", call: REPLAYED_EDIT }); // single message, diff included
    dispatch(window, { type: "historyReplay", active: false });

    const group = doc.querySelector(".tool-group");
    expect(group).not.toBeNull();
    expect(doc.querySelector(".tool-flat")).toBeNull();
    expect(group!.querySelector(".diff-stat-add")!.textContent).toBe("+2");
    expect(group!.querySelector(".tool-item-details .tool-diff-region")).not.toBeNull();

    const link = group!.querySelector(".tool-group-body .preview-link") as HTMLButtonElement;
    expect(link.textContent).toContain("open diff");
    click(window, link);
    const openDiffs = posted.filter((m: any) => m.type === "openDiff");
    expect(openDiffs).toHaveLength(1);
    expect(openDiffs[0]).toMatchObject({ path: "src/foo.ts", oldText: "a\nb", newText: "a\nB\nc" });

    // The answered permission card replays right at the tool it gated.
    expect(doc.querySelector(".card.permission.perm-resolved")).not.toBeNull();
  });

  it("rolls per-file totals up onto a multi-edit group header, de-duped by path", () => {
    const { window, doc } = bootWebview();
    // Two edits to the SAME file → "Edited 1 file", totals summed. grok's edit
    // tool_call carries the path in rawInput.file_path.
    dispatch(window, { type: "toolCall", call: { toolCallId: "e1", kind: "edit", title: "Edit a.ts", rawInput: { file_path: "a.ts" } } });
    dispatch(window, { type: "toolCallUpdate", call: { toolCallId: "e1", content: [{ type: "diff", path: "a.ts", oldText: "1", newText: "1\n2" }] } });
    dispatch(window, { type: "toolCall", call: { toolCallId: "e2", kind: "edit", title: "Edit a.ts", rawInput: { file_path: "a.ts" } } });
    dispatch(window, { type: "toolCallUpdate", call: { toolCallId: "e2", content: [{ type: "diff", path: "a.ts", oldText: "x", newText: "y" }] } });
    dispatch(window, { type: "promptComplete", meta: {} });

    const label = doc.querySelector(".tool-group-label")!;
    expect(label.textContent).toContain("Edited 1 file"); // de-duped, not "2 files"
    // Totals: e1 +1 −0, e2 +1 −1 → +2 −1.
    expect(label.querySelector(".diff-stat-add")!.textContent).toBe("+2");
    expect(label.querySelector(".diff-stat-del")!.textContent).toBe("−1");
  });
});
