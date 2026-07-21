// DOM-level regression tests for the webview UI bugs that the native-Windows
// smoke test surfaced and this build fixed (see CLAUDE.md § Status). Each one
// drives the REAL media/chat.js and asserts the fixed behavior, so the bug can't
// silently come back:
//
//   1. History popover that "never closed"  -> open/close toggle + outside-click close
//   2. Session rows "only clickable on the label" -> whole row resumes; action
//      buttons stopPropagation so they don't also resume
//   3. Reasoning traces "no longer expandable" -> header click toggles the body
import { describe, it, expect } from "vitest";
import { bootWebview, dispatch, click, Posted } from "./webview-harness";

const $ = (doc: Document, id: string) => doc.getElementById(id) as HTMLElement;
const types = (posted: Posted[]) => posted.map((p) => p.type);

describe("history popover (regression: popover that never closed)", () => {
  it("opens on the history button and requests the session list", () => {
    const { window, posted, doc } = bootWebview();
    const pop = $(doc, "history-popover");
    expect((pop as any).hidden).toBe(true);

    click(window, $(doc, "history-btn"));

    expect((pop as any).hidden).toBe(false);
    expect(types(posted)).toContain("listSessions");
  });

  it("toggles closed when the history button is clicked again", () => {
    const { window, doc } = bootWebview();
    const pop = $(doc, "history-popover");
    click(window, $(doc, "history-btn"));
    expect((pop as any).hidden).toBe(false);

    click(window, $(doc, "history-btn"));
    expect((pop as any).hidden).toBe(true);
  });

  it("closes on an outside click but stays open on a click inside it", () => {
    const { window, doc } = bootWebview();
    const pop = $(doc, "history-popover");

    click(window, $(doc, "history-btn"));
    expect((pop as any).hidden).toBe(false);

    // click inside the popover -> stopPropagation keeps it open
    click(window, pop);
    expect((pop as any).hidden).toBe(false);

    // click elsewhere in the document -> closePopovers()
    click(window, $(doc, "messages"));
    expect((pop as any).hidden).toBe(true);
  });

  it("right-anchors the popover so async row loading can't crop it off the right edge", () => {
    // Regression: the session rows stream in after the popover is positioned, widening it
    // from min-width toward max-width. The old left-anchor + one-shot width clamp measured
    // the width BEFORE those rows arrived, so the popover later spilled off the right edge
    // (and only looked right on reopen). Right-anchoring is width-independent.
    const { window, doc } = bootWebview();
    const pop = $(doc, "history-popover");
    const btn = $(doc, "history-btn");
    const parent = pop.parentElement as HTMLElement;
    (parent as any).getBoundingClientRect = () =>
      ({ left: 0, right: 400, top: 0, bottom: 600, width: 400, height: 600 });
    (btn as any).getBoundingClientRect = () =>
      ({ left: 360, right: 392, top: 8, bottom: 30, width: 32, height: 22 });

    click(window, btn);

    expect(pop.style.left).toBe("auto");
    expect(pop.style.right).toBe("6px"); // gap from the panel's right edge, not under the button
    expect(pop.style.top).toBe("34px"); // btnRect.bottom(30) - parentRect.top(0) + 4
    expect(pop.style.maxWidth).toBe("360px"); // wide panel: full max width
  });

  it("caps the popover width to a narrow panel so names ellipsize instead of overflowing left", () => {
    const { window, doc } = bootWebview();
    const pop = $(doc, "history-popover");
    const btn = $(doc, "history-btn");
    const parent = pop.parentElement as HTMLElement;
    // A 240px panel can't fit the 280px CSS min-width — without the inline cap the popover
    // would overflow the left edge. available = 240 - 6*2 = 228.
    (parent as any).getBoundingClientRect = () =>
      ({ left: 0, right: 240, top: 0, bottom: 600, width: 240, height: 600 });
    (btn as any).getBoundingClientRect = () =>
      ({ left: 200, right: 232, top: 8, bottom: 30, width: 32, height: 22 });

    click(window, btn);

    expect(pop.style.maxWidth).toBe("228px");
    expect(pop.style.minWidth).toBe("228px"); // min(280, 228) — shrinks below the CSS floor
    expect(pop.style.right).toBe("6px");
  });

  it("re-measures the open popover when the panel is resized (no close+reopen needed)", () => {
    const { window, doc } = bootWebview();
    const pop = $(doc, "history-popover");
    const btn = $(doc, "history-btn");
    const parent = pop.parentElement as HTMLElement;
    (btn as any).getBoundingClientRect = () =>
      ({ left: 360, right: 392, top: 8, bottom: 30, width: 32, height: 22 });
    (parent as any).getBoundingClientRect = () =>
      ({ left: 0, right: 400, top: 0, bottom: 600, width: 400, height: 600 });

    click(window, btn);
    expect(pop.style.maxWidth).toBe("360px");

    // Panel shrinks to 240px while the popover is still open -> it should re-fit live.
    (parent as any).getBoundingClientRect = () =>
      ({ left: 0, right: 240, top: 0, bottom: 600, width: 240, height: 600 });
    window.dispatchEvent(new (window as any).Event("resize"));

    expect(pop.style.maxWidth).toBe("228px"); // 240 - 6*2, re-measured without reopening
  });

  it("closes the popover when the view is hidden (switching to another extension/tab)", () => {
    const { window, doc } = bootWebview();
    const pop = $(doc, "history-popover");
    click(window, $(doc, "history-btn"));
    expect((pop as any).hidden).toBe(false);

    Object.defineProperty(doc, "hidden", { configurable: true, get: () => true });
    doc.dispatchEvent(new (window as any).Event("visibilitychange"));

    expect((pop as any).hidden).toBe(true);
  });
});

describe("session rows (regression: only the label was clickable)", () => {
  const entries = [
    { id: "s1", displayName: "Add subtract fn", numMessages: 4, updatedAt: Date.now() - 60000 },
    { id: "s2", displayName: "Refactor parser", numMessages: 9, updatedAt: Date.now() - 3600000 },
  ];

  function openWithSessions() {
    const h = bootWebview();
    click(h.window, $(h.doc, "history-btn")); // open the popover so the list renders
    h.posted.length = 0; // forget the listSessions request; keep only row interactions
    dispatch(h.window, { type: "sessions", entries, activeId: null });
    return h;
  }

  it("renders one row per session with name + meta", () => {
    const { doc } = openWithSessions();
    const rows = doc.querySelectorAll(".history-row");
    expect(rows).toHaveLength(2);
    expect(rows[0].querySelector(".history-row-name")!.textContent).toBe("Add subtract fn");
    expect(rows[0].querySelector(".history-row-meta")!.textContent).toContain("4 msg");
  });

  it("resumes the session when the row's META area (not the label) is clicked", () => {
    const { window, posted, doc } = openWithSessions();
    const meta = doc.querySelector(".history-row .history-row-meta") as HTMLElement;
    click(window, meta); // a non-label part of the row

    expect(posted).toContainEqual({ type: "resumeSession", id: "s1" });
  });

  it("delete button posts deleteSession and does NOT also resume (stopPropagation)", () => {
    const { window, posted, doc } = openWithSessions();
    const delBtn = doc.querySelector(".history-row .history-action-danger") as HTMLElement;
    click(window, delBtn);

    expect(posted).toContainEqual({ type: "deleteSession", id: "s1", name: "Add subtract fn" });
    expect(types(posted)).not.toContain("resumeSession");
  });

  it("hides the delete button for the active session, keeps it for others", () => {
    const h = bootWebview();
    click(h.window, $(h.doc, "history-btn"));
    h.posted.length = 0;
    dispatch(h.window, { type: "sessions", entries, activeId: "s1" });
    const rows = h.doc.querySelectorAll(".history-row");
    // s1 is active → no delete button (it's the live session; delete wouldn't stick).
    expect(rows[0].querySelector(".history-action-danger")).toBeNull();
    // s2 is not active → delete button present.
    expect(rows[1].querySelector(".history-action-danger")).not.toBeNull();
    // Rename stays available on the active row.
    expect(rows[0].querySelector(".history-action-btn")).not.toBeNull();
  });

  it("rename button enters rename mode and does NOT resume", () => {
    const { window, posted, doc } = openWithSessions();
    const renameBtn = doc.querySelectorAll(".history-row .history-action-btn")[0] as HTMLElement;
    click(window, renameBtn);

    expect(doc.querySelector(".history-row input.history-rename")).not.toBeNull();
    expect(types(posted)).not.toContain("resumeSession");
  });

  it("shows a Clear all footer that posts clearAllSessions and closes the popover", () => {
    const { window, posted, doc } = openWithSessions();
    const clearBtn = doc.querySelector(".history-clear-all") as HTMLElement;
    expect(clearBtn).not.toBeNull();
    click(window, clearBtn);

    expect(posted).toContainEqual({ type: "clearAllSessions" });
    expect(($(doc, "history-popover") as any).hidden).toBe(true);
  });

  it("hides the Clear all footer when the only session is the active one", () => {
    const h = bootWebview();
    click(h.window, $(h.doc, "history-btn"));
    dispatch(h.window, {
      type: "sessions",
      entries: [entries[0]],
      activeId: entries[0].id,
      total: 1,
    });
    expect((h.doc.querySelector(".history-footer") as any).hidden).toBe(true);
  });

  it("hides the Clear all footer when there are no sessions", () => {
    const h = bootWebview();
    click(h.window, $(h.doc, "history-btn"));
    dispatch(h.window, { type: "sessions", entries: [], activeId: null, total: 0 });
    expect((h.doc.querySelector(".history-footer") as any).hidden).toBe(true);
  });
});

describe("session history pagination", () => {
  const page1 = [
    { id: "p0", displayName: "Session 0", numMessages: 1, updatedAt: Date.now() - 1000 },
    { id: "p1", displayName: "Session 1", numMessages: 1, updatedAt: Date.now() - 2000 },
    { id: "p2", displayName: "Session 2", numMessages: 1, updatedAt: Date.now() - 3000 },
  ];
  const page2 = [
    { id: "q0", displayName: "Older 0", numMessages: 1, updatedAt: Date.now() - 10000 },
    { id: "q1", displayName: "Older 1", numMessages: 1, updatedAt: Date.now() - 11000 },
  ];

  function openPopover() {
    const h = bootWebview();
    click(h.window, $(h.doc, "history-btn"));
    h.posted.length = 0; // forget the initial listSessions request
    return h;
  }

  it("shows a 'more' indicator while later pages remain", () => {
    const h = openPopover();
    dispatch(h.window, { type: "sessions", entries: page1, activeId: null, offset: 0, total: 5, hasMore: true });
    expect(h.doc.querySelector(".history-more")).not.toBeNull();
    expect(h.doc.querySelectorAll(".history-row")).toHaveLength(3);
  });

  it("appends the next page on a load-more (offset > 0) response", () => {
    const h = openPopover();
    dispatch(h.window, { type: "sessions", entries: page1, activeId: null, offset: 0, total: 5, hasMore: true });
    dispatch(h.window, { type: "sessions", entries: page2, activeId: null, offset: 3, total: 5, hasMore: false });
    expect(h.doc.querySelectorAll(".history-row")).toHaveLength(5);
    // The indicator disappears once the final page has arrived.
    expect(h.doc.querySelector(".history-more")).toBeNull();
  });

  it("replaces (not appends) on a fresh offset-0 response", () => {
    const h = openPopover();
    dispatch(h.window, { type: "sessions", entries: page1, activeId: null, offset: 0, total: 5, hasMore: true });
    dispatch(h.window, { type: "sessions", entries: page2, activeId: null, offset: 0, total: 2, hasMore: false });
    const rows = h.doc.querySelectorAll(".history-row");
    expect(rows).toHaveLength(2);
    expect(rows[0].querySelector(".history-row-name")!.textContent).toBe("Older 0");
  });

  it("de-dupes when a load-more page overlaps the loaded list", () => {
    const h = openPopover();
    dispatch(h.window, { type: "sessions", entries: page1, activeId: null, offset: 0, total: 5, hasMore: true });
    const overlap = [{ ...page1[2] }, ...page2]; // p2 already loaded
    dispatch(h.window, { type: "sessions", entries: overlap, activeId: null, offset: 3, total: 5, hasMore: false });
    expect(h.doc.querySelectorAll(".history-row")).toHaveLength(5); // 3 + 2, the dup dropped
  });

  it("keeps the Clear all footer visible when later pages hold the only deletable sessions", () => {
    const h = openPopover();
    // Only the active session is loaded, but `total` says more exist on later pages.
    dispatch(h.window, {
      type: "sessions",
      entries: [{ id: "active", displayName: "Live", numMessages: 1, updatedAt: Date.now() }],
      activeId: "active",
      offset: 0,
      total: 40,
      hasMore: true,
    });
    expect((h.doc.querySelector(".history-footer") as any).hidden).toBe(false);
  });
});

describe("session status dots (Agent Dashboard)", () => {
  const entries = [
    { id: "s1", displayName: "Working one", numMessages: 4, updatedAt: Date.now() },
    { id: "s2", displayName: "Resting one", numMessages: 2, updatedAt: Date.now() },
    { id: "s3", displayName: "Unread one", numMessages: 1, updatedAt: Date.now() },
  ];

  function openWithDots(dots: Record<string, string>, activeId: string | null = null) {
    const h = bootWebview();
    click(h.window, $(h.doc, "history-btn"));
    h.posted.length = 0;
    dispatch(h.window, { type: "sessions", entries, activeId, dots });
    return h;
  }

  const dotOf = (doc: Document, id: string) =>
    doc.querySelector(`[data-session-dot="${id}"]`) as HTMLElement;

  it("colors each row's dot from the dots map; rows with no entry render gray (dot-none)", () => {
    const { doc } = openWithDots({ s1: "working", s2: "unread" });
    expect(dotOf(doc, "s1").className).toContain("dot-working");
    expect(dotOf(doc, "s2").className).toContain("dot-unread");
    // s3 is absent from the map → at rest → gray default.
    expect(dotOf(doc, "s3").className).toContain("dot-none");
  });

  it("renders each dot value with its class (working/needs-you/unread/error)", () => {
    const { doc } = openWithDots({ s1: "needs-you", s2: "unread", s3: "error" });
    expect(dotOf(doc, "s1").className).toContain("dot-needs-you");
    expect(dotOf(doc, "s2").className).toContain("dot-unread");
    expect(dotOf(doc, "s3").className).toContain("dot-error");
  });

  it("patches a single dot incrementally on a sessionDot message (no re-render)", () => {
    const { window, doc } = openWithDots({ s1: "working", s2: "unread" });
    const before = dotOf(doc, "s1");
    dispatch(window, { type: "sessionDot", id: "s1", dot: "needs-you" });
    // Same element, mutated in place — not a fresh row.
    expect(dotOf(doc, "s1")).toBe(before);
    expect(dotOf(doc, "s1").className).toContain("dot-needs-you");
    // The other dot is untouched.
    expect(dotOf(doc, "s2").className).toContain("dot-unread");
  });

  it("drops a dot to gray when sessionDot clears it to none (opened / reaped+read)", () => {
    const { window, doc } = openWithDots({ s1: "unread" });
    dispatch(window, { type: "sessionDot", id: "s1", dot: "none" });
    expect(dotOf(doc, "s1").className).toContain("dot-none");
  });

  it("keeps a green unread dot when the session is reaped but still unopened", () => {
    // disposeSession recomputes the dot; an unread reaped session stays green.
    const { window, doc } = openWithDots({ s1: "working" });
    dispatch(window, { type: "sessionDot", id: "s1", dot: "unread" });
    expect(dotOf(doc, "s1").className).toContain("dot-unread");
  });

  it("keeps the dot's tooltip in sync with its state", () => {
    const { doc } = openWithDots({ s1: "working" });
    expect(dotOf(doc, "s1").title).toBe("Working");
  });
});

describe("mode picker (the plan-gate entry path)", () => {
  it("offers Agent / Plan / Auto accept and posts setMode with the chosen mode id", () => {
    const { window, posted, doc } = bootWebview();
    const pop = $(doc, "mode-popover");

    click(window, $(doc, "mode-btn"));
    expect((pop as any).hidden).toBe(false);
    const labels = [...pop.querySelectorAll(".mode-item-label")].map((l) => l.textContent);
    expect(labels).toEqual(["Agent mode", "Plan mode", "Auto accept"]);

    const planItem = [...pop.querySelectorAll(".mode-popover-item")]
      .find((el) => el.querySelector(".mode-item-label")!.textContent === "Plan mode") as HTMLElement;
    click(window, planItem);

    expect(posted).toContainEqual({ type: "setMode", modeId: "plan" });
    expect((pop as any).hidden).toBe(true); // selecting a mode closes the popover
  });

  it("toggles the mode popover closed when the button is clicked again", () => {
    const { window, doc } = bootWebview();
    const pop = $(doc, "mode-popover");
    click(window, $(doc, "mode-btn"));
    expect((pop as any).hidden).toBe(false);
    click(window, $(doc, "mode-btn"));
    expect((pop as any).hidden).toBe(true);
  });

  // Regression: switching mode during session start called setMode before the
  // session existed → "Couldn't switch mode: no session". The button is now
  // disabled while busy (like send), and busy always clears so it can't get stuck.
  it("disables the mode button while starting/busy and won't open the picker or post setMode", () => {
    const { window, posted, doc } = bootWebview({ ready: false }); // startup: busy + locked
    const modeBtn = $(doc, "mode-btn") as HTMLButtonElement;
    expect(modeBtn.disabled).toBe(true);
    expect(modeBtn.className).toContain("disabled");

    click(window, modeBtn);
    expect(($(doc, "mode-popover") as any).hidden).toBe(true); // picker never opened
    expect(types(posted)).not.toContain("setMode");
  });

  it("enables the mode button once the session is ready", () => {
    const { window, doc } = bootWebview(); // ready → busy cleared
    const modeBtn = $(doc, "mode-btn") as HTMLButtonElement;
    expect(modeBtn.disabled).toBe(false);
    click(window, modeBtn);
    expect(($(doc, "mode-popover") as any).hidden).toBe(false); // opens normally
  });
});

describe("context donut (token usage)", () => {
  const boot = () => {
    const h = bootWebview();
    dispatch(h.window, {
      type: "session",
      sessionId: "s1",
      currentModelId: "grok-build",
      models: [{ modelId: "grok-build", name: "Grok Build", totalContextTokens: 100000 }],
    });
    return h;
  };

  it("updates on a real totalTokens; keeps the last value when the host stripped it", () => {
    const { window, doc } = boot();
    dispatch(window, { type: "promptComplete", meta: { totalTokens: 32000 } });
    expect($(doc, "donut-label").textContent).toBe("32K/100K");
    // gateZeroTokenMeta strips totalTokens:0 host-side (#39 — /session-info AND
    // /compact report 0, never a real measurement), so the webview only ever
    // sees a real number or nothing. Nothing = keep the last real value.
    dispatch(window, { type: "promptComplete", meta: { totalTokens: undefined } });
    dispatch(window, { type: "promptComplete", meta: {} });
    dispatch(window, { type: "promptComplete" });
    expect($(doc, "donut-label").textContent).toBe("32K/100K");
  });

  it("contextUsage (host-read signals.json) updates used and the window", () => {
    const { window, doc } = boot();
    dispatch(window, { type: "contextUsage", used: 29088, window: 200000 });
    expect($(doc, "donut-label").textContent).toBe("29K/200K");
  });

  it("contextUsage without a window keeps the model-derived window", () => {
    const { window, doc } = boot();
    dispatch(window, { type: "contextUsage", used: 29088 });
    expect($(doc, "donut-label").textContent).toBe("29K/100K");
  });

  it("seeds a cold restore: the session event zeroes the donut, contextUsage restores it", () => {
    // Cold-restore buffered order: `session` (resets the donut to 0) → replay →
    // `contextUsage` (the host reads signals.json after loadSession returns).
    const { window, doc } = boot();
    expect($(doc, "donut-label").textContent).toBe("0K/100K");
    dispatch(window, { type: "contextUsage", used: 44123, window: 100000 });
    expect($(doc, "donut-label").textContent).toBe("44K/100K");
  });

  it("a stripped zero keeps the donut, a later contextUsage corrects it", () => {
    const { window, doc } = boot();
    dispatch(window, { type: "promptComplete", meta: { totalTokens: 40088 } });
    // /compact reports a stripped zero; the CLI recomputes signals.json only
    // when the NEXT turn ends (research/signals-refresh-probe.cjs), so the
    // corrected count arrives via contextUsage after a follow-up zero turn
    // (e.g. /session-info) — compact shrinks context, it doesn't empty it.
    dispatch(window, { type: "promptComplete", meta: {} });
    dispatch(window, { type: "contextUsage", used: 29088 });
    expect($(doc, "donut-label").textContent).toBe("29K/100K");
  });
});

describe("gear settings lock (model + effort disabled while busy / priming)", () => {
  const models = [
    { modelId: "grok-build", name: "Grok Build" },
    { modelId: "grok-composer-2.5-fast", name: "Composer 2.5 Fast" },
  ];
  function bootWithModels(busy?: { value: boolean; locked?: boolean }) {
    const h = bootWebview();
    dispatch(h.window, { type: "session", sessionId: "s1", models, currentModelId: "grok-build" });
    if (busy) dispatch(h.window, { type: "setBusy", ...busy });
    h.posted.length = 0;
    return h;
  }
  const modelBtn = (doc: Document) => doc.querySelector(".model-name-btn") as HTMLButtonElement;

  it("shows the user-facing model name on the gear button, not the raw id", () => {
    const { window, doc } = bootWithModels();
    click(window, $(doc, "gear-btn"));
    expect(modelBtn(doc).textContent).toContain("Grok Build");
    expect(modelBtn(doc).textContent).not.toContain("grok-build");
  });

  it("when idle, the model button opens the picker and a pick posts setModel", () => {
    const { window, posted, doc } = bootWithModels();
    click(window, $(doc, "gear-btn"));
    expect(modelBtn(doc).disabled).toBe(false);

    click(window, modelBtn(doc)); // opens the picker sub-view
    const composer = [...doc.querySelectorAll("#gear-popover .toolbar-popover-item")]
      .find((el) => el.textContent!.includes("Composer 2.5 Fast")) as HTMLElement;
    click(window, composer);

    expect(posted).toContainEqual({ type: "setModel", modelId: "grok-composer-2.5-fast" });
  });

  it("while priming, the model button is disabled and clicking it neither opens the picker nor posts", () => {
    const { window, posted, doc } = bootWithModels({ value: true, locked: true });
    click(window, $(doc, "gear-btn"));

    expect(modelBtn(doc).disabled).toBe(true);
    expect(modelBtn(doc).className).toContain("disabled");

    click(window, modelBtn(doc));
    // still on the main gear view (the picker's "← Model" back row never rendered)
    expect(doc.querySelector("#gear-popover .popover-back")).toBeNull();
    expect(types(posted)).not.toContain("setModel");
  });

  it("while busy, clicking an effort dot does not post setEffort", () => {
    const { window, posted, doc } = bootWithModels({ value: true });
    click(window, $(doc, "gear-btn"));
    const dot = doc.querySelector(".effort-dot") as HTMLElement;

    expect(dot.className).toContain("disabled");
    click(window, dot);
    expect(types(posted)).not.toContain("setEffort");
  });

  it("re-renders an open gear to unlock the controls once busy clears", () => {
    const { window, doc } = bootWithModels({ value: true, locked: true });
    click(window, $(doc, "gear-btn"));
    expect(modelBtn(doc).disabled).toBe(true);

    dispatch(window, { type: "setBusy", value: false });

    expect(($(doc, "gear-popover") as any).hidden).toBe(false); // popover stays open
    expect(modelBtn(doc).disabled).toBe(false); // now unlocked
  });
});

describe("reasoning trace (regression: thinking traces no longer expandable)", () => {
  it("renders a collapsed thinking block whose header toggles the body open/closed", () => {
    const { window, doc } = bootWebview();
    dispatch(window, { type: "thoughtChunk", text: "considering the approach…" });

    const block = doc.querySelector(".msg.thinking")!;
    const hdr = block.querySelector(".thinking-header") as HTMLElement;
    const body = block.querySelector(".thinking-body") as HTMLElement;
    const chevron = block.querySelector(".thinking-chevron") as HTMLElement;

    // Chevron is the same SVG glyph as tool groups; the body's open state is
    // driven by the `.expanded` class on the block (CSS rotates the chevron),
    // not a glyph swap.
    expect(body.hidden).toBe(true);
    expect(chevron.querySelector("svg")).not.toBeNull();
    expect(block.classList.contains("expanded")).toBe(false);

    click(window, hdr);
    expect(body.hidden).toBe(false);
    expect(block.classList.contains("expanded")).toBe(true);

    click(window, hdr);
    expect(body.hidden).toBe(true);
    expect(block.classList.contains("expanded")).toBe(false);
  });
});

describe("Grokking… indicator (waiting placeholder)", () => {
  const grokking = (doc: Document) => doc.querySelector(".grokking") as HTMLElement | null;

  it("mounts on agentStart with a spinning orbit icon, a label, and no dots or chevron", () => {
    const { window, doc } = bootWebview();
    dispatch(window, { type: "agentStart" });

    const el = grokking(doc);
    expect(el).not.toBeNull();
    const label = el!.querySelector(".grokking-label") as HTMLElement;
    expect(label.textContent).toBe("Grokking");
    // The orbit icon is Grokking's motion — no blink-dots here (those are for
    // Thinking / tools); and NOT expandable: no chevron, no body, not .thinking.
    expect(el!.querySelector(".grokking-icon svg")).not.toBeNull();
    expect(el!.querySelector(".blink-dots")).toBeNull();
    expect(el!.querySelector(".thinking-chevron")).toBeNull();
    expect(el!.querySelector(".thinking-body")).toBeNull();
    expect(el!.classList.contains("thinking")).toBe(false);
  });

  it("is replaced in place by the Thinking block on the first thought chunk", () => {
    const { window, doc } = bootWebview();
    dispatch(window, { type: "agentStart" });
    expect(grokking(doc)).not.toBeNull();

    dispatch(window, { type: "thoughtChunk", text: "considering…" });
    expect(grokking(doc)).toBeNull();
    expect(doc.querySelector(".msg.thinking")).not.toBeNull();
  });

  it("is replaced by the agent bubble when the turn streams text without thinking", () => {
    const { window, doc } = bootWebview();
    dispatch(window, { type: "agentStart" });
    dispatch(window, { type: "messageChunk", text: "Here is the answer." });
    expect(grokking(doc)).toBeNull();
    expect(doc.querySelector(".msg.agent")).not.toBeNull();
  });

  it("is replaced when the first content of the turn is a tool call", () => {
    const { window, doc } = bootWebview();
    dispatch(window, { type: "agentStart" });
    dispatch(window, {
      type: "toolCall",
      call: { toolCallId: "t1", title: "read foo.ts", kind: "read", status: "in_progress" },
    });
    expect(grokking(doc)).toBeNull();
    expect(doc.querySelector(".tool-group")).not.toBeNull();
  });

  it("shows on every turn, not just the first (a general typing indicator)", () => {
    const { window, doc } = bootWebview();
    // Turn 1 completes.
    dispatch(window, { type: "agentStart" });
    dispatch(window, { type: "messageChunk", text: "first" });
    dispatch(window, { type: "agentEnd" });
    expect(grokking(doc)).toBeNull();
    // Turn 2 begins → the indicator returns.
    dispatch(window, { type: "agentStart" });
    expect(grokking(doc)).not.toBeNull();
  });

  it("clears on agentEnd even if the turn produced no content", () => {
    const { window, doc } = bootWebview();
    dispatch(window, { type: "agentStart" });
    expect(grokking(doc)).not.toBeNull();
    dispatch(window, { type: "agentEnd" });
    expect(grokking(doc)).toBeNull();
  });

  it("coexists with the user's own bubble, below it (message shows as sent while waiting)", () => {
    const { window, doc } = bootWebview();
    // Mirrors handleSend's order: the user bubble, then agentStart.
    dispatch(window, { type: "userMessage", text: "do the thing", chips: [] });
    dispatch(window, { type: "agentStart" });

    expect(doc.querySelectorAll(".msg.user").length).toBe(1);
    const el = grokking(doc);
    expect(el).not.toBeNull();
    // The indicator sits after the user bubble in DOM order.
    const user = doc.querySelector(".msg.user") as HTMLElement;
    expect(user.compareDocumentPosition(el!) & 4 /* DOCUMENT_POSITION_FOLLOWING */).toBeTruthy();
  });

  it("renders sent-message attachment chips by filename, full path on hover for external files", () => {
    const { window, doc } = bootWebview();
    const external = "c:\\Users\\Dell\\Downloads\\2025-07-14_12-15-44.png";
    dispatch(window, {
      type: "userMessage",
      text: "test",
      chips: [
        { id: "explicit:1", path: "c:\\GitHub\\grok-build-vscode\\CLAUDE.md", relPath: "CLAUDE.md" },
        { id: "explicit:2", path: external, relPath: external },
      ],
    });
    const chips = Array.from(doc.querySelectorAll(".msg.user .msg-chip")) as HTMLElement[];
    const texts = chips.map((c) => c.querySelector("span")!.textContent);
    expect(texts).toContain("CLAUDE.md");
    const ext = chips.find((c) => c.title === external)!; // full path preserved on hover
    expect(ext).toBeTruthy();
    const extText = ext.querySelector("span")!.textContent!;
    expect(extText.startsWith("2025-07-14")).toBe(true); // filename, not the path
    expect(extText).not.toContain("\\");
    expect(extText).not.toContain("Downloads");
  });

  it("shows the selected line range on a sent-message chip, like the composer chip", () => {
    const { window, doc } = bootWebview();
    dispatch(window, {
      type: "userMessage",
      text: "explain these lines",
      chips: [
        {
          id: "implicit:/repo/src/prompt-builder.ts",
          path: "/repo/src/prompt-builder.ts",
          relPath: "src/prompt-builder.ts",
          selectionStart: 60,
          selectionEnd: 82,
        },
        { id: "explicit:1", path: "/repo/src/a.ts", relPath: "src/a.ts", selectionStart: 8, selectionEnd: 8 },
      ],
    });
    const chips = Array.from(doc.querySelectorAll(".msg.user .msg-chip")) as HTMLElement[];
    const texts = chips.map((c) => c.querySelector("span")!.textContent);
    // No 20-char JS truncation — the full name + range must survive (ellipsis is CSS).
    expect(texts).toContain("prompt-builder.ts:60-82");
    expect(texts).toContain("a.ts:8");
    const ranged = chips.find((c) => c.querySelector("span")!.textContent === "prompt-builder.ts:60-82")!;
    expect(ranged.title).toBe("/repo/src/prompt-builder.ts (lines 60-82)");
    const single = chips.find((c) => c.querySelector("span")!.textContent === "a.ts:8")!;
    expect(single.title).toBe("/repo/src/a.ts (line 8)");
  });

  it("rebuilds a replayed selection snippet as a ranged chip, not an inline code block", () => {
    const { window, doc } = bootWebview();
    const replayed =
      "<vscode-context note=\"added by the editor, not typed by the user\">\n" +
      "Attached file: CLAUDE.md\n" +
      "</vscode-context>\n\n" +
      "`src/a.ts` (lines 2-4):\n```ts\nline2\nline3\nline4\n```\n\n" +
      "what is this";

    dispatch(window, { type: "historyReplay", active: true });
    dispatch(window, { type: "userMessageChunk", text: replayed });
    dispatch(window, { type: "historyReplay", active: false });

    const bubble = doc.querySelector(".msg.user") as HTMLElement;
    expect(bubble.textContent).toContain("what is this");
    expect(bubble.textContent).not.toContain("line2"); // snippet body → chip, not a code block
    const texts = Array.from(bubble.querySelectorAll(".msg-chip span")).map((s) => s.textContent);
    expect(texts).toContain("CLAUDE.md");
    expect(texts).toContain("a.ts:2-4");
    const ranged = Array.from(bubble.querySelectorAll(".msg-chip")).find(
      (c) => c.querySelector("span")!.textContent === "a.ts:2-4",
    ) as HTMLElement;
    expect(ranged.title).toBe("src/a.ts (lines 2-4)");
  });

  it("copies only the user's own words from a restored message, not the context plumbing", () => {
    const { window, doc } = bootWebview();
    dispatch(window, { type: "historyReplay", active: true });
    dispatch(window, {
      type: "userMessageChunk",
      text: "`a.ts` (lines 1-1):\n```ts\nconst x = 1;\n```\n\nexplain this",
    });
    dispatch(window, { type: "historyReplay", active: false });

    const msg = doc.querySelector(".msg.user") as HTMLElement & { _copyText?: string };
    expect(msg._copyText).toBe("explain this");
  });

  it("is mutually exclusive with the plan-processing indicator (one waiting indicator at a time)", () => {
    const { window, doc } = bootWebview();
    // planProcessing then agentStart → Grokking wins, plan-processing is gone.
    dispatch(window, { type: "planProcessing" });
    expect(doc.querySelector(".plan-processing")).not.toBeNull();
    dispatch(window, { type: "agentStart" });
    expect(doc.querySelector(".plan-processing")).toBeNull();
    expect(grokking(doc)).not.toBeNull();
    // …and the reverse: planProcessing replaces Grokking.
    dispatch(window, { type: "planProcessing" });
    expect(grokking(doc)).toBeNull();
    expect(doc.querySelector(".plan-processing")).not.toBeNull();
  });

  it("does not duplicate when agentStart fires twice without content", () => {
    const { window, doc } = bootWebview();
    dispatch(window, { type: "agentStart" });
    dispatch(window, { type: "agentStart" });
    expect(doc.querySelectorAll(".grokking").length).toBe(1);
  });
});

describe("user message (regression: doubled on grok 0.2.33)", () => {
  const users = (doc: Document) => doc.querySelectorAll(".msg.user");

  it("does not render a second bubble when a live prompt is echoed back as a user chunk", () => {
    const { window, doc } = bootWebview();

    // Live send: the host posts the optimistic bubble.
    dispatch(window, { type: "userMessage", text: "/imagine a rocket", chips: [] });
    expect(users(doc).length).toBe(1);

    // grok 0.2.33 echoes the prompt back as a user_message_chunk mid-turn (not
    // replaying). It must NOT spawn a duplicate bubble.
    dispatch(window, { type: "userMessageChunk", text: "/imagine a rocket" });
    expect(users(doc).length).toBe(1);
  });

  it("still renders the user bubble from chunks during a session replay", () => {
    const { window, doc } = bootWebview();

    dispatch(window, { type: "historyReplay", active: true });
    dispatch(window, { type: "userMessageChunk", text: "resumed prompt" });

    expect(users(doc).length).toBe(1);
    expect(users(doc)[0].textContent).toContain("resumed prompt");
  });
});

describe("welcome version line (session-start lifecycle)", () => {
  const verEl = (doc: Document) => $(doc, "welcome-version");
  const ver = (doc: Document) => verEl(doc).textContent;
  // The trailing dots are an animated ::after pseudo-element (the .loading-dots
  // class), so the literal text is dot-free while a status is transient.
  const animating = (doc: Document) => verEl(doc).classList.contains("loading-dots");

  it("flips to connected only when priming finishes, not at the handshake", () => {
    const { window, doc } = bootWebview();

    // ACP handshake done — but the hidden primer is still in flight, so the
    // line must stay "Starting…" (animated), NOT jump to "Connected" yet.
    dispatch(window, { type: "initialized", info: { version: "0.2.33" } });
    expect(ver(doc)).toBe("Starting");
    expect(animating(doc)).toBe(true);

    // Priming spinner clears → grok is finally ready → reveal the version.
    dispatch(window, { type: "setBusy", value: false });
    expect(ver(doc)).toBe("Connected · v0.2.33");
    expect(animating(doc)).toBe(false); // settled — dots stop
  });

  it("shows the silent-update hint, then starting, then the new version", () => {
    const { window, doc } = bootWebview();

    dispatch(window, { type: "cliUpdating" });
    expect(ver(doc)).toBe("Updating Grok Build CLI");
    expect(animating(doc)).toBe(true);

    dispatch(window, { type: "initialized", info: { version: "0.2.40" } });
    expect(ver(doc)).toBe("Starting");
    expect(animating(doc)).toBe(true);

    dispatch(window, { type: "setBusy", value: false });
    expect(ver(doc)).toBe("Connected · v0.2.40");
    expect(animating(doc)).toBe(false);
  });

  it("does not overwrite the version on later (post-priming) busy toggles", () => {
    const { window, doc } = bootWebview();
    dispatch(window, { type: "initialized", info: { version: "0.2.33" } });
    dispatch(window, { type: "setBusy", value: false });
    expect(ver(doc)).toBe("Connected · v0.2.33");

    // A normal prompt's busy cycle later — the line must not revert.
    dispatch(window, { type: "setBusy", value: true });
    dispatch(window, { type: "setBusy", value: false });
    expect(ver(doc)).toBe("Connected · v0.2.33");
  });
});

describe("send button startup state (spinner by default until the session is ready)", () => {
  const sendBtn = (doc: Document) => $(doc, "send-btn") as HTMLButtonElement;

  it("shows the disabled spinner from the first paint, before the host says ready", () => {
    const { doc } = bootWebview({ ready: false });
    expect(sendBtn(doc).classList.contains("initializing")).toBe(true);
    expect(sendBtn(doc).disabled).toBe(true);
    expect(sendBtn(doc).classList.contains("stop")).toBe(false);
  });

  it("switches to the enabled send arrow once the host posts setBusy:false", () => {
    const { window, doc } = bootWebview({ ready: false });
    dispatch(window, { type: "setBusy", value: false });
    expect(sendBtn(doc).classList.contains("initializing")).toBe(false);
    expect(sendBtn(doc).disabled).toBe(false);
  });
});

describe("gear menu — Other group + About / Config & debug sub-views", () => {
  function boot() {
    const h = bootWebview();
    dispatch(h.window, { type: "initialState", useCtrlEnter: false, effort: "", cwd: "/x", extVersion: "1.4.0" });
    dispatch(h.window, { type: "initialized", info: { version: "0.2.33" } });
    dispatch(h.window, { type: "session", sessionId: "s1", models: [], currentModelId: "grok-build" });
    h.posted.length = 0;
    return h;
  }
  const gear = (doc: Document) => $(doc, "gear-popover");
  const items = (doc: Document) => [...doc.querySelectorAll("#gear-popover .toolbar-popover-item")] as HTMLElement[];
  const itemByText = (doc: Document, text: string) =>
    items(doc).find((el) => el.textContent!.includes(text)) as HTMLElement;

  it("replaces the flat Config/Account/Debug sections with an Other group", () => {
    const h = boot();
    click(h.window, $(h.doc, "gear-btn"));
    const labels = items(h.doc).map((el) => el.textContent || "");
    expect(labels.some((l) => l.includes("Version & about"))).toBe(true);
    expect(labels.some((l) => l.includes("Config & debug"))).toBe(true);
    expect(labels.some((l) => l.includes("Log out"))).toBe(true);
    // the old standalone items no longer live on the main view
    expect(labels.some((l) => l.trim() === "Sign out")).toBe(false);
    expect(labels.some((l) => l.includes("Show extension logs"))).toBe(false);
  });

  it("About shows both versions and requests an update check", () => {
    const h = boot();
    click(h.window, $(h.doc, "gear-btn"));
    click(h.window, itemByText(h.doc, "Version & about"));

    const text = gear(h.doc).textContent || "";
    expect(text).toContain("This extension");
    expect(text).toContain("v1.4.0");
    expect(text).toContain("Grok Build CLI");
    expect(text).toContain("v0.2.33");
    expect(types(h.posted)).toContain("checkGrokUpdate");
  });

  it("enables Update Grok Build when an update is available and posts updateGrok", () => {
    const h = boot();
    click(h.window, $(h.doc, "gear-btn"));
    click(h.window, itemByText(h.doc, "Version & about"));
    dispatch(h.window, { type: "grokUpdateStatus", current: "0.2.3", latest: "0.2.33", updateAvailable: true });

    expect(gear(h.doc).textContent).toContain("Update available");
    const btn = itemByText(h.doc, "Update Grok Build");
    expect(btn.className).not.toContain("disabled");

    h.posted.length = 0;
    click(h.window, btn);
    expect(types(h.posted)).toContain("updateGrok");
  });

  it("shows a grayed up-to-date status and no update action when current", () => {
    const h = boot();
    click(h.window, $(h.doc, "gear-btn"));
    click(h.window, itemByText(h.doc, "Version & about"));
    dispatch(h.window, { type: "grokUpdateStatus", current: "0.2.33", latest: "0.2.33", updateAvailable: false });

    expect(gear(h.doc).textContent).toContain("up to date");
    expect(itemByText(h.doc, "Update Grok Build")).toBeUndefined();
  });

  it("falls back to the update check's version when the handshake gave none", () => {
    const h = bootWebview();
    dispatch(h.window, { type: "initialState", useCtrlEnter: false, effort: "", cwd: "/x", extVersion: "1.4.0" });
    // No `initialized` version (native Windows build) — the panel starts at "—".
    dispatch(h.window, { type: "session", sessionId: "s1", models: [], currentModelId: "grok-build" });
    click(h.window, $(h.doc, "gear-btn"));
    click(h.window, itemByText(h.doc, "Version & about"));
    dispatch(h.window, { type: "grokUpdateStatus", current: "0.2.3", latest: "0.2.3", updateAvailable: false });

    const text = gear(h.doc).textContent || "";
    expect(text).toContain("Grok Build CLI");
    expect(text).toContain("v0.2.3");
    expect(text).not.toContain("—");
  });

  it("the About back row returns to the main menu", () => {
    const h = boot();
    click(h.window, $(h.doc, "gear-btn"));
    click(h.window, itemByText(h.doc, "Version & about"));
    click(h.window, itemByText(h.doc, "← Version & about"));
    expect(items(h.doc).some((el) => (el.textContent || "").includes("Config & debug"))).toBe(true);
  });

  it("Config & debug exposes the config + logs links and posts the right message", () => {
    const h = boot();
    click(h.window, $(h.doc, "gear-btn"));
    click(h.window, itemByText(h.doc, "Config & debug"));

    const labels = items(h.doc).map((el) => el.textContent || "");
    expect(labels.some((l) => l.includes("Open global config"))).toBe(true);
    expect(labels.some((l) => l.includes("Open project config"))).toBe(true);
    expect(labels.some((l) => l.includes("MCP servers"))).toBe(true);
    expect(labels.some((l) => l.includes("Show extension logs"))).toBe(true);

    click(h.window, itemByText(h.doc, "Show extension logs"));
    expect(types(h.posted)).toContain("showLogs");
  });
});

describe("Auto accept mode label (#25 rename)", () => {
  it("labels the auto-approve mode 'Auto accept' and keeps YOLO only in the description", () => {
    const { window, doc } = bootWebview();
    click(window, $(doc, "mode-btn"));
    const pop = $(doc, "mode-popover");
    const yolo = [...pop.querySelectorAll(".mode-popover-item")].find(
      (el) => el.querySelector(".mode-item-label")?.textContent === "Auto accept",
    ) as HTMLElement;
    expect(yolo).toBeTruthy();
    expect(yolo.querySelector(".mode-item-desc")?.textContent).toContain("YOLO");
  });
});

describe("thinking traces toggle (#26)", () => {
  it("applies the hidden body class from initialState (off by default)", () => {
    const { window, doc } = bootWebview();
    dispatch(window, { type: "initialState", useCtrlEnter: false, showThinking: false });
    expect(doc.body.classList.contains("thinking-hidden")).toBe(true);
  });

  it("toggles the body class live on a showThinking message", () => {
    const { window, doc } = bootWebview();
    dispatch(window, { type: "showThinking", value: true });
    expect(doc.body.classList.contains("thinking-hidden")).toBe(false);
    dispatch(window, { type: "showThinking", value: false });
    expect(doc.body.classList.contains("thinking-hidden")).toBe(true);
  });

  it("stands in a 'Thinking…' indicator while hidden, still building the real block", () => {
    const { window, doc } = bootWebview();
    dispatch(window, { type: "showThinking", value: false });
    dispatch(window, { type: "thoughtChunk", text: "weighing options…" });
    const ind = doc.querySelector(".thinking-indicator");
    expect(ind).not.toBeNull();
    expect(ind!.querySelectorAll(".blink-dots span").length).toBe(3);
    // the real reasoning block is still built (just CSS-hidden), never lost
    expect(doc.querySelector(".msg.thinking")).not.toBeNull();
  });

  it("shows no stand-in when traces are visible", () => {
    const { window, doc } = bootWebview();
    dispatch(window, { type: "showThinking", value: true });
    dispatch(window, { type: "thoughtChunk", text: "weighing options…" });
    expect(doc.querySelector(".thinking-indicator")).toBeNull();
    expect(doc.querySelector(".msg.thinking")).not.toBeNull();
  });

  it("drops the stand-in when real agent text arrives", () => {
    const { window, doc } = bootWebview();
    dispatch(window, { type: "showThinking", value: false });
    dispatch(window, { type: "thoughtChunk", text: "weighing…" });
    expect(doc.querySelector(".thinking-indicator")).not.toBeNull();
    dispatch(window, { type: "messageChunk", text: "Here's the answer." });
    expect(doc.querySelector(".thinking-indicator")).toBeNull();
  });

  it("exposes a Show thinking traces switch in Config & debug that posts setShowThinking and flips the class", () => {
    const { window, posted, doc } = bootWebview();
    dispatch(window, { type: "showThinking", value: false });
    expect(doc.body.classList.contains("thinking-hidden")).toBe(true);
    click(window, $(doc, "gear-btn"));
    const cfg = [...doc.querySelectorAll("#gear-popover .toolbar-popover-item")].find(
      (el) => el.textContent?.includes("Config & debug"),
    ) as HTMLElement;
    click(window, cfg);
    const toggle = [...doc.querySelectorAll("#gear-popover .toolbar-popover-item")].find(
      (el) => el.textContent?.includes("Show thinking traces"),
    ) as HTMLElement;
    expect(toggle).toBeTruthy();
    expect(toggle.querySelector(".popover-switch")).not.toBeNull();
    click(window, toggle);
    expect(posted.some((p) => p.type === "setShowThinking" && p.value === true)).toBe(true);
    expect(doc.body.classList.contains("thinking-hidden")).toBe(false); // optimistic flip
  });
});

describe("scroll-to-bottom button (#28)", () => {
  const setMetrics = (window: any, list: HTMLElement, top: number, height: number, client: number) => {
    Object.defineProperty(list, "scrollHeight", { value: height, configurable: true });
    Object.defineProperty(list, "clientHeight", { value: client, configurable: true });
    Object.defineProperty(list, "scrollTop", { value: top, configurable: true, writable: true });
    list.dispatchEvent(new window.Event("scroll"));
  };

  it("shows when scrolled away from the bottom and hides at the bottom (same threshold)", () => {
    const { window, doc } = bootWebview();
    const btn = $(doc, "scroll-bottom-btn");
    const list = $(doc, "messages");
    setMetrics(window, list, 0, 1000, 300); // 700px from bottom → visible
    expect(btn.classList.contains("visible")).toBe(true);
    setMetrics(window, list, 680, 1000, 300); // 20px from bottom (≤40) → hidden
    expect(btn.classList.contains("visible")).toBe(false);
  });

  it("re-pins to the bottom and hides on click", () => {
    const { window, doc } = bootWebview();
    const btn = $(doc, "scroll-bottom-btn");
    const list = $(doc, "messages") as any;
    list.scrollTo = () => {}; // happy-dom has no smooth-scroll impl
    setMetrics(window, list, 0, 1000, 300);
    expect(btn.classList.contains("visible")).toBe(true);
    click(window, btn);
    expect(btn.classList.contains("visible")).toBe(false);
  });
});

describe("continuous progress indicator (always show something mid-turn)", () => {
  // A *live* progress affordance: Grokking / a running tool group / Thinking /
  // plan-processing / streaming message / an open card. A CSS-hidden thinking
  // block does NOT count (that's the whole point of the stand-in).
  const hasLiveIndicator = (doc: Document) => {
    if (
      doc.querySelector(
        ".grokking, .thinking-indicator, .tool-group.in-progress, .plan-processing, .msg.agent, .card:not(.resolved)",
      )
    )
      return true;
    // A thinking block is a live indicator only when traces are shown (a hidden
    // one is display:none via the body class — the stand-in covers that case).
    return !doc.body.classList.contains("thinking-hidden") && !!doc.querySelector(".msg.thinking");
  };

  // A realistic interleaved turn, mirroring how real sessions stream: start →
  // reason → run a tool → reason → narrate → reason → narrate.
  const STEPS: any[] = [
    { type: "agentStart" },
    { type: "thoughtChunk", text: "let me look at the file" },
    { type: "thoughtChunk", text: " and weigh the options" },
    { type: "toolCall", call: { toolCallId: "t1", kind: "read", title: "Read `/a.ts`" } },
    { type: "toolCallUpdate", call: { toolCallId: "t1", status: "completed" } },
    { type: "thoughtChunk", text: "now I'll edit it" },
    { type: "messageChunk", text: "Here's what I'll do: " },
    { type: "thoughtChunk", text: "one more consideration" },
    { type: "messageChunk", text: "and the rest of the answer." },
  ];

  const simulate = (showThinking: boolean) => {
    const { window, doc } = bootWebview();
    dispatch(window, { type: "showThinking", value: showThinking });
    dispatch(window, { type: "setBusy", value: true }); // a user turn is in flight
    for (const step of STEPS) {
      dispatch(window, step);
      expect(
        hasLiveIndicator(doc),
        `blank frame after ${step.type} (showThinking=${showThinking})`,
      ).toBe(true);
    }
    dispatch(window, { type: "agentEnd" }); // turn done — idle is allowed now
  };

  it("never leaves a blank frame mid-turn with thinking hidden (the default)", () => {
    simulate(false);
  });

  it("never leaves a blank frame mid-turn with thinking shown", () => {
    simulate(true);
  });

  it("stands in with Grokking when a step would otherwise leave nothing visible", () => {
    const { window, doc } = bootWebview();
    dispatch(window, { type: "setBusy", value: true }); // unlocked turn, nothing shown yet
    expect(doc.querySelector(".grokking")).toBeNull();
    // A bare completed-tool update with no prior group leaves nothing on its own…
    dispatch(window, { type: "toolCallUpdate", call: { toolCallId: "x", status: "completed" } });
    expect(doc.querySelector(".grokking")).not.toBeNull(); // …so the safety net stands in
  });

  it("does not stand in during the locked priming window", () => {
    const { window, doc } = bootWebview();
    dispatch(window, { type: "setBusy", value: true, locked: true }); // priming
    dispatch(window, { type: "toolCallUpdate", call: { toolCallId: "x", status: "completed" } });
    expect(doc.querySelector(".grokking")).toBeNull();
  });
});

// LaTeX rendering: grok now emits TeX (\(...\) inline, \[...\] display). The
// webview pulls math out before HTML-escaping and renders it via KaTeX. KaTeX
// isn't loaded in the happy-dom harness, so renderMarkdown falls back to the
// escaped raw TeX (.math-raw) — which is exactly what proves the extract/restore
// pipeline runs and that the backslashes survive the inline-markdown pass.
describe("LaTeX math rendering", () => {
  // promptComplete forces a synchronous flushAgent so the markdown is in the DOM.
  const renderAgent = (text: string) => {
    const { doc, window } = bootWebview();
    dispatch(window, { type: "messageChunk", text });
    dispatch(window, { type: "promptComplete" });
    return doc.querySelector(".msg.agent") as HTMLElement;
  };

  it("renders inline \\(...\\) math as a math node, not raw delimiters", () => {
    const el = renderAgent("The area is \\(\\pi r^2\\) exactly.");
    const math = el.querySelector(".math-raw");
    expect(math).not.toBeNull();
    expect(math!.textContent).toBe("\\pi r^2");
    // the literal delimiters must NOT survive into the rendered text
    expect(el.textContent).not.toContain("\\(");
    expect(el.textContent).not.toContain("\\)");
  });

  it("renders display \\[...\\] math as a block", () => {
    const el = renderAgent("Result:\n\\[E = mc^2\\]\ndone");
    const math = el.querySelector(".math-raw.math-display");
    expect(math).not.toBeNull();
    expect(math!.textContent).toBe("E = mc^2");
  });

  it("preserves a matrix (backslashes + braces) through the markdown pipeline", () => {
    const el = renderAgent("\\[\\begin{pmatrix} 1 & 2 \\\\ 3 & 4 \\end{pmatrix}\\]");
    const math = el.querySelector(".math-raw.math-display") as HTMLElement;
    expect(math).not.toBeNull();
    expect(math.textContent).toContain("\\begin{pmatrix}");
    expect(math.textContent).toContain("&");
  });

  it("leaves prose with bare dollar amounts untouched", () => {
    const el = renderAgent("it costs $5 and then $10");
    expect(el.querySelector(".math-raw")).toBeNull();
    expect(el.textContent).toContain("it costs $5 and then $10");
  });

  it("strips \\label{...} so an align block doesn't render a red error (KaTeX has no \\ref)", () => {
    const el = renderAgent(
      "\\[\\begin{align} f(x) &= x^2 \\label{eq:quadratic} \\\\ f'(x) &= 2x \\end{align}\\]",
    );
    const math = el.querySelector(".math-raw.math-display") as HTMLElement;
    expect(math).not.toBeNull();
    // the unsupported \label macro is gone, the equation body survives
    expect(math.textContent).not.toContain("\\label");
    expect(math.textContent).not.toContain("eq:quadratic");
    expect(math.textContent).toContain("\\begin{align}");
    expect(math.textContent).toContain("f(x) &= x^2");
  });
});

describe("Mermaid diagram rendering", () => {
  // mermaid (the 3.3 MB browser bundle) is never loaded in happy-dom, so these
  // exercise the fallback: a ```mermaid fence becomes a tagged .mermaid-block
  // whose source stays readable until the real lib swaps in an SVG at runtime.
  const renderAgent = (text: string) => {
    const { doc, window } = bootWebview();
    dispatch(window, { type: "messageChunk", text });
    dispatch(window, { type: "promptComplete" });
    return doc.querySelector(".msg.agent") as HTMLElement;
  };

  it("turns a ```mermaid fence into a .mermaid-block, not a plain code block", () => {
    const el = renderAgent(
      "Here:\n```mermaid\nflowchart TD\n    A[Start] --> B[End]\n```\ndone",
    );
    const block = el.querySelector(".mermaid-block");
    expect(block).not.toBeNull();
    // mermaid isn't loaded under happy-dom, so it must stay in the fallback state
    expect(block!.getAttribute("data-mermaid-state")).toBeNull();
  });

  it("keeps the diagram source readable in the fallback", () => {
    const el = renderAgent("```mermaid\nsequenceDiagram\n    A->>B: hi\n```");
    const src = el.querySelector(".mermaid-block .mermaid-src") as HTMLElement;
    expect(src).not.toBeNull();
    expect(src.textContent).toContain("sequenceDiagram");
    expect(src.textContent).toContain("A->>B: hi");
  });

  it("leaves a non-mermaid fenced block as a normal code block", () => {
    const el = renderAgent("```js\nconst x = 1;\n```");
    expect(el.querySelector(".mermaid-block")).toBeNull();
    const code = el.querySelector(".code-block") as HTMLElement;
    expect(code).not.toBeNull();
    expect(code.textContent).toContain("const x = 1;");
  });

  it("does not treat a half-streamed (unclosed) mermaid fence as a diagram", () => {
    const el = renderAgent("```mermaid\nflowchart TD\n    A --> B");
    expect(el.querySelector(".mermaid-block")).toBeNull();
    // the raw text shows through until the closing fence arrives
    expect(el.textContent).toContain("flowchart TD");
  });

  // A single markdown blank line around a fenced block must NOT render as a doubled
  // gap. The block placeholder used to fall through to the paragraph path and get
  // wrapped in <br><br> before/after; on top of the .code-block div's own margin
  // that read as ~2 blank lines (the model only sent one). It's now emitted as its
  // own block, like tables/math, so no <br> hugs the code block.
  it("does not glue <br> around a code block (single blank line, not doubled)", () => {
    const el = renderAgent("Folders:\n\n```\ndocs/\n```\n\nNo other dirs.");
    const block = el.querySelector(".code-block") as HTMLElement;
    expect(block).not.toBeNull();
    expect(block.previousElementSibling?.tagName).not.toBe("BR");
    expect(block.nextElementSibling?.tagName).not.toBe("BR");
    expect(el.textContent).toContain("Folders:");
    expect(el.textContent).toContain("No other dirs.");
  });
});

// Nested code blocks (issue #20): an outer fence of 4+ backticks must survive so
// it can wrap an inner ``` block. The old regex hardcoded exactly 3 backticks for
// both fences, so it ate the first 3 of a 5-backtick outer fence and closed early
// on the inner ```python fence — splitting one block into several and dropping
// backticks. The fix matches a 3+ backtick fence and requires the close to be the
// same length, so shorter inner fences can't terminate the outer block.
describe("nested code blocks (issue #20)", () => {
  const renderAgent = (text: string) => {
    const { doc, window } = bootWebview();
    dispatch(window, { type: "messageChunk", text });
    dispatch(window, { type: "promptComplete" });
    return doc.querySelector(".msg.agent") as HTMLElement;
  };

  const NESTED_5 =
    "`````text\n" +
    "Here is an example of nested code blocks.\n\n" +
    "```python\n" +
    "def hello():\n" +
    '    print("Hello, world!")\n' +
    "```\n\n" +
    "The outer block uses 5 backticks.\n" +
    "`````";

  it("keeps a 5-backtick outer fence as ONE code block", () => {
    const el = renderAgent(NESTED_5);
    expect(el.querySelectorAll(".code-block").length).toBe(1);
  });

  it("preserves the inner ``` fence literally inside the outer block", () => {
    const el = renderAgent(NESTED_5);
    const code = el.querySelector(".code-block") as HTMLElement;
    expect(code.textContent).toContain("```python");
    expect(code.textContent).toContain("def hello():");
    // the inner closing fence + the outer prose both live inside the one block
    expect(code.textContent).toContain("The outer block uses 5 backticks.");
  });

  it("handles a 4-backtick outer fence the same way", () => {
    const el = renderAgent(
      "````\n```js\nconst x = 1;\n```\n````",
    );
    expect(el.querySelectorAll(".code-block").length).toBe(1);
    const code = el.querySelector(".code-block") as HTMLElement;
    expect(code.textContent).toContain("```js");
    expect(code.textContent).toContain("const x = 1;");
  });

  it("still renders a plain 3-backtick block (the N=3 case)", () => {
    const el = renderAgent("```js\nconst y = 2;\n```");
    expect(el.querySelectorAll(".code-block").length).toBe(1);
    expect((el.querySelector(".code-block") as HTMLElement).textContent)
      .toContain("const y = 2;");
  });

  it("renders two sequential blocks of different fence lengths", () => {
    const el = renderAgent(
      "```js\na\n```\nthen\n`````md\n```inner```\n`````",
    );
    const blocks = el.querySelectorAll(".code-block");
    expect(blocks.length).toBe(2);
    expect(blocks[0].textContent).toContain("a");
    expect(blocks[1].textContent).toContain("```inner```");
  });
});

describe("math / diagram export actions (step b)", () => {
  const renderAgent = (window: any, text: string) => {
    dispatch(window, { type: "messageChunk", text });
    dispatch(window, { type: "promptComplete" });
    return window.document.querySelector(".msg.agent") as HTMLElement;
  };

  it("wraps display math in an export host with Copy/Download/Open carrying the source", () => {
    const { window } = bootWebview();
    const el = renderAgent(window, "Result:\n\\[E = mc^2\\]\ndone");
    const host = el.querySelector(".math-export") as HTMLElement;
    expect(host).not.toBeNull();
    expect(host.getAttribute("data-export-kind")).toBe("latex");
    expect(host.getAttribute("data-export-src")).toBe("E = mc^2");
    const acts = [...host.querySelectorAll(".expr-btn")].map((b) => b.getAttribute("data-expr-act"));
    expect(acts).toEqual(["copy", "download", "open"]);
  });

  it("does NOT add export actions to inline math", () => {
    const { window } = bootWebview();
    const el = renderAgent(window, "area is \\(\\pi r^2\\) ok");
    expect(el.querySelector(".math-export")).toBeNull();
    expect(el.querySelector(".expr-actions")).toBeNull();
  });

  it("Copy writes the original source TeX to the clipboard", () => {
    const { window } = bootWebview();
    let copied: string | null = null;
    Object.defineProperty((window as any).navigator, "clipboard", {
      value: { writeText: (t: string) => { copied = t; return Promise.resolve(); } },
      configurable: true,
    });
    const el = renderAgent(window, "\\[a^2 + b^2 = c^2\\]");
    const copyBtn = el.querySelector('.expr-btn[data-expr-act="copy"]') as HTMLElement;
    click(window, copyBtn);
    expect(copied).toBe("a^2 + b^2 = c^2");
  });

  it("Download posts an exportExpr message with transparent dark + light SVG variants", () => {
    const { window, posted } = bootWebview();
    const el = renderAgent(window, "\\[x^2\\]");
    const host = el.querySelector(".math-export") as HTMLElement;
    // happy-dom has no MathJax, so stand in a minimal SVG for the rendered output.
    const svg = (window as any).document.createElementNS("http://www.w3.org/2000/svg", "svg");
    host.insertBefore(svg, host.firstChild);
    click(window, host.querySelector('.expr-btn[data-expr-act="download"]') as HTMLElement);
    const msg = posted.find((p) => p.type === "exportExpr");
    expect(msg).toBeTruthy();
    expect(msg!.action).toBe("download");
    expect(msg!.kind).toBe("latex");
    // two SVG variants for the host to quick-pick between; neither paints a bg.
    expect(typeof msg!.svgDark).toBe("string");
    expect(typeof msg!.svgLight).toBe("string");
    expect(msg!.svgDark as string).not.toContain("background:");
  });
});

// The composer's active-editor context chip mirrors Claude Code's: full file
// name (CSS ellipsis handles pathological lengths — no JS truncation), plus a
// live `:start-end` line-range suffix while the user has an editor selection.
describe("active-editor context chip in the composer", () => {
  const implicitChip = (over: Record<string, unknown> = {}) => ({
    id: "implicit:/ws/vitest.perf.config.ts",
    path: "/ws/vitest.perf.config.ts",
    relPath: "vitest.perf.config.ts",
    hidden: false,
    ...over,
  });

  it("shows the full file name — no 10-char JS truncation", () => {
    const { window, doc } = bootWebview();
    dispatch(window, { type: "chips", chips: [implicitChip()] });
    const span = doc.querySelector("#chips .chip span")!;
    expect(span.textContent).toBe("vitest.perf.config.ts");
  });

  it("appends the selected line range to the label and tooltip", () => {
    const { window, doc } = bootWebview();
    dispatch(window, { type: "chips", chips: [implicitChip({ selectionStart: 8, selectionEnd: 15 })] });
    const chip = doc.querySelector("#chips .chip") as HTMLElement;
    expect(chip.querySelector("span")!.textContent).toBe("vitest.perf.config.ts:8-15");
    expect(chip.getAttribute("title")).toBe("/ws/vitest.perf.config.ts (lines 8-15)");
  });

  it("labels a single-line selection with one line number", () => {
    const { window, doc } = bootWebview();
    dispatch(window, { type: "chips", chips: [implicitChip({ selectionStart: 8, selectionEnd: 8 })] });
    const chip = doc.querySelector("#chips .chip") as HTMLElement;
    expect(chip.querySelector("span")!.textContent).toBe("vitest.perf.config.ts:8");
    expect(chip.getAttribute("title")).toBe("/ws/vitest.perf.config.ts (line 8)");
  });

  it("escapes HTML in the file name instead of injecting it", () => {
    const { window, doc } = bootWebview();
    dispatch(window, {
      type: "chips",
      chips: [implicitChip({ relPath: "<img src=x>.ts", path: "/ws/<img src=x>.ts", id: "implicit:/ws/x" })],
    });
    const chip = doc.querySelector("#chips .chip") as HTMLElement;
    expect(chip.querySelector("span")!.textContent).toBe("<img src=x>.ts");
    expect(chip.querySelector("img")).toBeNull();
  });
});

// A selection sent via the "Add Selection to Grok" command is an EXPLICIT
// attachment (id "explicit:…"), so it belongs in the top attachments row like
// any other attached file — removable, with its line range on the label. Only
// the ambient active-editor chip (implicit) stays in the bottom toolbar.
describe("explicit selection chip placement (top attachments row)", () => {
  const explicitSel = {
    id: "explicit:/repo/src/a.ts:8-12:1",
    path: "/repo/src/a.ts",
    relPath: "src/a.ts",
    selectionStart: 8,
    selectionEnd: 12,
    hidden: false,
  };

  it("renders a command-sent selection in the top row with its range + a remove button", () => {
    const { window, posted, doc } = bootWebview();
    dispatch(window, { type: "chips", chips: [explicitSel] });

    // Top attachments area, NOT the bottom toolbar.
    expect(doc.querySelector("#chips .chip")).toBeNull();
    const row = doc.querySelector("#attachments .attachment") as HTMLElement;
    expect(row).not.toBeNull();
    expect(row.querySelector("span")!.textContent).toBe("a.ts:8-12"); // range survives the move to the top
    expect(row.title).toBe("/repo/src/a.ts (lines 8-12)");

    // Removable like any other attachment (not a hide toggle).
    const rm = row.querySelector(".attachment-remove") as HTMLElement;
    expect(rm).not.toBeNull();
    click(window, rm);
    expect(posted.find((m) => m.type === "removeChip" && m.id === explicitSel.id)).toBeTruthy();
  });

  it("keeps the ambient active-editor selection in the bottom toolbar", () => {
    const { window, doc } = bootWebview();
    dispatch(window, {
      type: "chips",
      chips: [{ ...explicitSel, id: "implicit:/repo/src/a.ts" }],
    });
    expect(doc.querySelector("#attachments .attachment")).toBeNull();
    const chip = doc.querySelector("#chips .chip") as HTMLElement;
    expect(chip.querySelector("span")!.textContent).toBe("a.ts:8-12");
  });
});

// Opening the panel must land the caret in the input — no first click needed
// (mirrors Claude Code / Codex). Boot focuses directly (the webview is rebuilt
// on every re-show); a window "focus" landing on <body> is forwarded to the
// input, but never stolen from a real control.
describe("composer input focus (caret ready on open)", () => {
  it("focuses the input on boot, so typing works without a first click", () => {
    const { doc } = bootWebview();
    expect(doc.activeElement).toBe($(doc, "input"));
  });

  it("forwards window focus that landed on <body> to the input", () => {
    const { window, doc } = bootWebview();
    ($(doc, "input") as HTMLTextAreaElement).blur(); // focus falls back to <body>
    expect(doc.activeElement).toBe(doc.body);

    window.dispatchEvent(new (window as any).Event("focus"));
    expect(doc.activeElement).toBe($(doc, "input"));
  });

  it("does not steal focus from a control the user actually focused", () => {
    const { window, doc } = bootWebview();
    const btn = $(doc, "history-btn") as HTMLButtonElement;
    btn.focus();

    window.dispatchEvent(new (window as any).Event("focus"));
    expect(doc.activeElement).toBe(btn);
  });

  it("lands the caret in the input on the new-session click", () => {
    const { window, doc } = bootWebview();
    const newBtn = $(doc, "new-btn") as HTMLButtonElement;
    newBtn.focus(); // the click leaves focus on the button
    click(window, newBtn);
    expect(doc.activeElement).toBe($(doc, "input"));
  });

  it("lands the caret in the input on a session swap (clearMessages)", () => {
    // Both a history-row re-focus and a disk restore reach the webview as the
    // host's clearMessages; the user just clicked a popover row, so the caret
    // should end up ready in the box.
    const { window, doc } = bootWebview();
    ($(doc, "input") as HTMLTextAreaElement).blur();
    dispatch(window, { type: "clearMessages" });
    expect(doc.activeElement).toBe($(doc, "input"));
  });
});

describe("gear entry: Move view (Config & debug)", () => {
  function openConfigDebug(window: Window, doc: Document) {
    click(window, $(doc, "gear-btn"));
    const item = [...doc.querySelectorAll("#gear-popover .toolbar-popover-item")].find((el) =>
      el.textContent!.includes("Config & debug"),
    ) as HTMLElement;
    click(window, item);
  }
  const itemByLabel = (doc: Document, label: string) =>
    [...doc.querySelectorAll("#gear-popover .toolbar-popover-item")].find((el) =>
      el.textContent!.includes(label),
    ) as HTMLElement | undefined;

  it("offers the three destinations, each posting moveView with its location", () => {
    const { window, posted, doc } = bootWebview();
    const destinations: Array<[string, string]> = [
      ["To Secondary Side Bar", "auxiliarybar"],
      ["To Primary Side Bar", "sidebar"],
      ["To Panel", "panel"],
    ];
    for (const [label, location] of destinations) {
      openConfigDebug(window, doc); // clicking an item closes the popover — reopen each time
      const item = itemByLabel(doc, label);
      expect(item, label).toBeTruthy();
      click(window, item!);
      expect(posted).toContainEqual({ type: "moveView", location });
    }
  });
});

describe("context popover (donut click, #39)", () => {
  it("opens on donut click with the context line, closes on outside click", () => {
    const { window, doc } = bootWebview();
    dispatch(window, { type: "promptComplete", meta: { totalTokens: 44123 } });

    click(window, $(doc, "donut"));
    const pop = $(doc, "context-popover");
    expect((pop as any).hidden).toBe(false);
    expect(pop.textContent).toContain("Context used");

    click(window, $(doc, "messages"));
    expect((pop as any).hidden).toBe(true);
  });

  it("shows only the context line — no action rows", () => {
    const { window, doc } = bootWebview();
    click(window, $(doc, "donut"));
    expect($(doc, "context-popover").querySelector(".toolbar-popover-item")).toBeNull();
  });
});

describe("agent message footer (copy + timestamp) — one per turn", () => {
  it("keeps the footer only on the turn's last narration segment, revealed at turn end", () => {
    const { window, doc } = bootWebview();
    dispatch(window, { type: "userMessage", text: "do things" });
    dispatch(window, { type: "agentStart" });
    dispatch(window, { type: "messageChunk", text: "first I'll look around" });
    // A tool group splits the prose into a second .msg.agent segment.
    dispatch(window, { type: "toolCall", call: { toolCallId: "t1", title: "read_file", kind: "read" } });
    dispatch(window, { type: "messageChunk", text: "here is the conclusion" });

    // Mid-turn: the (single) footer exists but is HIDDEN — no copy icons
    // flickering through the conversation while the agent works.
    let agentFooters = [...doc.querySelectorAll(".msg.agent .msg-actions")] as HTMLElement[];
    expect(agentFooters).toHaveLength(1);
    expect(agentFooters[0].hidden).toBe(true);

    dispatch(window, { type: "promptComplete", meta: {} }); // commits the bubble (real turns always emit it)
    dispatch(window, { type: "agentEnd" });

    agentFooters = [...doc.querySelectorAll(".msg.agent .msg-actions")] as HTMLElement[];
    expect(agentFooters).toHaveLength(1);
    expect(agentFooters[0].hidden).toBe(false);
    // …and it sits on the LAST segment (the conclusion), not the first.
    expect(agentFooters[0].closest(".msg.agent")!.textContent).toContain("here is the conclusion");
    // The user bubble keeps its own footer, visible immediately.
    expect(doc.querySelectorAll(".msg.user .msg-actions")).toHaveLength(1);
  });

  it("each turn keeps its own footer — a new turn doesn't steal the previous one", () => {
    const { window, doc } = bootWebview();
    dispatch(window, { type: "userMessage", text: "q1" });
    dispatch(window, { type: "agentStart" });
    dispatch(window, { type: "messageChunk", text: "answer one" });
    dispatch(window, { type: "promptComplete", meta: {} });
    dispatch(window, { type: "agentEnd" });
    dispatch(window, { type: "userMessage", text: "q2" });
    dispatch(window, { type: "agentStart" });
    dispatch(window, { type: "messageChunk", text: "answer two" });
    dispatch(window, { type: "promptComplete", meta: {} });
    dispatch(window, { type: "agentEnd" });

    expect(doc.querySelectorAll(".msg.agent .msg-actions")).toHaveLength(2);
  });
});

describe("composer autosize", () => {
  it("sets an explicit height on every input change (grow-to-5-lines wiring)", () => {
    // happy-dom has no layout (scrollHeight is 0), so the growth itself can't
    // be measured here — this pins the wiring: typing re-runs autosize and the
    // height is always an explicit px value with overflow managed.
    const { window, doc } = bootWebview();
    const input = $(doc, "input") as HTMLTextAreaElement;
    input.value = "line1\nline2\nline3\nline4\nline5\nline6";
    input.dispatchEvent(new window.Event("input", { bubbles: true }));
    expect(input.style.height).toMatch(/px$/);
    expect(["auto", "hidden"]).toContain(input.style.overflowY);
  });
});

describe("welcome screen visibility (logo/byline hides once real content exists)", () => {
  it("hides the welcome block on the first live user message", () => {
    const { window, doc } = bootWebview();
    expect(($(doc, "welcome") as any).hidden).toBe(false);

    dispatch(window, { type: "userMessage", text: "hello grok" });

    expect(($(doc, "welcome") as any).hidden).toBe(true);
  });

  it("hides the welcome when a restored session replays real user content", () => {
    const { window, doc } = bootWebview();
    dispatch(window, { type: "historyReplay", active: true });
    dispatch(window, { type: "userMessageChunk", text: "a real question" });
    dispatch(window, { type: "messageChunk", text: "an answer" });
    dispatch(window, { type: "historyReplay", active: false });

    expect(($(doc, "welcome") as any).hidden).toBe(true);
  });

  it("keeps the welcome on a primer-only restore — the primer is not user content", () => {
    const { window, doc } = bootWebview();
    dispatch(window, { type: "historyReplay", active: true });
    dispatch(window, { type: "userMessageChunk", text: "[grok-build-vscode primer v4] Plan-mode protocol instructions." });
    dispatch(window, { type: "messageChunk", text: "ok" });
    dispatch(window, { type: "historyReplay", active: false });

    expect(($(doc, "welcome") as any).hidden).toBe(false);
  });
});
