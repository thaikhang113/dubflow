import { Window } from "happy-dom";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const script = readFileSync(
  fileURLToPath(new URL("../media/external-sidebar.js", import.meta.url)),
  "utf8",
);

function boot(): { window: Window; document: Document; posted: unknown[] } {
  const window = new Window({ url: "https://localhost/" });
  const posted: unknown[] = [];
  (window as any).acquireVsCodeApi = () => ({ postMessage: (message: unknown) => posted.push(message) });
  const document = (window as any).document as Document;
  document.body.innerHTML = `
    <select id="sessions"><option value="">Select a broker session…</option></select>
    <button id="refresh">refresh</button>
    <div id="status">Connecting to the local broker…</div>
    <div id="events"></div>
    <textarea id="composer"></textarea>
    <button id="send">Send revision</button>
    <button id="diff">Diff</button>
    <button id="cancel">Cancel</button>
    <pre id="diffout" class="hidden"></pre>`;
  (window as any).eval(script);
  return { window, document, posted };
}

describe("external broker webview", () => {
  it("announces readiness and refreshes through the VS Code bridge", () => {
    const { window, document, posted } = boot();
    expect(posted).toEqual([{ type: "ready" }]);

    document.getElementById("refresh")!.dispatchEvent(new (window as any).MouseEvent("click"));
    expect(posted).toEqual([{ type: "ready" }, { type: "refresh" }]);
  });

  it("renders broker sessions returned by the extension host", () => {
    const { window, document } = boot();
    window.dispatchEvent(new (window as any).MessageEvent("message", {
      data: {
        type: "sessions",
        steering: false,
        sessions: [{ sessionId: "session-1", task: "Douyin plan", state: "idle" }],
      },
    }));

    expect(document.querySelectorAll("#sessions option")).toHaveLength(2);
    expect(document.getElementById("status")!.textContent).toBe("External broker · monitor-only");
  });
});
