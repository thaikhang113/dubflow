const state = {
  jobs: [],
  providers: [],
  selectedJobId: "",
  queuePaused: false,
};

const artifacts = [
  "final_video_vi.mp4",
  "vietnamese.srt",
  "dub.srt",
  "thumbnail.jpg",
  "voice_sync_quality_report.json",
  "final_mix_quality_report.json",
  "bilibili_branding_proof.json",
];

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

function notify(message, error = false) {
  const notice = document.querySelector("#notice");
  notice.textContent = message;
  notice.classList.toggle("error", error);
  notice.hidden = false;
  window.clearTimeout(notify.timer);
  notify.timer = window.setTimeout(() => {
    notice.hidden = true;
  }, 5000);
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) {
    let message = `HTTP ${response.status}`;
    try {
      const payload = await response.json();
      message = payload.detail || message;
    } catch {
      // Response body is not JSON.
    }
    throw new Error(message);
  }
  if (response.status === 204) return null;
  return response.json();
}

function formatTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleString("vi-VN");
}

function statusLabel(value) {
  return {
    queued: "Đang chờ",
    running: "Đang chạy",
    paused: "Tạm dừng",
    needs_attention: "Cần xử lý",
    failed: "Thất bại",
    cancelled: "Đã hủy",
    completed: "Hoàn thành",
  }[value] || value;
}

function button(label, className, handler) {
  const node = element("button", className, label);
  node.type = "button";
  node.addEventListener("click", handler);
  return node;
}

function showView(name) {
  document.querySelectorAll(".view").forEach((view) => {
    const active = view.dataset.view === name;
    view.hidden = !active;
    view.classList.toggle("active", active);
  });
  document.querySelectorAll(".nav-item[data-target]").forEach((item) => {
    item.classList.toggle("active", item.dataset.target === name);
  });
  const providers = name === "providers";
  document.querySelector("#view-eyebrow").textContent = providers ? "Cấu hình" : "Queue";
  document.querySelector("#view-title").textContent = providers ? "Providers" : "Jobs";
  document.querySelector("#queue-pause").hidden = providers;
  document.querySelector("#focus-new-job").hidden = providers;
}

function providerOptions(select, providers, emptyLabel) {
  const previous = select.value;
  clear(select);
  const empty = element("option", "", emptyLabel);
  empty.value = "";
  select.append(empty);
  providers.forEach((provider) => {
    const option = element(
      "option",
      "",
      `${provider.name} · ${provider.model || provider.kind}`,
    );
    option.value = provider.id;
    select.append(option);
  });
  if ([...select.options].some((option) => option.value === previous)) {
    select.value = previous;
  }
}

function renderProviders() {
  const list = document.querySelector("#provider-list");
  clear(list);
  document.querySelector("#provider-summary").textContent =
    `${state.providers.length} provider đã cấu hình.`;
  providerOptions(
    document.querySelector("#job-translation-provider"),
    state.providers.filter((provider) => provider.kind !== "ai33"),
    "Ollama mặc định",
  );
  providerOptions(
    document.querySelector("#job-tts-provider"),
    state.providers.filter((provider) => provider.kind === "ai33"),
    "Theo cấu hình pipeline",
  );

  if (!state.providers.length) {
    list.append(element("p", "empty-inline", "Chưa có provider. Ollama mặc định vẫn dùng được."));
    return;
  }
  state.providers.forEach((provider) => {
    const row = element("article", "provider-row");
    const body = element("div", "provider-main");
    body.append(element("strong", "", provider.name));
    body.append(element("span", "muted", provider.endpoint));
    body.append(element(
      "span",
      "provider-meta",
      `${provider.kind} · ${provider.model || "không đặt model"} · ${provider.configured ? "đã có key" : "không có key"}`,
    ));
    const actions = element("div", "row-actions");
    actions.append(button("Sửa", "text-button", () => editProvider(provider)));
    actions.append(button("Kiểm tra", "text-button", () => testProvider(provider.id)));
    actions.append(button("Xóa", "text-button danger", () => deleteProvider(provider.id)));
    row.append(body, actions);
    list.append(row);
  });
}

function editProvider(provider) {
  showView("providers");
  document.querySelector("#provider-id").value = provider.id;
  document.querySelector("#provider-name").value = provider.name;
  document.querySelector("#provider-kind").value = provider.kind;
  document.querySelector("#provider-endpoint").value = provider.endpoint;
  document.querySelector("#provider-model").value = provider.model || "";
  document.querySelector("#provider-timeout").value = provider.timeout_seconds;
  document.querySelector("#provider-key").value = "";
  document.querySelector("#provider-form-title").textContent = "Sửa provider";
  document.querySelector("#provider-reset").hidden = false;
  document.querySelector("#provider-name").focus();
}

function resetProviderForm() {
  const form = document.querySelector("#provider-form");
  form.reset();
  document.querySelector("#provider-id").value = "";
  document.querySelector("#provider-timeout").value = "90";
  document.querySelector("#provider-form-title").textContent = "Thêm provider";
  document.querySelector("#provider-reset").hidden = true;
}

async function loadProviders() {
  try {
    state.providers = await api("/api/providers");
    renderProviders();
  } catch (error) {
    notify(`Không tải được providers: ${error.message}`, true);
  }
}

async function saveProvider(event) {
  event.preventDefault();
  const id = document.querySelector("#provider-id").value;
  const payload = {
    name: document.querySelector("#provider-name").value,
    kind: document.querySelector("#provider-kind").value,
    endpoint: document.querySelector("#provider-endpoint").value,
    model: document.querySelector("#provider-model").value,
    timeout_seconds: Number(document.querySelector("#provider-timeout").value),
    api_key: document.querySelector("#provider-key").value,
  };
  try {
    await api(id ? `/api/providers/${id}` : "/api/providers", {
      method: id ? "PUT" : "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(payload),
    });
    document.querySelector("#provider-key").value = "";
    resetProviderForm();
    await loadProviders();
    notify("Đã lưu provider.");
  } catch (error) {
    notify(`Không lưu được provider: ${error.message}`, true);
  }
}

async function testProvider(id) {
  try {
    const result = await api(`/api/providers/${id}/test`, {method: "POST"});
    notify(result.message, !result.ok);
  } catch (error) {
    notify(`Kiểm tra thất bại: ${error.message}`, true);
  }
}

async function deleteProvider(id) {
  if (!window.confirm("Xóa provider này? Key lưu kèm cũng sẽ bị xóa.")) return;
  try {
    await api(`/api/providers/${id}`, {method: "DELETE"});
    await loadProviders();
    notify("Đã xóa provider.");
  } catch (error) {
    notify(`Không xóa được provider: ${error.message}`, true);
  }
}

function jobAction(job, label, action) {
  return button(label, "text-button", async () => {
    try {
      const updated = await api(`/api/jobs/${job.id}/${action}`, {method: "POST"});
      upsertJob(updated);
      renderJobs();
      selectJob(updated.id);
    } catch (error) {
      notify(`${label} thất bại: ${error.message}`, true);
    }
  });
}

function renderJobs() {
  const list = document.querySelector("#job-list");
  clear(list);
  const running = state.jobs.filter((job) => job.state === "running").length;
  const queued = state.jobs.filter((job) => job.state === "queued").length;
  document.querySelector("#queue-summary").textContent =
    `${running} đang chạy · ${queued} đang chờ · ${state.jobs.length} tổng cộng.`;
  if (!state.jobs.length) {
    list.append(element("p", "empty-inline", "Chưa có job."));
    renderJobDetail(null);
    return;
  }
  state.jobs.forEach((job) => {
    const row = element("article", "job-row");
    row.tabIndex = 0;
    row.classList.toggle("selected", job.id === state.selectedJobId);
    row.addEventListener("click", () => selectJob(job.id));
    row.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") selectJob(job.id);
    });

    const main = element("div", "job-main");
    const source = element("strong", "job-source", job.source);
    source.title = job.source;
    const metadata = element(
      "span",
      "muted",
      `${job.platform} · ${formatTime(job.created_at)}`,
    );
    main.append(source, metadata);

    const progress = element("div", "progress-track");
    const progressValue = element("span", "progress-value");
    progressValue.style.width = `${Math.max(0, Math.min(100, job.progress || 0))}%`;
    progress.append(progressValue);

    const status = element("div", "job-status");
    status.append(element("span", `status status-${job.state}`, statusLabel(job.state)));
    status.append(element("span", "progress-label", `${job.progress || 0}%`));

    const actions = element("div", "row-actions");
    if (["queued", "running", "needs_attention"].includes(job.state)) {
      actions.append(jobAction(job, "Hủy", "cancel"));
    }
    if (["needs_attention", "failed", "cancelled"].includes(job.state) && job.job_dir) {
      actions.append(jobAction(job, "Tiếp tục", "resume"));
    }
    if (["needs_attention", "failed", "cancelled", "completed"].includes(job.state)) {
      actions.append(jobAction(job, "Chạy lại", "retry"));
    }

    row.append(main, progress, status, actions);
    list.append(row);
  });
}

function renderJobDetail(job) {
  const detail = document.querySelector("#job-detail");
  clear(detail);
  document.querySelector("#detail-subtitle").textContent =
    job ? job.id : "Chọn một job để xem.";
  if (!job) {
    detail.append(element("p", "muted", "Chưa chọn job."));
    return;
  }
  const facts = element("dl", "facts");
  [
    ["Trạng thái", statusLabel(job.state)],
    ["Tiến độ", `${job.progress || 0}%`],
    ["Cập nhật", formatTime(job.updated_at)],
    ["Mã lỗi", job.error_code || "—"],
  ].forEach(([label, value]) => {
    facts.append(element("dt", "", label), element("dd", "", value));
  });
  detail.append(facts);
  if (job.message) {
    detail.append(element("h3", "", "Thông báo"));
    detail.append(element("p", "error-message", job.message));
  }
  if (job.state === "completed" || job.job_dir) {
    detail.append(element("h3", "", "Artifacts"));
    const links = element("div", "artifact-list");
    artifacts.forEach((name) => {
      const link = element("a", "artifact-link", name);
      link.href = `/api/jobs/${encodeURIComponent(job.id)}/artifacts/${encodeURIComponent(name)}`;
      link.target = "_blank";
      link.rel = "noopener";
      links.append(link);
    });
    detail.append(links);
  }
}

function selectJob(id) {
  state.selectedJobId = id;
  renderJobs();
  renderJobDetail(state.jobs.find((job) => job.id === id) || null);
}

function upsertJob(job) {
  const index = state.jobs.findIndex((item) => item.id === job.id);
  if (index === -1) state.jobs.unshift(job);
  else state.jobs[index] = job;
}

async function loadJobs() {
  try {
    state.jobs = await api("/api/jobs");
    if (!state.selectedJobId && state.jobs.length) state.selectedJobId = state.jobs[0].id;
    renderJobs();
    renderJobDetail(state.jobs.find((job) => job.id === state.selectedJobId) || null);
  } catch (error) {
    notify(`Không tải được jobs: ${error.message}`, true);
  }
}

async function createJob(event) {
  event.preventDefault();
  const file = document.querySelector("#job-file").files[0];
  let platform = document.querySelector("#job-platform").value;
  let source = document.querySelector("#job-source").value.trim();
  try {
    if (file) {
      const data = new FormData();
      data.append("file", file);
      const upload = await api("/api/uploads", {method: "POST", body: data});
      platform = "upload";
      source = upload.source;
    }
    const job = await api("/api/jobs", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        platform,
        source,
        translation_provider_id: document.querySelector("#job-translation-provider").value,
        tts_provider_id: document.querySelector("#job-tts-provider").value,
        voice: document.querySelector("#job-voice").value.trim(),
        preset: document.querySelector("#job-preset").value,
      }),
    });
    document.querySelector("#job-source").value = "";
    document.querySelector("#job-file").value = "";
    upsertJob(job);
    selectJob(job.id);
    notify("Đã đưa video vào queue.");
  } catch (error) {
    notify(`Không tạo được job: ${error.message}`, true);
  }
}

async function toggleQueue() {
  try {
    state.queuePaused = !state.queuePaused;
    await api(`/api/queue/${state.queuePaused ? "pause" : "resume"}`, {method: "POST"});
    document.querySelector("#queue-pause").textContent =
      state.queuePaused ? "Chạy tiếp queue" : "Tạm dừng queue";
  } catch (error) {
    state.queuePaused = !state.queuePaused;
    notify(`Không đổi được queue: ${error.message}`, true);
  }
}

async function checkHealth() {
  const label = document.querySelector("#runtime-label");
  try {
    await api("/api/health");
    label.textContent = "Runtime sẵn sàng";
  } catch {
    label.textContent = "Runtime lỗi";
    document.querySelector(".runtime-status").classList.add("error");
  }
}

function connectEvents() {
  const events = new EventSource("/api/events");
  events.addEventListener("job", (event) => {
    try {
      const job = JSON.parse(event.data);
      upsertJob(job);
      renderJobs();
      if (state.selectedJobId === job.id) renderJobDetail(job);
    } catch {
      // Polling remains active as fallback.
    }
  });
  events.onerror = () => {
    events.close();
    window.setTimeout(connectEvents, 5000);
  };
}

document.querySelectorAll(".nav-item[data-target]").forEach((item) => {
  item.addEventListener("click", () => showView(item.dataset.target));
});
document.querySelector("#new-job-form").addEventListener("submit", createJob);
document.querySelector("#provider-form").addEventListener("submit", saveProvider);
document.querySelector("#provider-reset").addEventListener("click", resetProviderForm);
document.querySelector("#refresh-jobs").addEventListener("click", loadJobs);
document.querySelector("#refresh-providers").addEventListener("click", loadProviders);
document.querySelector("#queue-pause").addEventListener("click", toggleQueue);
document.querySelector("#focus-new-job").addEventListener("click", () => {
  showView("jobs");
  document.querySelector("#job-source").focus();
});
document.querySelector("#job-file").addEventListener("change", (event) => {
  document.querySelector("#job-source").required = !event.target.files.length;
});

const initialView = new URLSearchParams(window.location.search).get("view");
if (initialView === "providers") showView("providers");
checkHealth();
loadProviders();
loadJobs();
connectEvents();
window.setInterval(loadJobs, 10000);
