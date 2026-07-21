// DOM test for #43 — after Send Selection / Send File / @-mention, the host
// reveals the panel taking focus and posts `focusInput`; the webview lands the
// caret in the composer so the user can type a prompt immediately.
import { describe, it, expect } from "vitest";
import { bootWebview, dispatch } from "./webview-harness";

describe("focusInput (#43)", () => {
  it("moves keyboard focus to the composer input", () => {
    const { window, doc } = bootWebview();
    const input = doc.getElementById("input") as HTMLElement;

    // Move focus off the composer first (chat.js focuses the input at boot), so
    // the assertion proves the message did the work, not the boot-time focus.
    const historyBtn = doc.getElementById("history-btn") as HTMLElement;
    historyBtn.focus();
    expect(doc.activeElement).toBe(historyBtn);

    dispatch(window, { type: "focusInput" });
    expect(doc.activeElement).toBe(input);
  });
});
