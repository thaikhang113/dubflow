import * as vscode from "vscode";
import { ExternalGrokSidebar } from "./external-sidebar";
import { GrokSidebar } from "./sidebar";

export function activate(context: vscode.ExtensionContext): void {
  const output = vscode.window.createOutputChannel("Grok");
  const connectionMode = vscode.workspace.getConfiguration("grok").get<"internal" | "external">("connectionMode", "internal");
  const sidebar = connectionMode === "external"
    ? new ExternalGrokSidebar(context, output)
    : new GrokSidebar(context, output);

  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider(GrokSidebar.viewId, sidebar, {
      webviewOptions: { retainContextWhenHidden: true },
    }),
    output,
    { dispose: () => sidebar.dispose() },
    vscode.commands.registerCommand("grok.open", () =>
      vscode.commands.executeCommand("workbench.view.extension.grokSidebar"),
    ),
    vscode.commands.registerCommand("grok.newSession", () => sidebar.newSession()),
    vscode.commands.registerCommand("grok.compact", () => {
      // emulated by sending the slash command as a prompt; CLI handles it
      vscode.window.showInformationMessage(
        "Type /compact in the composer to compress the conversation.",
      );
    }),
    vscode.commands.registerCommand("grok.pickModel", () => sidebar.pickModel()),
    vscode.commands.registerCommand("grok.toggleMode", () => sidebar.openModePopover()),
    vscode.commands.registerCommand("grok.sendSelection", () =>
      sidebar.insertActiveMention({ selection: true }),
    ),
    vscode.commands.registerCommand(
      "grok.sendFile",
      (uri?: vscode.Uri) => sidebar.insertActiveMention({ uri, pickIfMissing: true }),
    ),
    vscode.commands.registerCommand("grok.insertAtMention", () =>
      sidebar.insertActiveMention(),
    ),
    vscode.commands.registerCommand("grok.showLogs", () => output.show()),
    vscode.commands.registerCommand("grok.expandAllToolDetails", () => sidebar.setAllToolDetails(true)),
    vscode.commands.registerCommand("grok.collapseAllToolDetails", () => sidebar.setAllToolDetails(false)),
    vscode.commands.registerCommand("grok.logout", () => sidebar.logout()),
    // Internal debug helper for manually exercising the plan-review card UI
    // (Approve / Reject / Cancel flows) without a live CLI session.
    vscode.commands.registerCommand("grok._debugDummyPlan", () => sidebar.debugShowDummyPlan()),
  );
}

export function deactivate(): void {
  // disposables handle cleanup
}
