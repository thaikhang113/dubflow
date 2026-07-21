(() => {
  "use strict";

  const vscode = acquireVsCodeApi();
  const sessions = document.getElementById("sessions");
  const events = document.getElementById("events");
  const status = document.getElementById("status");
  const composer = document.getElementById("composer");
  const diffout = document.getElementById("diffout");
  let steering = false;

  const post = (type, extra = {}) => vscode.postMessage({ type, ...extra });

  sessions.onchange = () => sessions.value && post("attach", { sessionId: sessions.value });
  document.getElementById("refresh").onclick = () => post("refresh");
  document.getElementById("send").onclick = () => {
    if (!composer.value.trim()) return;
    post("send", { message: composer.value });
    composer.value = "";
  };
  document.getElementById("diff").onclick = () => post("diff");
  document.getElementById("cancel").onclick = () => post("cancel");

  window.addEventListener("message", ({ data: message }) => {
    if (message.type === "sessions") {
      steering = message.steering;
      sessions.replaceChildren();
      const placeholder = document.createElement("option");
      placeholder.value = "";
      placeholder.textContent = "Select a broker session…";
      sessions.add(placeholder);
      for (const session of message.sessions) {
        const option = document.createElement("option");
        option.value = session.sessionId;
        option.textContent = `${session.task || session.sessionId} · ${session.state}`;
        sessions.add(option);
      }
      if (message.active) sessions.value = message.active;
      status.textContent = steering ? "External broker · steering enabled" : "External broker · monitor-only";
      return;
    }
    if (message.type === "attached") {
      events.replaceChildren();
      status.textContent = `Attached ${message.sessionId}${message.steering ? "" : " · monitor-only"}`;
      return;
    }
    if (message.type === "events") {
      for (const event of message.events) {
        const card = document.createElement("div");
        card.className = `event ${event.type === "error" ? "error " : ""}${event.type === "permission_requested" ? "permission" : ""}`;
        const kind = document.createElement("div");
        kind.className = "kind";
        kind.textContent = `${event.type} · #${event.event_id}`;
        const text = document.createElement("div");
        text.textContent = event.summary;
        card.append(kind, text);
        if (event.type === "permission_requested" && event.metadata.request_id && event.metadata.decision === "required") {
          for (const decision of ["approve", "reject"]) {
            const button = document.createElement("button");
            button.textContent = decision;
            button.disabled = !steering;
            button.onclick = () => post("permission", {
              requestId: String(event.metadata.request_id),
              decision,
            });
            card.append(button);
          }
        }
        events.append(card);
      }
      events.scrollTop = events.scrollHeight;
      return;
    }
    if (message.type === "diff") {
      diffout.classList.remove("hidden");
      diffout.textContent = `${message.diff.stat || ""}\n${message.diff.files.join("\n")}\n\n${message.diff.diff}`;
      return;
    }
    if (message.type === "error") {
      status.textContent = message.message;
      status.className = "status error";
      return;
    }
    if (message.type === "connection") status.textContent = message.message;
  });

  post("ready");
})();
