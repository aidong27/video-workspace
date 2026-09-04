(function () {
  "use strict";

  const byId = (id) => document.getElementById(id);
  const elements = {
    refreshButton: byId("refresh-button"),
    refreshLabel: byId("refresh-label"),
    freshness: byId("freshness"),
    freshnessText: byId("freshness-text"),
    lastUpdated: byId("last-updated"),
    errorPanel: byId("error-panel"),
    errorTitle: byId("error-title"),
    errorMessage: byId("error-message"),
    errorLogin: byId("error-login"),
    errorRetry: byId("error-retry")
  };

  const labels = {
    status: "总体状态", generated_at: "生成时间", version: "服务版本", active_users: "活跃用户",
    worker_alive: "主 Worker", workers_alive: "在线 Worker", worker_count: "Worker 数量", queued: "排队任务",
    running: "运行任务", max_pending: "最大排队数", persistent_enabled: "常驻模式", exit_on_idle: "空闲退出",
    idle_seconds: "空闲阈值", idle_exit_in_seconds: "距空闲退出", alive: "进程存活", warm: "模型已预热",
    start_count: "启动次数", process_rss_mb: "进程内存 RSS", process_swap_mb: "进程交换空间",
    rss_mb: "ASR 子进程 RSS", swap_mb: "ASR 子进程交换空间", snapshot_consistent: "状态快照一致",
    system_available_mb: "系统可用内存", swap_total_mb: "交换空间总量", swap_used_mb: "已用交换空间",
    available: "空间可用", total_bytes: "磁盘总容量", free_bytes: "磁盘可用容量", free_ratio: "磁盘可用比例",
    minimum_free_bytes: "最低保留容量", upload_reservations: "上传预留数", upload_reserved_bytes: "上传预留容量",
    media_reservations: "媒体预留数", media_reserved_bytes: "媒体预留容量", enabled: "已启用", ready: "已就绪",
    paid_allowed: "允许付费调用", usage: "用量", failures: "失败", window_days: "统计窗口", total: "总数",
    by_provider: "按提供商", by_model: "按模型", by_code: "按错误代码", by_outcome: "按结果",
    bilibili: "哔哩哔哩", douyin: "抖音", api_adapter_ready: "API 适配器", playwright_ready: "Playwright",
    chromium_ready: "Chromium", cookie_cached: "Cookie 缓存", ffmpeg: "FFmpeg", ffprobe: "FFprobe"
  };

  const sectionIds = ["service", "queue", "asr", "memory", "disk", "cloud", "failure", "platform", "tools"];
  let loading = false;

  function isObject(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value);
  }

  function finiteNumber(value) {
    return typeof value === "number" && Number.isFinite(value);
  }

  function formatBytes(value) {
    if (!finiteNumber(value)) return "—";
    const units = ["B", "KB", "MB", "GB", "TB"];
    let size = Math.max(0, value);
    let unit = 0;
    while (size >= 1024 && unit < units.length - 1) {
      size /= 1024;
      unit += 1;
    }
    const digits = size >= 100 || unit === 0 ? 0 : size >= 10 ? 1 : 2;
    return `${size.toFixed(digits)} ${units[unit]}`;
  }

  function formatSeconds(value) {
    if (!finiteNumber(value)) return "—";
    if (value < 60) return `${Math.round(value)} 秒`;
    if (value < 3600) return `${Math.floor(value / 60)} 分 ${Math.round(value % 60)} 秒`;
    return `${Math.floor(value / 3600)} 小时 ${Math.floor((value % 3600) / 60)} 分`;
  }

  function formatValue(key, value) {
    if (value === null || value === undefined || value === "") return "—";
    if (typeof value === "boolean") return value ? "是" : "否";
    if (key === "generated_at" && finiteNumber(value)) {
      const generated = new Date(value * 1000);
      if (!Number.isNaN(generated.getTime())) {
        return generated.toLocaleString("zh-CN", { hour12: false });
      }
    }
    if (key.endsWith("_bytes") && finiteNumber(value)) return formatBytes(value);
    if (key.endsWith("_mb") && finiteNumber(value)) return `${value.toLocaleString("zh-CN", { maximumFractionDigits: 1 })} MB`;
    if (key.endsWith("_seconds") && finiteNumber(value)) return formatSeconds(value);
    if (key.endsWith("_ratio") && finiteNumber(value)) return `${(value * 100).toFixed(1)}%`;
    if (key === "window_days" && finiteNumber(value)) return `${value} 天`;
    if (finiteNumber(value)) return value.toLocaleString("zh-CN", { maximumFractionDigits: 2 });
    if (Array.isArray(value)) return value.length ? value.map((item) => String(item)).join("、") : "无";
    return String(value);
  }

  function valueTone(key, value) {
    if (typeof value !== "boolean") return "";
    const negativeWhenTrue = key === "paid_allowed";
    if (negativeWhenTrue) return value ? "warn" : "good";
    return value ? "good" : "bad";
  }

  function displayLabel(path) {
    const parts = path.split(".");
    return parts.map((part) => labels[part] || part.replaceAll("_", " ")).join(" · ");
  }

  function flatten(value, prefix, rows, depth) {
    if (rows.length >= 40) return;
    if (isObject(value) && depth < 3) {
      const entries = Object.entries(value);
      if (!entries.length) {
        rows.push({ key: prefix || "status", value: "无记录", raw: null });
        return;
      }
      entries.forEach(([key, child]) => {
        const next = prefix ? `${prefix}.${key}` : key;
        if (isObject(child)) flatten(child, next, rows, depth + 1);
        else rows.push({ key: next, value: formatValue(key, child), raw: child, leaf: key });
      });
      return;
    }
    rows.push({ key: prefix || "status", value: formatValue(prefix || "status", value), raw: value, leaf: prefix });
  }

  function renderDetails(id, data) {
    const list = byId(`${id}-details`);
    const rows = [];
    flatten(data, "", rows, 0);
    list.replaceChildren();
    if (!rows.length) {
      const empty = document.createElement("p");
      empty.className = "empty-row";
      empty.textContent = "暂无诊断数据";
      list.appendChild(empty);
    } else {
      rows.forEach((row) => {
        const wrapper = document.createElement("div");
        const term = document.createElement("dt");
        const detail = document.createElement("dd");
        wrapper.className = "detail-row";
        term.textContent = displayLabel(row.key);
        term.title = term.textContent;
        detail.textContent = row.value;
        const tone = valueTone(row.leaf || row.key, row.raw);
        if (tone) detail.classList.add(tone);
        wrapper.append(term, detail);
        list.appendChild(wrapper);
      });
    }
    list.setAttribute("aria-busy", "false");
  }

  function setPill(id, text, tone) {
    const pill = byId(id);
    pill.className = id.endsWith("-pill") ? `status-pill ${tone}` : `section-state ${tone}`;
    pill.textContent = text;
  }

  function setText(id, text) {
    byId(id).textContent = text;
  }

  function boolState(value, goodText, badText) {
    return value ? { text: goodText, tone: "good" } : { text: badText, tone: "bad" };
  }

  function renderSummary(data) {
    const serviceGood = data.status === "ok";
    setPill("service-pill", serviceGood ? "正常" : "异常", serviceGood ? "good" : "bad");
    setText("service-value", serviceGood ? "运行正常" : "需要关注");
    setText("service-detail", `${data.service.version || "未知版本"} · ${data.service.active_users || 0} 位活跃用户`);

    const queued = Number(data.queue.queued) || 0;
    const running = Number(data.queue.running) || 0;
    const maxPending = Math.max(1, Number(data.queue.max_pending) || 1);
    const queueHealthy = Boolean(data.queue.worker_alive) && queued < maxPending;
    setPill("queue-pill", queueHealthy ? "可用" : "关注", queueHealthy ? "good" : "warn");
    setText("queue-value", `${queued} 排队 · ${running} 运行`);
    setText("queue-detail", `${data.queue.workers_alive || 0} / ${data.queue.worker_count || 0} 个 Worker 在线`);
    byId("queue-progress").max = maxPending;
    byId("queue-progress").value = Math.min(maxPending, queued);

    const availableMb = finiteNumber(data.memory.system_available_mb)
      ? data.memory.system_available_mb
      : Number.NaN;
    const memoryKnown = Number.isFinite(availableMb);
    const memoryGood = memoryKnown && availableMb >= 512;
    setPill(
      "memory-pill",
      memoryKnown ? (memoryGood ? "充足" : "关注") : "未知",
      memoryKnown ? (memoryGood ? "good" : "warn") : "neutral"
    );
    setText("memory-value", memoryKnown ? `${availableMb.toLocaleString("zh-CN", { maximumFractionDigits: 0 })} MB` : "—");
    setText("memory-detail", `服务进程 RSS ${formatValue("process_rss_mb", data.memory.process_rss_mb)}`);

    const freeRatio = Number(data.disk.free_ratio);
    const diskGood = Boolean(data.disk.available);
    setPill("disk-pill", diskGood ? "可用" : "不足", diskGood ? "good" : "bad");
    setText("disk-value", formatBytes(data.disk.free_bytes));
    setText("disk-detail", `总容量 ${formatBytes(data.disk.total_bytes)} · 最低保留 ${formatBytes(data.disk.minimum_free_bytes)}`);
    byId("disk-progress").max = 1;
    byId("disk-progress").value = Number.isFinite(freeRatio) ? Math.max(0, Math.min(1, freeRatio)) : 0;
  }

  function renderSections(data) {
    renderDetails("service", { status: data.status, generated_at: data.generated_at, ...data.service });
    renderDetails("queue", data.queue);
    renderDetails("asr", data.asr_worker);
    renderDetails("memory", data.memory);
    renderDetails("disk", { ...data.disk, temporary_storage: data.temporary_storage });
    renderDetails("cloud", { enabled: data.cloud_asr.enabled, ready: data.cloud_asr.ready, paid_allowed: data.cloud_asr.paid_allowed, usage: data.cloud_asr.usage });
    renderDetails("failure", data.cloud_asr.failures);
    renderDetails("platform", data.platforms);
    renderDetails("tools", data.tools);

    const serviceState = boolState(data.status === "ok", "正常", "异常");
    const queueState = boolState(Boolean(data.queue.worker_alive), "在线", "离线");
    const asrState = data.asr_worker.alive
      ? { text: data.asr_worker.warm ? "已预热" : "在线", tone: "good" }
      : { text: "按需启动", tone: "neutral" };
    const memoryState = !finiteNumber(data.memory.system_available_mb)
      ? { text: "未知", tone: "neutral" }
      : data.memory.system_available_mb >= 512
        ? { text: "正常", tone: "good" }
        : { text: "偏低", tone: "warn" };
    const diskState = boolState(Boolean(data.disk.available), "正常", "不足");
    const cloudState = !data.cloud_asr.enabled ? { text: "未启用", tone: "neutral" } : boolState(Boolean(data.cloud_asr.ready), "已就绪", "未就绪");
    const failureTotal = data.cloud_asr.failures.total;
    const failureKnown = data.cloud_asr.failures.available !== false && finiteNumber(failureTotal);
    const failureState = failureKnown
      ? { text: failureTotal ? `${failureTotal} 条` : "无失败", tone: failureTotal ? "warn" : "good" }
      : { text: "暂不可用", tone: "warn" };
    const platformReady = Boolean(data.platforms.bilibili && data.platforms.bilibili.enabled) || Boolean(data.platforms.douyin && data.platforms.douyin.enabled);
    const platformState = boolState(platformReady, "可用", "未启用");
    const toolsReady = Boolean(data.tools.ffmpeg) && Boolean(data.tools.ffprobe);
    const toolsState = boolState(toolsReady, "齐全", "缺失");
    [serviceState, queueState, asrState, memoryState, diskState, cloudState, failureState, platformState, toolsState]
      .forEach((state, index) => setPill(`${sectionIds[index]}-state`, state.text, state.tone));
  }

  function normalizePayload(payload) {
    if (!isObject(payload)) throw new Error("invalid_payload");
    return {
      status: payload.status,
      generated_at: payload.generated_at,
      service: isObject(payload.service) ? payload.service : {},
      queue: isObject(payload.queue) ? payload.queue : {},
      asr_worker: isObject(payload.asr_worker) ? payload.asr_worker : {},
      memory: isObject(payload.memory) ? payload.memory : {},
      disk: isObject(payload.disk) ? payload.disk : {},
      temporary_storage: isObject(payload.temporary_storage) ? payload.temporary_storage : {},
      cloud_asr: isObject(payload.cloud_asr) ? payload.cloud_asr : {},
      platforms: isObject(payload.platforms) ? payload.platforms : {},
      tools: isObject(payload.tools) ? payload.tools : {}
    };
  }

  function showError(status) {
    let title = "诊断数据加载失败";
    let message = "服务器未返回可用的诊断数据，请稍后重试。";
    let showLogin = false;
    if (status === 401) {
      title = "登录状态已失效";
      message = "请重新登录后再查看管理员诊断。";
      showLogin = true;
    } else if (status === 403) {
      title = "没有管理员权限";
      message = "当前账号无权查看此页面。如有需要，请联系服务管理员。";
    } else if (status === 0) {
      title = "无法连接诊断服务";
      message = "请检查网络连接，确认服务可访问后重试。";
    } else if (status >= 500) {
      title = "诊断服务暂时不可用";
      message = `服务器返回 HTTP ${status}，请稍后重试。`;
    }
    elements.errorTitle.textContent = title;
    elements.errorMessage.textContent = message;
    elements.errorLogin.hidden = !showLogin;
    elements.errorPanel.hidden = false;
    elements.freshness.className = "freshness error";
    elements.freshnessText.textContent = "更新失败";
  }

  function setLoading(active) {
    loading = active;
    elements.refreshButton.disabled = active;
    elements.refreshButton.classList.toggle("loading", active);
    elements.refreshLabel.textContent = active ? "刷新中" : "刷新";
  }

  async function loadDiagnostics() {
    if (loading) return;
    setLoading(true);
    elements.errorPanel.hidden = true;
    elements.freshness.className = "freshness";
    elements.freshnessText.textContent = "正在获取数据";
    try {
      const response = await fetch("/api/admin/diagnostics", {
        method: "GET",
        credentials: "same-origin",
        cache: "no-store",
        headers: { Accept: "application/json" }
      });
      if (!response.ok) {
        showError(response.status);
        return;
      }
      const payload = await response.json();
      const data = normalizePayload(payload);
      if (!isObject(data.cloud_asr.usage)) data.cloud_asr.usage = {};
      if (!isObject(data.cloud_asr.failures)) data.cloud_asr.failures = {};
      renderSummary(data);
      renderSections(data);
      const generatedAt = finiteNumber(data.generated_at) ? data.generated_at * 1000 : data.generated_at;
      const updated = generatedAt ? new Date(generatedAt) : new Date();
      const validDate = !Number.isNaN(updated.getTime());
      elements.lastUpdated.textContent = validDate ? updated.toLocaleString("zh-CN", { hour12: false }) : String(data.generated_at || "刚刚");
      if (validDate) elements.lastUpdated.dateTime = updated.toISOString();
      elements.freshness.className = "freshness online";
      elements.freshnessText.textContent = "数据已更新";
    } catch (error) {
      showError(error instanceof TypeError ? 0 : -1);
    } finally {
      setLoading(false);
    }
  }

  elements.refreshButton.addEventListener("click", loadDiagnostics);
  elements.errorRetry.addEventListener("click", loadDiagnostics);
  loadDiagnostics();
})();
