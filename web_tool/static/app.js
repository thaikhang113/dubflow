const state = {
  jobs: [],
  providers: [],
  channels: [],
  series: [],
  settings: null,
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
  const headings = {
    jobs: ["Queue", "Jobs"],
    providers: ["Cấu hình", "Providers"],
    "bilibili-login": ["Tài khoản", "Bilibili Login"],
    channels: ["Tự động", "Channels"],
    series: ["Nội dung", "Series"],
    trend: ["Khám phá", "Trend"],
    settings: ["Hệ thống", "Settings"],
  };
  const heading = headings[name] || headings.jobs;
  document.querySelector("#view-eyebrow").textContent = heading[0];
  document.querySelector("#view-title").textContent = heading[1];
  document.querySelector("#queue-pause").hidden = name !== "jobs";
  document.querySelector("#focus-new-job").hidden = name !== "jobs";
  if (name === "bilibili-login") loadBilibiliStatus();
  if (name === "channels") loadChannels();
  if (name === "series") loadSeries();
  if (name === "settings") {
    loadSettings();
    loadDoctor();
    loadBrandLogo();
    loadInstallStatus();
  }
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

function selectFirstProvider(select) {
  if (!select.value && select.options.length > 1) select.selectedIndex = 1;
}

function setSelectValue(select, value) {
  if (value && ![...select.options].some((option) => option.value === value)) {
    const option = element("option", "", value);
    option.value = value;
    select.append(option);
  }
  select.value = value || "";
}

function renderProviders() {
  const list = document.querySelector("#provider-list");
  clear(list);
  document.querySelector("#provider-summary").textContent =
    `${state.providers.length} provider đã cấu hình.`;
  const translationSelect = document.querySelector("#job-translation-provider");
  providerOptions(
    translationSelect,
    state.providers.filter((provider) => provider.kind !== "ai33"),
    "Ollama mặc định",
  );
  selectFirstProvider(translationSelect);
  providerOptions(
    document.querySelector("#channel-provider"),
    state.providers,
    "Pipeline mặc định",
  );
  providerOptions(
    document.querySelector("#settings-provider"),
    state.providers,
    "Pipeline mặc định",
  );
  if (state.settings?.default_provider_id) {
    document.querySelector("#settings-provider").value =
      state.settings.default_provider_id;
  }
  const ttsSelect = document.querySelector("#job-tts-provider");
  providerOptions(
    ttsSelect,
    state.providers.filter((provider) => provider.kind === "ai33"),
    "Theo cấu hình pipeline",
  );
  if (document.querySelector("#job-voice").value.startsWith("ai33:")) {
    selectFirstProvider(ttsSelect);
  }

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

async function installLocalOllama() {
  const installButton = document.querySelector("#provider-install-ollama");
  const originalLabel = installButton.textContent;
  installButton.disabled = true;
  installButton.textContent = "Đang cài Ollama và tải model...";
  try {
    const response = await fetch("http://127.0.0.1:18794/ollama/install", {
      method: "POST",
    });
    const result = await response.json();
    if (!response.ok || !result.ok) {
      throw new Error(result.error_code || `HTTP ${response.status}`);
    }
    let provider = state.providers.find(
      (item) => item.kind === "ollama"
        && item.endpoint.replace(/\/+$/, "") === "http://ollama:11434",
    );
    if (!provider) {
      provider = await api("/api/providers", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          name: "Ollama local",
          kind: "ollama",
          endpoint: "http://ollama:11434",
          model: "translategemma:4b",
          timeout_seconds: 180,
          api_key: "",
        }),
      });
    }
    const settings = state.settings || await api("/api/settings");
    await api("/api/settings", {
      method: "PUT",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        default_provider_id: provider.id,
        default_model: "translategemma:4b",
        default_voice: settings.default_voice || "",
        vieneu_style: settings.vieneu_style || "story",
        asr_engine: settings.asr_engine || "auto",
        whisper_model: settings.whisper_model || "medium",
        hardware_mode: settings.hardware_mode || "auto",
        hardware_profile: settings.hardware_profile || "cpu",
        queue_poll_seconds: settings.queue_poll_seconds || 2,
        telegram_chat_id: settings.telegram_chat_id || "",
        telegram_thread_id: settings.telegram_thread_id || "",
        telegram_bot_token: "",
      }),
    });
    await loadProviders();
    await loadSettings();
    await loadDoctor();
    notify("Ollama local và model TranslateGemma 4B đã sẵn sàng.");
  } catch (error) {
    notify(
      `Không cài được Ollama: ${error.message}. Hãy mở Docker Desktop và chạy host helper.`,
      true,
    );
  } finally {
    installButton.disabled = false;
    installButton.textContent = originalLabel;
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
        asr_engine: document.querySelector("#job-asr-engine").value,
        whisper_model: document.querySelector("#job-whisper-model").value,
        vieneu_style: document.querySelector("#job-vieneu-style").value,
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

function loginStateLabel(stateName) {
  return {
    logged_out: "Chưa đăng nhập",
    connecting: "Đang kết nối Chromium",
    waiting_scan: "Đang chờ quét QR",
    logged_in: "Đã đăng nhập",
    needs_attention: "Cần xử lý",
  }[stateName] || stateName;
}

function renderBilibiliStatus(status) {
  document.querySelector("#bilibili-login-state").textContent =
    loginStateLabel(status.state);
  const details = [
    `${status.cookie_count || 0} cookie`,
    status.error_code || "",
    status.last_checked ? formatTime(status.last_checked) : "",
  ].filter(Boolean);
  document.querySelector("#bilibili-login-meta").textContent = details.join(" · ");
  const qr = document.querySelector("#bilibili-login-qr");
  qr.hidden = !status.qr_available;
  if (status.qr_available) {
    qr.src = `/api/bilibili/login/qr?t=${Date.now()}`;
  } else {
    qr.removeAttribute("src");
  }
}

async function loadBilibiliStatus() {
  try {
    renderBilibiliStatus(await api("/api/bilibili/login/status"));
  } catch (error) {
    notify(`Không đọc được trạng thái Bilibili: ${error.message}`, true);
  }
}

async function startBilibiliLogin() {
  try {
    renderBilibiliStatus(
      await api("/api/bilibili/login/start", {method: "POST"}),
    );
    notify("Đang mở trang đăng nhập Bilibili.");
  } catch (error) {
    notify(`Không tạo được QR: ${error.message}`, true);
  }
}

async function openHostBilibiliLogin() {
  try {
    const response = await fetch("http://127.0.0.1:18794/open", {
      method: "POST",
    });
    const result = await response.json();
    if (!response.ok || !result.ok) {
      throw new Error(result.message || result.error_code || `HTTP ${response.status}`);
    }
    notify("Chrome đã mở. Đăng nhập Bilibili, cookie sẽ tự đồng bộ.");
  } catch (error) {
    notify(
      `Host helper chưa chạy: ${error.message}. Chạy script trong tools/bilibili-host-login.`,
      true,
    );
  }
}

async function importBilibiliCookies(event) {
  event.preventDefault();
  const file = document.querySelector("#bilibili-cookie-file").files[0];
  let text = document.querySelector("#bilibili-cookie-text").value;
  if (file) text = await file.text();
  try {
    const status = await api("/api/bilibili/login/cookies", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({text}),
    });
    document.querySelector("#bilibili-cookie-file").value = "";
    document.querySelector("#bilibili-cookie-text").value = "";
    renderBilibiliStatus(status);
    notify("Đã lưu đăng nhập Bilibili.");
  } catch (error) {
    notify(`Cookies không hợp lệ: ${error.message}`, true);
  }
}

async function clearBilibiliLogin() {
  if (!window.confirm("Xóa cookies và profile Bilibili trong tool?")) return;
  try {
    renderBilibiliStatus(
      await api("/api/bilibili/login/cookies", {method: "DELETE"}),
    );
    notify("Đã xóa đăng nhập Bilibili.");
  } catch (error) {
    notify(`Không xóa được đăng nhập: ${error.message}`, true);
  }
}

function renderChannels() {
  const list = document.querySelector("#channel-list");
  clear(list);
  document.querySelector("#channel-summary").textContent =
    `${state.channels.length} kênh · ${state.channels.filter((channel) => channel.enabled).length} đang bật.`;
  if (!state.channels.length) {
    list.append(element("p", "empty-inline", "Chưa có kênh theo dõi."));
    return;
  }
  state.channels.forEach((channel) => {
    const row = element("article", "channel-row");
    const body = element("div", "provider-main");
    body.append(element("strong", "", channel.name));
    body.append(element("span", "muted", channel.url));
    body.append(element(
      "span",
      "provider-meta",
      `${channel.platform} · mỗi ${channel.interval_minutes} phút · ${channel.state}`,
    ));
    body.append(element(
      "span",
      "muted",
      channel.last_result || `Lần tới: ${formatTime(channel.next_check_at)}`,
    ));
    const actions = element("div", "row-actions");
    actions.append(button("Sửa", "text-button", () => editChannel(channel)));
    actions.append(button("Chạy ngay", "text-button", () => channelAction(channel.id, "run")));
    actions.append(button(
      channel.enabled ? "Tắt" : "Bật",
      "text-button",
      () => channelAction(channel.id, channel.enabled ? "disable" : "enable"),
    ));
    actions.append(button("Xóa", "text-button danger", () => deleteChannel(channel.id)));
    row.append(body, actions);
    list.append(row);
  });
}

function editChannel(channel) {
  showView("channels");
  document.querySelector("#channel-id").value = channel.id;
  document.querySelector("#channel-name").value = channel.name;
  document.querySelector("#channel-platform").value = channel.platform;
  document.querySelector("#channel-url").value = channel.url;
  document.querySelector("#channel-interval").value = channel.interval_minutes;
  document.querySelector("#channel-provider").value = channel.provider_id || "";
  document.querySelector("#channel-model").value = channel.model || "";
  document.querySelector("#channel-voice").value = channel.voice || "";
  document.querySelector("#channel-series").value = channel.series_id || "";
  document.querySelector("#channel-preset").value = channel.preset?.mode || "exact_sync";
  document.querySelector("#channel-enabled").checked = channel.enabled;
  document.querySelector("#channel-form-title").textContent = "Sửa kênh";
  document.querySelector("#channel-reset").hidden = false;
}

function resetChannelForm() {
  document.querySelector("#channel-form").reset();
  document.querySelector("#channel-id").value = "";
  document.querySelector("#channel-interval").value = "60";
    document.querySelector("#channel-model").value = "translategemma:4b";
  document.querySelector("#channel-voice").value =
    "ai33:vbee_hn_female_ngochuyen_full_48k-fhg";
  document.querySelector("#channel-enabled").checked = true;
  document.querySelector("#channel-form-title").textContent = "Theo dõi kênh";
  document.querySelector("#channel-reset").hidden = true;
}

async function loadChannels() {
  try {
    state.channels = await api("/api/channels");
    renderChannels();
  } catch (error) {
    notify(`Không tải được kênh: ${error.message}`, true);
  }
}

async function saveChannel(event) {
  event.preventDefault();
  const id = document.querySelector("#channel-id").value;
  const payload = {
    name: document.querySelector("#channel-name").value.trim(),
    platform: document.querySelector("#channel-platform").value,
    url: document.querySelector("#channel-url").value.trim(),
    interval_minutes: Number(document.querySelector("#channel-interval").value),
    enabled: document.querySelector("#channel-enabled").checked,
    provider_id: document.querySelector("#channel-provider").value,
    model: document.querySelector("#channel-model").value.trim(),
    voice: document.querySelector("#channel-voice").value.trim(),
    series_id: document.querySelector("#channel-series").value.trim(),
    preset: {mode: document.querySelector("#channel-preset").value},
  };
  try {
    await api(id ? `/api/channels/${id}` : "/api/channels", {
      method: id ? "PUT" : "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(payload),
    });
    resetChannelForm();
    await loadChannels();
    notify("Đã lưu kênh.");
  } catch (error) {
    notify(`Không lưu được kênh: ${error.message}`, true);
  }
}

async function channelAction(id, action) {
  try {
    await api(`/api/channels/${id}/${action}`, {method: "POST"});
    await loadChannels();
    notify(action === "run" ? "Đã xếp lịch kiểm tra ngay." : "Đã cập nhật kênh.");
  } catch (error) {
    notify(`Không cập nhật được kênh: ${error.message}`, true);
  }
}

async function deleteChannel(id) {
  if (!window.confirm("Xóa kênh theo dõi này?")) return;
  try {
    await api(`/api/channels/${id}`, {method: "DELETE"});
    await loadChannels();
    notify("Đã xóa kênh.");
  } catch (error) {
    notify(`Không xóa được kênh: ${error.message}`, true);
  }
}

function renderJson(selector, payload) {
  document.querySelector(selector).textContent = JSON.stringify(payload, null, 2);
}

function renderSeries(payload) {
  const list = document.querySelector("#series-list");
  clear(list);
  state.series = payload.series || payload.items || [];
  if (!state.series.length) {
    list.append(element("p", "empty-inline", "Chưa có series."));
    return;
  }
  state.series.forEach((series) => {
    const row = element("article", "channel-row");
    const body = element("div", "provider-main");
    body.append(element("strong", "", series.name || series.title || series.series_id));
    body.append(element("span", "muted", series.series_id || "Không có ID"));
    body.append(element(
      "span",
      "provider-meta",
      `${(series.episodes || []).length} tập · ${series.keyword || ""}`,
    ));
    const actions = element("div", "row-actions");
    actions.append(button("Cập nhật", "text-button", () => seriesQuickAction("update", series.series_id)));
    actions.append(button("Plan", "text-button", () => {
      document.querySelector("#series-action-id").value = series.series_id || "";
      runSeriesAction("plan");
    }));
    actions.append(button("Xóa", "text-button danger", () => removeSeries(series.series_id)));
    row.append(body, actions);
    list.append(row);
  });
}

async function loadSeries() {
  try {
    renderSeries(await api("/api/series/list"));
  } catch (error) {
    notify(`Không tải được series: ${error.message}`, true);
  }
}

async function addSeries(event) {
  event.preventDefault();
  try {
    await api("/api/series/add", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({payload: {
        name: document.querySelector("#series-name").value.trim(),
        keyword: document.querySelector("#series-keyword").value.trim(),
        source_url: document.querySelector("#series-source-url").value.trim(),
        channel_url: document.querySelector("#series-channel-url").value.trim(),
        series_id: document.querySelector("#series-id-new").value.trim(),
      }}),
    });
    document.querySelector("#series-form").reset();
    await loadSeries();
    notify("Đã thêm series.");
  } catch (error) {
    notify(`Không thêm được series: ${error.message}`, true);
  }
}

async function seriesQuickAction(action, seriesId) {
  try {
    const result = await api(`/api/series/${action}`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({payload: {series_id: seriesId}}),
    });
    renderJson("#series-result", result);
    await loadSeries();
  } catch (error) {
    notify(`Series ${action} lỗi: ${error.message}`, true);
  }
}

async function removeSeries(seriesId) {
  if (!window.confirm("Xóa series này?")) return;
  await seriesQuickAction("remove", seriesId);
}

async function runSeriesAction(action) {
  const payload = {
    series_id: document.querySelector("#series-action-id").value.trim(),
    selector: document.querySelector("#series-selector").value.trim(),
    compilation_id: document.querySelector("#series-compilation-id").value.trim(),
  };
  try {
    renderJson("#series-result", await api(`/api/series/${action}`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({payload}),
    }));
  } catch (error) {
    notify(`Series ${action} lỗi: ${error.message}`, true);
  }
}

async function trendAction(action, payload) {
  try {
    const result = await api(`/api/trend/${action}`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({payload}),
    });
    renderJson("#trend-result", result);
    if (result.scan_id) document.querySelector("#trend-scan-id").value = result.scan_id;
  } catch (error) {
    notify(`Trend lỗi: ${error.message}`, true);
  }
}

async function startTrend(event) {
  event.preventDefault();
  await trendAction("scan", {
    query: document.querySelector("#trend-query").value.trim(),
    mode: document.querySelector("#trend-mode").value,
    days: Number(document.querySelector("#trend-days").value),
  });
}

async function loadSettings() {
  try {
    const settings = await api("/api/settings");
    state.settings = settings;
    document.querySelector("#settings-provider").value = settings.default_provider_id || "";
    document.querySelector("#settings-model").value = settings.default_model || "";
    const defaultVoice = settings.default_voice || "vieneu:hong-chau";
    setSelectValue(document.querySelector("#settings-voice"), defaultVoice);
    document.querySelector("#settings-vieneu-style").value = settings.vieneu_style || "story";
    document.querySelector("#settings-asr-engine").value = settings.asr_engine || "auto";
    document.querySelector("#settings-whisper-model").value = settings.whisper_model || "medium";
    document.querySelector("#settings-hardware-mode").value = settings.hardware_mode || "auto";
    document.querySelector("#settings-hardware-status").textContent =
      `Đang dùng ${hardwareProfileLabel(settings.hardware_profile || "cpu")}.`;
    document.querySelector("#settings-queue-poll").value = settings.queue_poll_seconds;
    document.querySelector("#settings-telegram-chat").value = settings.telegram_chat_id || "";
    document.querySelector("#settings-telegram-thread").value = settings.telegram_thread_id || "";
    document.querySelector("#settings-telegram-token").value = "";
    setSelectValue(document.querySelector("#job-voice"), defaultVoice);
    document.querySelector("#channel-provider").value = settings.default_provider_id || "";
    document.querySelector("#channel-model").value = settings.default_model || "";
    document.querySelector("#channel-voice").value = settings.default_voice || "";
    const provider = state.providers.find(
      (item) => item.id === settings.default_provider_id,
    );
    if (provider?.kind === "ai33") {
      document.querySelector("#job-tts-provider").value =
        defaultVoice.startsWith("ai33:") ? provider.id : "";
    } else if (provider) {
      document.querySelector("#job-translation-provider").value = provider.id;
    }
  } catch (error) {
    notify(`Không tải được settings: ${error.message}`, true);
  }
}

function hardwareProfileLabel(profile) {
  return {
    cpu: "CPU",
    hybrid: "GPU cho Ollama, CPU cho phần còn lại",
    gpu: "GPU cho Ollama, CPU cho phần còn lại",
  }[profile] || profile;
}

function settingsPayload(hardwareProfile = state.settings?.hardware_profile || "cpu") {
  return {
    default_provider_id: document.querySelector("#settings-provider").value,
    default_model: document.querySelector("#settings-model").value.trim(),
    default_voice: document.querySelector("#settings-voice").value.trim(),
    vieneu_style: document.querySelector("#settings-vieneu-style").value,
    asr_engine: document.querySelector("#settings-asr-engine").value,
    whisper_model: document.querySelector("#settings-whisper-model").value,
    hardware_mode: document.querySelector("#settings-hardware-mode").value,
    hardware_profile: hardwareProfile,
    queue_poll_seconds: Number(document.querySelector("#settings-queue-poll").value),
    telegram_chat_id: document.querySelector("#settings-telegram-chat").value.trim(),
    telegram_thread_id: document.querySelector("#settings-telegram-thread").value.trim(),
    telegram_bot_token: document.querySelector("#settings-telegram-token").value,
  };
}

async function detectHardware() {
  const detectButton = document.querySelector("#settings-hardware-detect");
  const status = document.querySelector("#settings-hardware-status");
  const mode = document.querySelector("#settings-hardware-mode").value;
  detectButton.disabled = true;
  status.textContent = "Đang nhận diện GPU và Docker...";
  try {
    const response = await fetch("http://127.0.0.1:18794/hardware/apply", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({mode}),
    });
    const result = await response.json();
    if (!response.ok || !result.ok) {
      throw new Error(result.error_code || `HTTP ${response.status}`);
    }
    await api("/api/settings", {
      method: "PUT",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(settingsPayload(result.selected_profile)),
    });
    const gpu = result.gpu
      ? `${result.gpu.name} (${Math.round(result.gpu.memory_mb / 1024)} GB VRAM)`
      : "không có GPU phù hợp";
    status.textContent =
      `${gpu}. Đang dùng ${hardwareProfileLabel(result.selected_profile)}.`;
    await loadSettings();
    await loadDoctor();
    notify("Đã áp dụng cấu hình phần cứng.");
  } catch (error) {
    status.textContent = "Không áp dụng được. Hệ thống tiếp tục dùng CPU.";
    notify(`Nhận diện phần cứng lỗi: ${error.message}. Hãy mở Docker Desktop và host helper.`, true);
  } finally {
    detectButton.disabled = false;
  }
}

function installComponent(payload, key) {
  return payload[key] || payload.installs?.[key] || payload.components?.[key] || {};
}

function installReady(key, component) {
  if (component.ready === true || component.state === "ready" || component.status === "ready") {
    return true;
  }
  if (key === "qwen_asr") {
    return component.service === true && component.model === true && component.aligner === true;
  }
  return component.health === true && Number(component.sample_rate) === 48000;
}

function installStatusText(key, component) {
  const label = key === "qwen_asr" ? "Qwen3 ASR" : "VieNeu";
  if (installReady(key, component)) {
    return key === "qwen_asr"
      ? "Qwen3 ASR đã sẵn sàng: service, model và aligner."
      : "VieNeu đã sẵn sàng: health tốt, âm thanh 48 kHz.";
  }
  const stateName = component.state || component.status;
  if (["queued", "installing", "downloading", "starting"].includes(stateName)) {
    return `${label} đang cài đặt${component.detail ? `: ${component.detail}` : "..."}`;
  }
  if (component.error_code || ["failed", "error"].includes(stateName)) {
    return `${label} cài đặt lỗi: ${component.error_code || component.detail || stateName}.`;
  }
  if (key === "qwen_asr") {
    const missing = [
      component.service === true ? "" : "service",
      component.model === true ? "" : "model",
      component.aligner === true ? "" : "aligner",
    ].filter(Boolean);
    return `Qwen3 ASR chưa sẵn sàng${missing.length ? `: thiếu ${missing.join(", ")}` : "."}`;
  }
  return `VieNeu chưa sẵn sàng: health=${component.health === true ? "tốt" : "chưa đạt"}, sample rate=${Number(component.sample_rate) || 0} Hz.`;
}

function renderInstallStatus(payload) {
  for (const [key, selector] of [
    ["qwen_asr", "#settings-qwen-status"],
    ["vieneu", "#settings-vieneu-status"],
  ]) {
    document.querySelector(selector).textContent =
      installStatusText(key, installComponent(payload, key));
  }
}

async function loadInstallStatus() {
  try {
    const response = await fetch("http://127.0.0.1:18794/install/status");
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error_code || `HTTP ${response.status}`);
    renderInstallStatus(payload);
    return payload;
  } catch {
    document.querySelector("#settings-qwen-status").textContent =
      "Không đọc được trạng thái Qwen3 ASR. Hãy chạy host helper.";
    document.querySelector("#settings-vieneu-status").textContent =
      "Không đọc được trạng thái VieNeu. Hãy chạy host helper.";
    return null;
  }
}

async function installRuntime(key) {
  const config = {
    qwen_asr: {
      endpoint: "http://127.0.0.1:18794/qwen-asr/install",
      button: "#settings-qwen-install",
      status: "#settings-qwen-status",
      label: "Qwen3 ASR",
    },
    vieneu: {
      endpoint: "http://127.0.0.1:18794/vieneu/install",
      button: "#settings-vieneu-install",
      status: "#settings-vieneu-status",
      label: "VieNeu",
    },
  }[key];
  const installButton = document.querySelector(config.button);
  const status = document.querySelector(config.status);
  installButton.disabled = true;
  status.textContent = `Đang gửi yêu cầu cài ${config.label}...`;
  try {
    const response = await fetch(config.endpoint, {method: "POST"});
    const payload = await response.json();
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.error_code || `HTTP ${response.status}`);
    }
    for (let attempt = 0; attempt < 900; attempt += 1) {
      const current = await loadInstallStatus();
      if (!current) throw new Error("HostHelperUnavailable");
      const component = installComponent(current, key);
      if (installReady(key, component)) {
        await loadDoctor();
        notify(`${config.label} đã sẵn sàng.`);
        return;
      }
      if (component.error_code || ["failed", "error"].includes(component.state || component.status)) {
        throw new Error(component.error_code || component.detail || "InstallFailed");
      }
      await new Promise((resolve) => window.setTimeout(resolve, 2000));
    }
    throw new Error("InstallTimeout");
  } catch (error) {
    status.textContent = `Không cài được ${config.label}: ${error.message}.`;
    notify(`Không cài được ${config.label}. Hãy chạy host helper và kiểm tra Docker.`, true);
  } finally {
    installButton.disabled = false;
  }
}

async function installLocalWhisper() {
  const installButton = document.querySelector("#settings-whisper-install");
  const model = document.querySelector("#settings-whisper-model").value;
  const originalLabel = installButton.textContent;
  installButton.disabled = true;
  installButton.textContent = "Đang tải model Whisper...";
  try {
    const response = await fetch("http://127.0.0.1:18794/whisper/install", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({model}),
    });
    const result = await response.json();
    if (!response.ok || !result.ok) {
      throw new Error(result.error_code || `HTTP ${response.status}`);
    }
    await loadDoctor();
    notify(`Whisper ${model} đã sẵn sàng.`);
  } catch (error) {
    notify(`Không tải được Whisper: ${error.message}. Hãy mở Docker Desktop và chạy host helper.`, true);
  } finally {
    installButton.disabled = false;
    installButton.textContent = originalLabel;
  }
}

async function loadBrandLogo() {
  try {
    const logo = await api("/api/branding/logo");
    const preview = document.querySelector("#settings-logo-preview");
    preview.hidden = !logo.configured;
    if (logo.configured) preview.src = `${logo.image_url}?t=${Date.now()}`;
    else preview.removeAttribute("src");
    document.querySelector("#settings-logo-remove").disabled = !logo.configured;
  } catch (error) {
    notify(`Không tải được trạng thái logo: ${error.message}`, true);
  }
}

async function saveBrandLogo() {
  const file = document.querySelector("#settings-logo-file").files[0];
  const url = document.querySelector("#settings-logo-url").value.trim();
  if (!file && !url) {
    notify("Chọn file logo hoặc dán URL HTTPS.", true);
    return;
  }
  try {
    if (file) {
      const body = new FormData();
      body.append("file", file);
      await api("/api/branding/logo", {method: "POST", body});
    } else {
      await api("/api/branding/logo-url", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({url}),
      });
    }
    document.querySelector("#settings-logo-file").value = "";
    document.querySelector("#settings-logo-url").value = "";
    await loadBrandLogo();
    notify("Đã lưu logo. Job Bilibili mới sẽ blur logo gốc và chèn logo này.");
  } catch (error) {
    notify(`Không lưu được logo: ${error.message}`, true);
  }
}

async function removeBrandLogo() {
  if (!window.confirm("Xóa logo cá nhân đang lưu?")) return;
  try {
    await api("/api/branding/logo", {method: "DELETE"});
    await loadBrandLogo();
    notify("Đã xóa logo.");
  } catch (error) {
    notify(`Không xóa được logo: ${error.message}`, true);
  }
}

function doctorAdvice(value) {
  const advice = {
    "FFmpeg": "Thiếu bộ xử lý hình ảnh và âm thanh.",
    "Whisper model/binary": "Thiếu bộ nhận dạng lời nói trong video.",
    "Qwen service": "Dịch vụ Qwen3 ASR chưa chạy.",
    "Qwen model": "Model Qwen3 ASR chưa được cài.",
    "Qwen aligner": "Bộ căn thời gian phụ đề của Qwen3 chưa sẵn sàng.",
    "VieNeu health": "Dịch vụ VieNeu chưa phản hồi health.",
    "VieNeu 48 kHz": "VieNeu chưa xuất âm thanh chuẩn 48 kHz.",
    "Demucs": "Thiếu bộ tách giọng nói khỏi nhạc nền.",
    "Writable runtime volumes": "Docker chưa ghi được dữ liệu. Hãy khởi động lại Docker.",
    "Ollama hoặc provider dịch": "Chưa chọn công cụ dịch tiếng Trung sang tiếng Việt.",
    "Ollama provider/endpoint": "Chưa thêm Ollama trong phần Nhà cung cấp.",
    "Ollama endpoint không kết nối được": "Ollama chưa chạy hoặc địa chỉ kết nối chưa đúng.",
    "API key provider dịch": "Công cụ dịch đang thiếu API key.",
    "AI33 provider": "Chưa thêm AI33 trong phần Nhà cung cấp.",
    "AI33_API_KEY": "Chưa nhập API key để tạo giọng đọc AI33.",
    "Edge TTS": "Chưa có công cụ tạo giọng đọc miễn phí Edge TTS.",
    "yt-dlp": "Thiếu công cụ tải video từ Bilibili.",
    "Bilibili cookie": "Chỉ cần đăng nhập khi Bilibili không cho tải video công khai.",
    "Host login helper": "Trợ lý mở trình duyệt đăng nhập chưa chạy.",
    "Telegram bot credential": "Chưa nhập token của Telegram bot.",
    "Telegram chat ID": "Chưa chọn nơi Telegram bot gửi kết quả.",
    "Trend host runner": "Tính năng tìm video xu hướng chưa được bật.",
  };
  return advice[value] || value;
}

function doctorItems(title, values, className = "") {
  if (!values.length) return null;
  const block = element("div", `doctor-items ${className}`.trim());
  block.append(element("strong", "", title));
  const list = element("ul");
  values.forEach((value) => list.append(element("li", "", doctorAdvice(value))));
  block.append(list);
  return block;
}

function doctorAction(workflow) {
  if (workflow.id === "bilibili") {
    showView("bilibili-login");
    return;
  }
  if (workflow.id === "trend") {
    showView("trend");
    return;
  }
  if (workflow.id === "telegram") {
    document.querySelector("#settings-telegram-token").focus();
    return;
  }
  if (workflow.id === "asr") {
    document.querySelector("#settings-asr-engine").focus();
    return;
  }
  if (workflow.id === "tts") {
    document.querySelector("#settings-voice").focus();
    return;
  }
  showView("providers");
  document.querySelector("#provider-name").focus();
}

function renderDoctor(report) {
  const target = document.querySelector("#settings-doctor-result");
  clear(target);
  const workflows = [...(report.workflows || [])].sort((left, right) => {
    const rank = {missing: 0, optional: 1, ready: 2};
    return rank[left.status] - rank[right.status];
  });
  const counts = {
    ready: workflows.filter((item) => item.status === "ready").length,
    missing: workflows.filter((item) => item.status === "missing").length,
    optional: workflows.filter((item) => item.status === "optional").length,
  };
  const summary = element("div", "doctor-summary");
  [
    ["Đang dùng được", counts.ready, "ready"],
    ["Cần thiết lập", counts.missing, "missing"],
    ["Không bắt buộc", counts.optional, "optional"],
  ].forEach(([label, count, status]) => {
    const item = element("div", `doctor-summary-item ${status}`);
    item.append(element("strong", "", String(count)));
    item.append(element("span", "", label));
    summary.append(item);
  });
  target.append(summary);
  workflows.forEach((workflow) => {
    const row = element("article", "doctor-row");
    const heading = element("div", "doctor-row-heading");
    heading.append(element("strong", "", workflow.label));
    heading.append(element(
      "span",
      `doctor-badge ${workflow.status}`,
      workflow.status === "ready"
        ? "Dùng được"
        : workflow.status === "optional"
          ? "Không bắt buộc"
          : "Cần thiết lập",
    ));
    row.append(heading);
    const missing = doctorItems("Cần làm", workflow.missing || [], "missing");
    const optional = doctorItems("Có thể làm thêm", workflow.optional || []);
    if (missing) row.append(missing);
    if (optional) row.append(optional);
    if (!missing && !optional) {
      row.append(element("p", "doctor-ready-copy", "Phần này đã sẵn sàng để sử dụng."));
    } else {
      row.append(button(
        "Mở phần thiết lập",
        "secondary doctor-action",
        () => doctorAction(workflow),
      ));
    }
    target.append(row);
  });
}

async function loadDoctor() {
  const target = document.querySelector("#settings-doctor-result");
  clear(target);
  target.append(element("p", "muted", "Đang kiểm tra cấu hình..."));
  try {
    renderDoctor(await api("/api/runtime/doctor"));
  } catch (error) {
    notify(`Doctor lỗi: ${error.message}`, true);
  }
}

async function saveSettings(event) {
  event.preventDefault();
  try {
    await api("/api/settings", {
      method: "PUT",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(settingsPayload()),
    });
    document.querySelector("#settings-telegram-token").value = "";
    await loadSettings();
    await loadDoctor();
    notify("Đã lưu settings.");
  } catch (error) {
    notify(`Không lưu được settings: ${error.message}`, true);
  }
}

async function showRuntime(path) {
  try {
    renderJson("#settings-result", await api(path, {method: path.includes("/test") ? "POST" : "GET"}));
  } catch (error) {
    notify(`Runtime lỗi: ${error.message}`, true);
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
document.querySelector("#provider-install-ollama").addEventListener("click", installLocalOllama);
document.querySelector("#provider-reset").addEventListener("click", resetProviderForm);
document.querySelector("#refresh-jobs").addEventListener("click", loadJobs);
document.querySelector("#refresh-providers").addEventListener("click", loadProviders);
document.querySelector("#queue-pause").addEventListener("click", toggleQueue);
document.querySelector("#bilibili-login-start").addEventListener("click", startBilibiliLogin);
document.querySelector("#bilibili-host-open").addEventListener("click", openHostBilibiliLogin);
document.querySelector("#bilibili-cookie-form").addEventListener("submit", importBilibiliCookies);
document.querySelector("#bilibili-login-clear").addEventListener("click", clearBilibiliLogin);
document.querySelector("#channel-form").addEventListener("submit", saveChannel);
document.querySelector("#channel-reset").addEventListener("click", resetChannelForm);
document.querySelector("#refresh-channels").addEventListener("click", loadChannels);
document.querySelector("#series-form").addEventListener("submit", addSeries);
document.querySelector("#refresh-series").addEventListener("click", loadSeries);
document.querySelectorAll("[data-series-action]").forEach((item) => {
  item.addEventListener("click", () => runSeriesAction(item.dataset.seriesAction));
});
document.querySelector("#trend-form").addEventListener("submit", startTrend);
document.querySelector("#trend-status").addEventListener("click", () => {
  trendAction("status", {scan_id: document.querySelector("#trend-scan-id").value.trim()});
});
document.querySelector("#trend-candidates").addEventListener("click", () => {
  trendAction("top-candidates", {
    scan_id: document.querySelector("#trend-scan-id").value.trim(),
    limit: 5,
  });
});
document.querySelector("#trend-tick").addEventListener("click", () => trendAction("collection-tick", {}));
document.querySelector("#trend-mode").addEventListener("change", (event) => {
  document.querySelector("#trend-days").max = event.target.value === "archive" ? "180" : "30";
});
document.querySelector("#settings-form").addEventListener("submit", saveSettings);
document.querySelector("#settings-whisper-install").addEventListener("click", installLocalWhisper);
document.querySelector("#settings-qwen-install").addEventListener("click", () => installRuntime("qwen_asr"));
document.querySelector("#settings-vieneu-install").addEventListener("click", () => installRuntime("vieneu"));
document.querySelector("#settings-hardware-detect").addEventListener("click", detectHardware);
document.querySelector("#settings-logo-save").addEventListener("click", saveBrandLogo);
document.querySelector("#settings-logo-remove").addEventListener("click", removeBrandLogo);
document.querySelector("#settings-doctor").addEventListener("click", loadDoctor);
document.querySelector("#settings-telegram-test").addEventListener("click", () => showRuntime("/api/telegram/test"));
document.querySelector("#settings-hyperframes").addEventListener("click", () => showRuntime("/api/hyperframes/status"));
document.querySelector("#settings-thumbnail").addEventListener("click", () => showRuntime("/api/thumbnail/status"));
document.querySelector("#settings-export").addEventListener("click", () => {
  window.location.assign("/api/runtime/export");
});
document.querySelector("#focus-new-job").addEventListener("click", () => {
  showView("jobs");
  document.querySelector("#job-source").focus();
});
document.querySelector("#job-file").addEventListener("change", (event) => {
  document.querySelector("#job-source").required = !event.target.files.length;
});
document.querySelector("#job-voice").addEventListener("change", (event) => {
  const ttsProvider = document.querySelector("#job-tts-provider");
  if (event.target.value.startsWith("ai33:")) selectFirstProvider(ttsProvider);
  else ttsProvider.value = "";
});

const initialView = new URLSearchParams(window.location.search).get("view");
if (["providers", "bilibili-login", "channels", "series", "trend", "settings"].includes(initialView)) showView(initialView);
checkHealth();
loadProviders();
loadJobs();
loadChannels();
loadSettings();
connectEvents();
window.setInterval(loadJobs, 10000);
window.setInterval(loadChannels, 10000);
window.setInterval(() => {
  const view = document.querySelector('.view[data-view="bilibili-login"]');
  if (!view.hidden) loadBilibiliStatus();
}, 3000);
