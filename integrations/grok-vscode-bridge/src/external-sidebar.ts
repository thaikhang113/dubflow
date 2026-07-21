import * as vscode from "vscode";

import { ExternalBrokerClient, type BrokerEvent, type BrokerSession } from "./external-broker";

type ExternalMessage =
  | { type: "ready" }
  | { type: "attach"; sessionId: string }
  | { type: "send"; message: string }
  | { type: "permission"; requestId: string; decision: "approve" | "reject" }
  | { type: "cancel" }
  | { type: "diff" }
  | { type: "refresh" };

export class ExternalGrokSidebar implements vscode.WebviewViewProvider {
  static readonly viewId = "grok.chat";
  private view?: vscode.WebviewView;
  private client?: ExternalBrokerClient;
  private sessionId?: string;
  private cursor = 0;
  private generation = 0;
  private readonly steering: boolean;

  constructor(private context: vscode.ExtensionContext, private output: vscode.OutputChannel) {
    this.steering = vscode.workspace.getConfiguration("grok").get<boolean>("externalSteeringEnabled", false);
    try { this.client = new ExternalBrokerClient(); }
    catch (error) { this.output.appendLine(`[external] ${(error as Error).message}`); }
  }

  resolveWebviewView(view: vscode.WebviewView): void {
    this.view = view;
    view.webview.options = {
      enableScripts: true,
      localResourceRoots: [vscode.Uri.joinPath(this.context.extensionUri, "media")],
    };
    view.webview.onDidReceiveMessage((message: ExternalMessage) => { void this.onMessage(message); });
    view.webview.html = this.html(view.webview);
  }

  newSession(): void { void this.refreshSessions(); }
  async pickModel(): Promise<void> { await vscode.window.showInformationMessage("External sessions use the model selected by the broker-owned Grok process."); }
  openModePopover(): void { void vscode.window.showInformationMessage("External mode has no independent auto-approve mode. Permissions are decided by the broker."); }
  insertActiveMention(): void { void vscode.window.showInformationMessage("Send revisions through the external session composer; broker worktree paths remain isolated."); }
  setAllToolDetails(): void { /* compact external cards are always auditable */ }
  async logout(): Promise<void> { await vscode.window.showInformationMessage("Switch grok.connectionMode to internal to manage Grok CLI login."); }
  debugShowDummyPlan(): void { /* internal-only debug command */ }
  dispose(): void { this.generation++; }

  private async onMessage(message: ExternalMessage): Promise<void> {
    try {
      if (message.type === "ready" || message.type === "refresh") await this.refreshSessions();
      else if (message.type === "attach") await this.attach(message.sessionId);
      else if (message.type === "diff") await this.showDiff();
      else if (message.type === "send") {
        this.assertSteering();
        await this.clientOrThrow().request("grok_session_send", { session_id: this.sessionOrThrow(), message: message.message, kind: "revision" });
      } else if (message.type === "permission") {
        this.assertSteering();
        await this.clientOrThrow().request("grok_session_approve", { session_id: this.sessionOrThrow(), request_id: message.requestId, decision: message.decision });
      } else if (message.type === "cancel") {
        this.assertSteering();
        await this.clientOrThrow().request("grok_session_cancel", { session_id: this.sessionOrThrow() });
      }
    } catch (error) {
      this.output.appendLine(`[external] ${(error as Error).message}`);
      this.post({ type: "error", message: (error as Error).message });
    }
  }

  private async refreshSessions(): Promise<void> {
    const sessions = await this.clientOrThrow().request<BrokerSession[]>("grok_session_list");
    this.post({ type: "sessions", sessions, steering: this.steering, active: this.sessionId });
  }

  private async attach(sessionId: string): Promise<void> {
    this.sessionId = sessionId;
    this.cursor = 0;
    const generation = ++this.generation;
    this.post({ type: "attached", sessionId, steering: this.steering });
    void this.watch(generation);
  }

  private async watch(generation: number): Promise<void> {
    while (generation === this.generation && this.sessionId) {
      try {
        const batch = await this.clientOrThrow().request<{ events: BrokerEvent[]; cursor: number }>("grok_session_watch", { session_id: this.sessionId, cursor: this.cursor, timeout_ms: 30_000 });
        if (generation !== this.generation) return;
        this.cursor = Math.max(this.cursor, batch.cursor);
        if (batch.events.length) this.post({ type: "events", events: batch.events });
      } catch (error) {
        if (generation !== this.generation) return;
        this.post({ type: "connection", connected: false, message: (error as Error).message });
        await new Promise((resolve) => setTimeout(resolve, 1_000));
      }
    }
  }

  private async showDiff(): Promise<void> {
    const diff = await this.clientOrThrow().request<{ diff: string; stat: string; files: string[]; truncated: boolean }>("grok_session_diff", { session_id: this.sessionOrThrow() });
    this.post({ type: "diff", diff });
  }

  private assertSteering(): void { if (!this.steering) throw new Error("External steering is monitor-only; enable grok.externalSteeringEnabled after the live gate passes"); }
  private clientOrThrow(): ExternalBrokerClient { if (!this.client) throw new Error("External broker paths are unavailable"); return this.client; }
  private sessionOrThrow(): string { if (!this.sessionId) throw new Error("Attach a broker session first"); return this.sessionId; }
  private post(message: unknown): void { void this.view?.webview.postMessage(message); }

  private html(webview: vscode.Webview): string {
    const scriptUri = webview.asWebviewUri(
      vscode.Uri.joinPath(this.context.extensionUri, "media", "external-sidebar.js"),
    );
    return `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${webview.cspSource} 'unsafe-inline'; script-src ${webview.cspSource}"><meta name="viewport" content="width=device-width,initial-scale=1"><style>
body{font:13px var(--vscode-font-family);color:var(--vscode-foreground);background:var(--vscode-sideBar-background);margin:0;padding:10px}button,select,textarea{font:inherit;color:inherit;background:var(--vscode-input-background);border:1px solid var(--vscode-input-border);border-radius:4px;padding:6px}button{cursor:pointer}.bar{display:flex;gap:6px;margin-bottom:8px}.bar select{min-width:0;flex:1}.status{color:var(--vscode-descriptionForeground);font-size:12px;margin:6px 0}.events{display:flex;flex-direction:column;gap:6px;max-height:55vh;overflow:auto}.event{border:1px solid var(--vscode-panel-border);border-radius:6px;padding:7px}.event .kind{font-size:11px;color:var(--vscode-descriptionForeground)}.error{color:var(--vscode-errorForeground)}.permission{border-color:var(--vscode-charts-yellow)}textarea{box-sizing:border-box;width:100%;min-height:70px;margin-top:8px}.actions{display:flex;gap:6px;margin-top:6px}pre{white-space:pre-wrap;overflow:auto;max-height:55vh}.hidden{display:none}
</style></head><body><div class="bar"><select id="sessions"><option value="">Select a broker session…</option></select><button id="refresh">↻</button></div><div id="status" class="status">Connecting to the local broker…</div><div id="events" class="events"></div><textarea id="composer" placeholder="Send a revision or clarification"></textarea><div class="actions"><button id="send">Send revision</button><button id="diff">Diff</button><button id="cancel">Cancel</button></div><pre id="diffout" class="hidden"></pre>
<script src="${scriptUri}"></script></body></html>`;
  }
}
