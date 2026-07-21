// DOM tests for #41 — full command text + captured output on command rows,
// driving the REAL media/chat.js. The host snapshots each terminal's buffer at
// terminal/release (the extension runs the commands itself, so the output is
// exactly what grok received) and posts it as `commandOutput`; the webview
// renders a Claude-Code-style IN/OUT block under the row, collapsed by default
// with the tool-group header's chevron affordance. Outputs attach by
// exact-command FIFO, with a standalone fallback row so output is never
// dropped. Success is silent (exit 0 = just the output); failure gets an
// [Error] marker + error tint; a kill is [Cancelled], not an error.
import { describe, it, expect } from "vitest";
import { bootWebview, dispatch, click } from "./webview-harness";

const exec = (id: string, command: string, title?: string) => ({
  type: "toolCall",
  call: {
    toolCallId: id,
    kind: "execute",
    title: title ?? `Run ${command.slice(0, 20)}…`,
    rawInput: { variant: "Bash", command, is_background: false },
  },
});
const out = (command: string, output: string, exitCode: number | null = 0, truncated = false) => ({
  type: "commandOutput",
  command,
  output,
  exitCode,
  truncated,
});
const read = (id: string, path: string) => ({
  type: "toolCall",
  call: { toolCallId: id, kind: "read", title: `Read ${path}`, rawInput: { path } },
});
const close = (window: Window) => dispatch(window, { type: "messageChunk", text: "done" });

describe("command details (#41)", () => {
  it("a lone command flattens WITH its trailing chevron + expandable IN/OUT block", () => {
    const { window, doc } = bootWebview();
    const longCmd = "node -e \"const fs=require('fs');const paths=fs.readdirSync('.').filter(p=>p.endsWith('.md'));console.log(paths.join('\\n'))\"";
    dispatch(window, exec("t1", longCmd, "Run node -e \"const fs=require('fs');const pa…"));
    close(window);

    const flat = doc.querySelector(".tool-flat.has-details") as HTMLElement;
    expect(flat).not.toBeNull();
    expect(flat.querySelector(".tool-chevron")).not.toBeNull(); // › after the label, moved with the flatten
    const details = flat.querySelector(".tool-item-details") as HTMLElement;
    expect(details.hidden).toBe(true); // collapsed by default
    expect(flat.classList.contains("expanded")).toBe(false);

    click(window, flat);
    expect(details.hidden).toBe(false);
    expect(flat.classList.contains("expanded")).toBe(true); // › rotated to v

    // The FULL command under an IN tag, not grok's truncated title.
    expect(details.querySelector(".cmd-io-tag")!.textContent).toBe("IN");
    expect(details.querySelector(".tool-cmd")!.textContent).toBe(longCmd);

    // Output lands after the flatten — the moved node still receives it.
    // Success is silent: OUT tag + text, no exit marker.
    dispatch(window, out(longCmd, "CLAUDE.md\nREADME.md", 0));
    const outRow = details.querySelector(".cmd-out") as HTMLElement;
    expect(outRow.querySelector(".cmd-io-tag")!.textContent).toBe("OUT");
    expect(outRow.querySelector(".tool-cmd-output")!.textContent).toBe("CLAUDE.md\nREADME.md");
    expect(outRow.classList.contains("failed")).toBe(false);
    expect(outRow.querySelector(".cmd-out-marker")).toBeNull();

    click(window, flat);
    expect(details.hidden).toBe(true);
    expect(flat.classList.contains("expanded")).toBe(false); // back to ›
  });

  it("grok.expandCommandOutputs pre-expands new rows and applies live to existing ones", () => {
    const { window, doc } = bootWebview();
    dispatch(window, {
      type: "initialState",
      effort: "", cwd: "/w", useCtrlEnter: false, extVersion: "0",
      showThinking: false, expandCommandOutputs: true,
    });
    dispatch(window, exec("a", "git status"));
    close(window);

    const flat = doc.querySelector(".tool-flat.has-details") as HTMLElement;
    const details = flat.querySelector(".tool-item-details") as HTMLElement;
    expect(details.hidden).toBe(false); // pre-expanded (v)
    expect(flat.classList.contains("expanded")).toBe(true);

    // Live config change collapses existing rows too.
    dispatch(window, { type: "expandCommandOutputs", value: false });
    expect(details.hidden).toBe(true);
    expect(flat.classList.contains("expanded")).toBe(false);

    dispatch(window, { type: "expandCommandOutputs", value: true });
    expect(details.hidden).toBe(false);
    expect(flat.classList.contains("expanded")).toBe(true);
  });

  it("outputs attach FIFO when the same command runs twice in one batch; exit 1 is [Error]", () => {
    const { window, doc } = bootWebview();
    dispatch(window, exec("a", "npm test"));
    dispatch(window, exec("b", "npm test"));
    close(window); // 2 calls → stays a group with .tool-item rows

    dispatch(window, out("npm test", "first run", 0));
    dispatch(window, out("npm test", "second run", 1));

    const items = [...doc.querySelectorAll(".tool-item.has-details")];
    expect(items).toHaveLength(2);
    // Labels in their own span (single-line ellipsis) + trailing chevron each.
    expect(items.every((i) => i.querySelector(".tool-item-label"))).toBe(true);
    expect(items.every((i) => i.querySelector(".tool-chevron"))).toBe(true);

    const details = [...doc.querySelectorAll(".tool-item .tool-item-details")];
    expect(details[0].querySelector(".tool-cmd-output")!.textContent).toBe("first run");
    expect(details[1].querySelector(".tool-cmd-output")!.textContent).toBe("second run");
    const failedRow = details[1].querySelector(".cmd-out") as HTMLElement;
    expect(failedRow.classList.contains("failed")).toBe(true);
    expect(failedRow.querySelector(".cmd-out-marker")!.textContent).toBe("[Error] exit 1");
  });

  it("an output with no matching row gets a standalone fallback row (never dropped)", () => {
    const { window, doc } = bootWebview();
    dispatch(window, out("echo orphan", "orphan output", 0));

    const details = doc.querySelector(".tool-item-details") as HTMLElement;
    expect(details).not.toBeNull();
    expect(details.querySelector(".tool-cmd")!.textContent).toBe("echo orphan");
    expect(details.querySelector(".tool-cmd-output")!.textContent).toBe("orphan output");
  });

  // The cursor/Composer agent runs commands in its OWN CLI-side shell (no
  // terminal/create), so `commandOutput` never fires for it — its output rides
  // the completed tool_call_update (rawOutput/content), keyed by toolCallId. The
  // #41 box must render it from there, or the row shows IN with no OUT (the bug).
  const completed = (id: string, output: string, exitCode = 0) => ({
    type: "toolCallUpdate",
    call: {
      toolCallId: id,
      status: "completed",
      rawOutput: { type: "Bash", output: [...Buffer.from(output, "utf8")], exit_code: exitCode, command: "x", truncated: false },
      content: [{ type: "content", content: { type: "text", text: output } }],
    },
  });

  it("fills a self-executed (Composer) command's OUT from the completed update, no terminal/create", () => {
    const { window, doc } = bootWebview();
    dispatch(window, exec("c1", "git status --short"));
    close(window);
    // No commandOutput ever arrives (Composer never delegates). The completed
    // update carries the result instead.
    dispatch(window, completed("c1", " M CHANGELOG.md", 0));

    const rows = [...doc.querySelectorAll(".has-details")];
    expect(rows).toHaveLength(1); // no duplicate/standalone row
    expect(doc.querySelector(".tool-cmd-output")!.textContent).toBe(" M CHANGELOG.md");
    expect(doc.querySelector(".tool-cmd")!.textContent).toBe("git status --short"); // IN unchanged
  });

  it("attaches self-executed outputs by toolCallId regardless of completion order (Composer runs parallel)", () => {
    const { window, doc } = bootWebview();
    dispatch(window, exec("a", "git status --short"));
    dispatch(window, exec("b", "$env:USERNAME"));
    close(window); // 2 calls → stays a group with rows
    // Completions arrive OUT of issue order (b before a) — FIFO would swap them.
    dispatch(window, completed("b", "Dell", 0));
    dispatch(window, completed("a", "STATUS_OUT", 0));

    const items = [...doc.querySelectorAll(".tool-item.has-details")];
    expect(items).toHaveLength(2); // no duplicate rows
    const outFor = (id: string) =>
      (items.find((i) => i.querySelector(".tool-cmd")!.textContent ===
        (id === "a" ? "git status --short" : "$env:USERNAME"))!
        .querySelector(".tool-cmd-output") as HTMLElement).textContent;
    expect(outFor("a")).toBe("STATUS_OUT"); // each output on its OWN row, by id
    expect(outFor("b")).toBe("Dell");
  });

  it("a non-zero self-executed command shows [Error] exit N in its OUT box", () => {
    const { window, doc } = bootWebview();
    dispatch(window, exec("e", "(cd x ; git status)"));
    close(window);
    dispatch(window, completed("e", "Missing closing ')' in expression.", 1));

    const outRow = doc.querySelector(".cmd-out") as HTMLElement;
    expect(outRow.classList.contains("failed")).toBe(true);
    expect(outRow.querySelector(".cmd-out-marker")!.textContent).toBe("[Error] exit 1");
    expect(outRow.querySelector(".tool-cmd-output")!.textContent).toContain("Missing closing");
  });

  it("killed commands read [Cancelled] (muted, not an error); truncation is noted", () => {
    const { window, doc } = bootWebview();
    dispatch(window, exec("k", "sleep 999"));
    close(window);
    dispatch(window, out("sleep 999", "partial", null, true));

    const outRow = doc.querySelector(".cmd-out") as HTMLElement;
    expect(outRow.classList.contains("failed")).toBe(false);
    const markers = [...outRow.querySelectorAll(".cmd-out-marker")];
    expect(markers[0].textContent).toBe("[Cancelled] no exit code");
    expect(markers[0].classList.contains("muted")).toBe(true);
    expect(markers[1].textContent).toContain("output truncated");
  });

  it("an exit-0 command with no output shows a done marker, not an empty (no output) pre", () => {
    const { window, doc } = bootWebview();
    dispatch(window, exec("q", "touch newfile"));
    close(window);
    dispatch(window, out("touch newfile", "", 0)); // success, nothing on stdout

    const outRow = doc.querySelector(".cmd-out") as HTMLElement;
    expect(outRow.classList.contains("failed")).toBe(false);
    const marker = outRow.querySelector(".cmd-out-marker") as HTMLElement;
    expect(marker.classList.contains("ok")).toBe(true);
    expect(marker.textContent).toContain("no output");
    expect(outRow.querySelector(".tool-cmd-output")).toBeNull(); // no empty <pre>
  });

  it("whitespace-only output is treated as empty (no lingering pre)", () => {
    const { window, doc } = bootWebview();
    dispatch(window, exec("w", "echo"));
    close(window);
    dispatch(window, out("echo", "\n  \n", 0));

    const outRow = doc.querySelector(".cmd-out") as HTMLElement;
    expect(outRow.querySelector(".cmd-out-marker.ok")).not.toBeNull();
    expect(outRow.querySelector(".tool-cmd-output")).toBeNull();
  });

  it("a non-zero exit with no output shows only [Error], no (no output) filler", () => {
    const { window, doc } = bootWebview();
    dispatch(window, exec("f", "false"));
    close(window);
    dispatch(window, out("false", "", 1));

    const outRow = doc.querySelector(".cmd-out") as HTMLElement;
    expect(outRow.classList.contains("failed")).toBe(true);
    expect(outRow.querySelector(".cmd-out-marker")!.textContent).toBe("[Error] exit 1");
    expect(outRow.querySelector(".tool-cmd-output")).toBeNull();
  });

  it("clicking inside the expanded block (text selection) does not collapse it", () => {
    const { window, doc } = bootWebview();
    dispatch(window, exec("s", "git status"));
    close(window);
    const flat = doc.querySelector(".tool-flat.has-details") as HTMLElement;
    click(window, flat);
    const details = flat.querySelector(".tool-item-details") as HTMLElement;
    expect(details.hidden).toBe(false);

    click(window, details.querySelector(".tool-cmd")!);
    expect(details.hidden).toBe(false); // still open
  });

  it("row chevrons are independent of the group's state (present mid-run, per-row rotation)", () => {
    const { window, doc } = bootWebview();
    dispatch(window, exec("a", "npm test"));
    dispatch(window, exec("b", "git status"));
    // Group still IN PROGRESS — expand it and inspect the rows.
    const group = doc.querySelector(".tool-group.in-progress") as HTMLElement;
    click(window, group.querySelector(".tool-group-header")!);

    const rows = [...group.querySelectorAll(".tool-item.has-details")] as HTMLElement[];
    expect(rows).toHaveLength(2);
    expect(rows.every((r) => r.querySelector(".tool-chevron"))).toBe(true); // chevrons exist mid-run
    expect(rows.every((r) => !r.classList.contains("expanded"))).toBe(true); // each starts ›

    click(window, rows[0]);
    expect(rows[0].classList.contains("expanded")).toBe(true); // v — this row only
    expect(rows[1].classList.contains("expanded")).toBe(false); // still ›
  });

  it("a lone RUNNING command is expandable immediately (no waiting for the batch to close)", () => {
    const { window, doc } = bootWebview();
    dispatch(window, exec("live", "npm run build"));
    // No close(): the batch is still in progress.
    const group = doc.querySelector(".tool-group.in-progress") as HTMLElement;
    expect(group.classList.contains("cmd-single")).toBe(true);

    // One click on the header reveals the row AND its IN detail.
    click(window, group.querySelector(".tool-group-header")!);
    const details = group.querySelector(".tool-item-details") as HTMLElement;
    expect(details.hidden).toBe(false);
    expect(details.querySelector(".tool-cmd")!.textContent).toBe("npm run build");

    // A second tool joining the batch demotes it to normal group behavior.
    dispatch(window, exec("live2", "git status"));
    expect(group.classList.contains("cmd-single")).toBe(false);
  });

  it("non-command tools get no details block and no clickable-highlight class", () => {
    const { window, doc } = bootWebview();
    dispatch(window, { type: "toolCall", call: { toolCallId: "r", kind: "read", rawInput: { path: "/a.ts" } } });
    close(window);
    expect(doc.querySelector(".tool-item-details")).toBeNull();
    expect(doc.querySelector(".has-details")).toBeNull();
  });

  it("the output poller and kill tools stay plain (no details, no highlight)", () => {
    const { window, doc } = bootWebview();
    dispatch(window, {
      type: "toolCall",
      call: { toolCallId: "p1", title: "Get task output: t1", rawInput: { variant: "TaskOutput", task_id: "t1", block: true } },
    });
    dispatch(window, {
      type: "toolCall",
      call: { toolCallId: "p2", title: "kill_command_or_subagent", rawInput: { task_id: "t1" } },
    });
    close(window);
    expect(doc.querySelector(".has-details")).toBeNull();
    expect(doc.querySelector(".tool-item-details")).toBeNull();
  });
});

// #41 (1.5.10): with the audit toggle on, a command-bearing tool GROUP opens
// itself so a "Ran N commands ›" batch needs zero extra clicks. Explore/edit-only
// groups (no command detail) stay collapsed.
describe("group auto-expand under grok.expandCommandOutputs", () => {
  const bootExpanded = () => {
    const h = bootWebview();
    dispatch(h.window, {
      type: "initialState",
      effort: "", cwd: "/w", useCtrlEnter: false, extVersion: "0",
      showThinking: false, expandCommandOutputs: true,
    });
    return h;
  };

  it("a finished command-bearing group paints open; an explore-only group stays collapsed", () => {
    const { window, doc } = bootExpanded();

    // Batch 1: a command + a read → kept as a group, has a command detail row.
    dispatch(window, exec("c1", "git status"));
    dispatch(window, read("r1", "src/a.ts"));
    close(window);

    // Batch 2: two reads → kept as a group, NO command detail.
    dispatch(window, read("r2", "src/b.ts"));
    dispatch(window, read("r3", "src/c.ts"));
    close(window);

    const groups = [...doc.querySelectorAll(".tool-group")] as HTMLElement[];
    expect(groups).toHaveLength(2);
    const cmdGroup = groups.find((g) => g.querySelector(".has-details"))!;
    const readGroup = groups.find((g) => !g.querySelector(".has-details"))!;

    expect((cmdGroup.querySelector(".tool-group-body") as HTMLElement).hidden).toBe(false);
    expect(cmdGroup.classList.contains("expanded")).toBe(true);
    expect((readGroup.querySelector(".tool-group-body") as HTMLElement).hidden).toBe(true);
    expect(readGroup.classList.contains("expanded")).toBe(false);
  });

  it("toggling the setting live expands/collapses existing command-bearing groups only", () => {
    const { window, doc } = bootWebview(); // setting OFF by default

    dispatch(window, exec("c1", "git status"));
    dispatch(window, read("r1", "src/a.ts"));
    close(window);
    dispatch(window, read("r2", "src/b.ts"));
    dispatch(window, read("r3", "src/c.ts"));
    close(window);

    const groups = [...doc.querySelectorAll(".tool-group")] as HTMLElement[];
    const cmdBody = groups.find((g) => g.querySelector(".has-details"))!.querySelector(".tool-group-body") as HTMLElement;
    const readBody = groups.find((g) => !g.querySelector(".has-details"))!.querySelector(".tool-group-body") as HTMLElement;
    expect(cmdBody.hidden).toBe(true); // both collapsed while OFF

    dispatch(window, { type: "expandCommandOutputs", value: true });
    expect(cmdBody.hidden).toBe(false); // command group opened
    expect(readBody.hidden).toBe(true); // explore-only untouched

    dispatch(window, { type: "expandCommandOutputs", value: false });
    expect(cmdBody.hidden).toBe(true); // collapses back
  });
});

// 1.5.10: Command Palette "Grok: Expand/Collapse All Tool Details (This Session)"
// — a per-session, in-memory LATCH. It opens/closes EVERY group (even
// explore-only) and every command box, and keeps applying to content that
// streams in afterward, until the opposite command or a gear-setting change
// (last action wins). It never persists to the host.
const bodies = (doc: Document) => [...doc.querySelectorAll(".tool-group-body")] as HTMLElement[];
const details = (doc: Document) => [...doc.querySelectorAll(".tool-item-details")] as HTMLElement[];

describe("setAllToolDetails (expand/collapse all latch)", () => {
  it("opens every group and command box, then collapses them all", () => {
    const { window, doc } = bootWebview();

    dispatch(window, exec("c1", "git status"));
    dispatch(window, read("r1", "src/a.ts"));
    close(window);
    dispatch(window, read("r2", "src/b.ts"));
    dispatch(window, read("r3", "src/c.ts"));
    close(window);
    dispatch(window, exec("solo", "npm test")); // lone command → flat row with details
    close(window);

    expect(bodies(doc).every((b) => b.hidden)).toBe(true); // all collapsed initially

    dispatch(window, { type: "setAllToolDetails", open: true });
    expect(bodies(doc).every((b) => !b.hidden)).toBe(true); // every group open (incl. explore-only)
    expect(details(doc).every((d) => !d.hidden)).toBe(true); // every IN/OUT box open

    dispatch(window, { type: "setAllToolDetails", open: false });
    expect(bodies(doc).every((b) => b.hidden)).toBe(true);
    expect(details(doc).every((d) => d.hidden)).toBe(true);
  });

  it("opens a group that is STILL EXECUTING (the reported gap)", () => {
    const { window, doc } = bootWebview();
    dispatch(window, exec("a", "npm test"));
    dispatch(window, exec("b", "git status")); // 2 tools, no close → group in-progress
    const group = doc.querySelector(".tool-group.in-progress") as HTMLElement;
    expect((group.querySelector(".tool-group-body") as HTMLElement).hidden).toBe(true);

    dispatch(window, { type: "setAllToolDetails", open: true });
    expect((group.querySelector(".tool-group-body") as HTMLElement).hidden).toBe(false);
    expect(group.classList.contains("expanded")).toBe(true); // chevron shown via CSS while running
  });

  it("keeps applying to tool calls that arrive AFTER the command (the second reported gap)", () => {
    const { window, doc } = bootWebview();
    dispatch(window, { type: "setAllToolDetails", open: true }); // latch on, transcript empty

    // A group + a lone command that appear later both render open.
    dispatch(window, exec("c1", "git status"));
    dispatch(window, read("r1", "src/a.ts"));
    close(window);
    dispatch(window, exec("solo", "npm test"));
    close(window);
    expect(bodies(doc).every((b) => !b.hidden)).toBe(true);
    expect(details(doc).every((d) => !d.hidden)).toBe(true);

    // Flip to collapse-all; subsequent content renders collapsed.
    dispatch(window, { type: "setAllToolDetails", open: false });
    dispatch(window, read("r2", "src/b.ts"));
    dispatch(window, read("r3", "src/c.ts"));
    close(window);
    expect(bodies(doc).every((b) => b.hidden)).toBe(true);
    expect(details(doc).every((d) => d.hidden)).toBe(true);
  });

  it("last action wins: flipping the gear setting clears the latch", () => {
    const { window, doc } = bootWebview();
    dispatch(window, exec("c1", "git status"));
    dispatch(window, read("r1", "src/a.ts"));
    close(window);
    dispatch(window, read("r2", "src/b.ts")); // explore-only group
    dispatch(window, read("r3", "src/c.ts"));
    close(window);

    dispatch(window, { type: "setAllToolDetails", open: false }); // force-collapse everything
    const cmdBody = bodies(doc).find((b) => b.closest(".tool-group")!.querySelector(".has-details"))!;
    const readBody = bodies(doc).find((b) => !b.closest(".tool-group")!.querySelector(".has-details"))!;
    expect(cmdBody.hidden).toBe(true);

    // Turning the setting ON clears the latch → command group opens, explore-only stays closed.
    dispatch(window, { type: "expandCommandOutputs", value: true });
    expect(cmdBody.hidden).toBe(false); // setting now governs (command-bearing only)
    expect(readBody.hidden).toBe(true);
  });

  it("collapse-all overrides the persisted setting (setting on, then collapse)", () => {
    const { window, doc } = bootWebview();
    dispatch(window, {
      type: "initialState",
      effort: "", cwd: "/w", useCtrlEnter: false, extVersion: "0",
      showThinking: false, expandCommandOutputs: true,
    });
    dispatch(window, exec("c1", "git status"));
    dispatch(window, read("r1", "src/a.ts"));
    close(window); // command group auto-opens under the setting
    const cmdBody = bodies(doc)[0];
    expect(cmdBody.hidden).toBe(false);

    dispatch(window, { type: "setAllToolDetails", open: false }); // latch beats the setting
    expect(cmdBody.hidden).toBe(true);
  });

  it("does not persist — no setExpandCommandOutputs round-trips to the host", () => {
    const { window, posted } = bootWebview();
    dispatch(window, exec("solo", "git status"));
    close(window);
    dispatch(window, { type: "setAllToolDetails", open: true });
    expect(posted.filter((m: any) => m.type === "setExpandCommandOutputs")).toHaveLength(0);
  });

  it("resets on a session swap (clearMessages) — new content follows the gear default again", () => {
    const { window, doc } = bootWebview();
    dispatch(window, { type: "setAllToolDetails", open: true }); // latch on
    dispatch(window, { type: "clearMessages" }); // focus-swap / new session

    dispatch(window, read("r1", "src/a.ts"));
    dispatch(window, read("r2", "src/b.ts"));
    close(window);
    // Explore-only group, latch cleared, setting off → collapsed.
    expect(bodies(doc)[0].hidden).toBe(true);
  });
});
