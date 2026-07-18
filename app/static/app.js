(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const elements = {
    form: $("extract-form"),
    input: $("video-input"),
    inputError: $("input-error"),
    paste: $("paste-input"),
    clearInput: $("clear-input"),
    taskHeading: $("task-heading"),
    platformDetect: $("platform-detect"),
    inputModeGroup: $("input-mode-group"),
    linkInputPanel: $("link-input-panel"),
    uploadInputPanel: $("upload-input-panel"),
    videoFile: $("video-file"),
    uploadDropzone: $("upload-dropzone"),
    uploadFileTitle: $("upload-file-title"),
    uploadFileDetail: $("upload-file-detail"),
    uploadError: $("upload-error"),
    uploadLimit: $("upload-limit"),
    sourceFieldGroup: $("source-field-group"),
    qualityFieldGroup: $("quality-field-group"),
    qualityCaption: $("quality-caption"),
    embeddedSubtitleRow: $("embedded-subtitle-row"),
    embeddedSubtitles: $("embedded-subtitles"),
    subtitleFormatGrid: $("subtitle-format-grid"),
    platformAiRow: $("platform-ai-row"),
    format: $("format-select"),
    lang: $("lang-select"),
    allowPlatformAi: $("allow-platform-ai"),
    cookieRow: $("cookie-row"),
    useCookie: $("use-cookie"),
    forceRefresh: $("force-refresh"),
    forceRefreshLabel: $("force-refresh-label"),
    forceRefreshHint: $("force-refresh-hint"),
    extractButton: $("extract-button"),
    extractButtonLabel: $("extract-button-label"),
    serviceState: $("service-state"),
    serviceLabel: $("service-label"),
    bilibiliChip: $("bilibili-chip"),
    douyinChip: $("douyin-chip"),
    uploadChip: $("upload-chip"),
    accountArea: $("account-area"),
    accountAvatar: $("account-avatar"),
    accountName: $("account-name"),
    logoutAccount: $("logout-account"),
    resultKicker: $("result-kicker"),
    resultTitle: $("result-title"),
    resultActions: $("result-actions"),
    copyResult: $("copy-result"),
    downloadResult: $("download-result"),
    statusPanel: $("status-panel"),
    statusMark: $("status-mark"),
    statusTitle: $("status-title"),
    statusDetail: $("status-detail"),
    statusElapsed: $("status-elapsed"),
    queueBadge: $("queue-badge"),
    cancelJob: $("cancel-job"),
    progressTrack: $("progress-track"),
    progressValue: $("progress-value"),
    metadataStrip: $("metadata-strip"),
    notice: $("result-notice"),
    outputShell: $("output-shell"),
    output: $("output"),
    outputFormat: $("output-format-label"),
    outputStats: $("output-stats-label"),
    mediaResult: $("media-result"),
    mediaFileMark: $("media-file-mark"),
    mediaFilename: $("media-filename"),
    mediaFileDetail: $("media-file-detail"),
    recentSection: $("recent-section"),
    recentList: $("recent-list"),
    clearHistory: $("clear-history"),
    loginSection: $("login-section"),
    loginStart: $("login-start"),
    loginStatus: $("login-status"),
    qrImage: $("qr-image"),
    toast: $("toast")
  };

  const state = {
    busy: false,
    startedAt: 0,
    elapsedTimer: null,
    pollTimer: null,
    toastTimer: null,
    loginPollTimer: null,
    uploadXhr: null,
    uploadFile: null,
    jobId: null,
    submissionKey: null,
    submissionSignature: null,
    currentPayload: null,
    current: null,
    resuming: false,
    user: null,
    health: null,
    history: [],
    uploadMaxBytes: 512 * 1024 * 1024,
    uploadExtensions: [],
    mediaEnabled: true,
    mediaMaxBytes: 1000 * 1000 * 1000
  };

  const sourceLabels = {
    official_no_cookie: "平台字幕",
    official_with_cookie: "平台字幕",
    asr_local: "本地语音识别",
    embedded_text: "内嵌字幕轨",
    ocr_video: "画面字幕 OCR"
  };

  const errorMessages = {
    invalid_input: "请输入有效的 B站或抖音视频链接，也可以输入 BV 号。",
    video_not_found: "没有找到这条视频，请检查链接是否有效。",
    no_official_subtitle: "这条视频没有可用的平台字幕。",
    queue_full: "当前等待任务较多，请稍后再提交。",
    asr_busy: "等待语音识别资源超时，请稍后重试。",
    asr_duration_too_long: "视频时长超过当前服务限制。",
    asr_timeout: "语音识别超时，可稍后重试或使用更短的视频。",
    asr_worker_crashed: "语音识别进程意外退出，可能是内存不足，请稍后重试。",
    asr_model_download_failed: "语音识别模型不可用，请检查模型缓存与服务器网络。",
    download_failed: "视频、音频或字幕下载失败，请稍后重试。",
    asr_failed: "本地语音识别失败，请稍后重试。",
    ocr_missing: "画面字幕识别组件尚未准备完成。",
    ocr_failed: "画面字幕识别失败，可取消画面字幕选项后改用语音识别。",
    ocr_empty: "没有在视频画面中识别到稳定字幕。",
    ocr_timeout: "画面字幕识别超时，请尝试更短的视频。",
    platform_temporarily_unavailable: "平台暂时拒绝了视频请求，请稍后重试。",
    douyin_browser_missing: "抖音处理组件尚未准备完成。",
    douyin_browser_busy: "抖音浏览器资源正忙，请稍后重试。",
    douyin_adapter_missing: "抖音处理组件尚未准备完成。",
    unsupported_upload_format: "暂不支持这种视频格式。",
    invalid_upload_media: "无法读取这个视频，请换一个文件。",
    upload_video_missing: "选择的文件不包含视频画面。",
    upload_audio_missing: "这个视频没有可识别的音轨。",
    upload_too_large: "视频文件超过当前上传限制。",
    upload_storage_busy: "服务器上传暂存空间正忙，请稍后再试。",
    upload_interrupted: "视频上传中断，请重试。",
    upload_expired: "上传视频已过期，请重新选择。",
    media_storage_busy: "服务器媒体暂存空间正忙，请稍后再试。",
    media_too_large: "媒体文件超过当前下载限制。",
    video_stream_missing: "没有找到可下载的视频画面。",
    audio_stream_missing: "没有找到可提取的音轨。",
    media_convert_failed: "音频转换失败，请稍后重试。",
    ffmpeg_failed: "媒体探测或转换失败，请确认文件可正常播放。",
    disk_space_low: "服务器剩余磁盘空间不足，请稍后重试。",
    no_audio_stream: "视频没有音轨，无法识别语音或生成 MP3。",
    subtitle_unavailable: "没有找到可读取的字幕或语音内容。",
    job_queue_full: "任务队列已满，请稍后重试。",
    job_expired: "服务可能已重启或任务已过期，请重新提交。",
    artifact_expired: "下载文件已过期，请重新提取。",
    artifact_not_found: "下载文件不存在或已过期。",
    job_not_found: "服务可能已重启或任务已过期，请重新提交。",
    idempotency_conflict: "这次提交与上一次请求不一致，请重新提交。",
    authentication_required: "登录已失效，正在返回登录页。"
  };

  const stageDetails = {
    starting: "处理线程已接收任务",
    validating: "正在校验视频内容",
    cache: "正在查找可复用的处理结果",
    discover: "正在查找平台字幕与语言轨道",
    platform: "正在读取视频信息与音轨",
    embedded_subtitle: "正在检查视频中的字幕轨",
    ocr_wait: "前一个画面识别任务结束后会自动继续",
    ocr: "正在逐帧识别画面中的字幕",
    ocr_fallback: "画面未识别到稳定字幕，正在改用精确语音识别",
    asr_wait: "前一条语音识别结束后会自动继续",
    download: "正在准备并标准化音轨",
    media_download: "正在从平台下载媒体文件",
    media_convert: "正在转换音频格式",
    media_finalize: "正在生成安全下载文件",
    transcribe: "模型正在把语音转成字幕",
    render: "正在整理时间轴与输出文件"
  };

  function historyStorageKey(userId) {
    return `video-workspace-history-v4:${userId}`;
  }

  function loadHistory(userId) {
    try {
      const value = JSON.parse(localStorage.getItem(historyStorageKey(userId)) || "[]");
      return Array.isArray(value) ? value.slice(0, 8) : [];
    } catch (_) {
      return [];
    }
  }

  function saveHistory() {
    if (!state.user) return;
    try {
      localStorage.setItem(historyStorageKey(state.user.id), JSON.stringify(state.history.slice(0, 8)));
    } catch (_) {
      return;
    }
  }

  function activeJobStorageKey(userId) {
    return `caption-active-job-v1:${userId}`;
  }

  function clearActiveJob() {
    if (!state.user) return;
    try {
      localStorage.removeItem(activeJobStorageKey(state.user.id));
    } catch (_) {
      return;
    }
  }

  function saveActiveJob() {
    if (!state.user || !state.jobId || !state.currentPayload) return;
    try {
      localStorage.setItem(activeJobStorageKey(state.user.id), JSON.stringify({
        jobId: state.jobId,
        payload: state.currentPayload,
        startedAt: state.startedAt || Date.now(),
        savedAt: Date.now()
      }));
    } catch (_) {
      return;
    }
  }

  function restoreForm(payload) {
    if (!payload) return;
    setSelectedOperation(payload.kind === "media" ? payload.media_type : "subtitle");
    setInputMode(payload.kind === "upload" ? "upload" : "link");
    if (payload.kind !== "media") {
      elements.format.value = payload.format || "txt";
      elements.lang.value = payload.lang || "";
      setSelectedQuality(payload.quality || "fast");
      elements.embeddedSubtitles.checked = Boolean(payload.embedded_subtitles);
    }
    elements.forceRefresh.checked = Boolean(payload.force_refresh);
    if (payload.kind === "upload") {
      state.uploadFile = null;
      elements.uploadFileTitle.textContent = payload.filename || "已上传视频";
      elements.uploadFileDetail.textContent = "文件已上传，正在处理";
      elements.uploadDropzone.classList.add("selected");
      syncInputMode();
      return;
    }
    if (!payload.input) return;
    elements.input.value = payload.input;
    if (payload.kind !== "media") elements.allowPlatformAi.checked = payload.allow_platform_ai !== false;
    elements.useCookie.checked = Boolean(payload.use_cookie);
    if (payload.kind !== "media") setSelectedSource(payload.source || "auto");
    updatePlatformDetect();
    syncInputMode();
  }

  function resumeActiveJob() {
    if (!state.user || state.busy) return;
    let saved;
    try {
      saved = JSON.parse(localStorage.getItem(activeJobStorageKey(state.user.id)) || "null");
    } catch (_) {
      clearActiveJob();
      return;
    }
    if (!saved || !saved.jobId || !saved.payload || Date.now() - Number(saved.savedAt || 0) > 2 * 60 * 60 * 1000) {
      clearActiveJob();
      return;
    }
    state.jobId = saved.jobId;
    state.currentPayload = saved.payload;
    state.current = null;
    state.resuming = true;
    restoreForm(saved.payload);
    setBusy(true, Number(saved.startedAt || Date.now()));
    const platform = saved.payload.kind === "upload" ? "upload" : detectPlatform(saved.payload.input || "");
    elements.resultKicker.textContent = `${platformLabel(platform)}任务`;
    elements.resultTitle.textContent = "正在恢复任务";
    showStatus("processing", "正在恢复任务", "正在读取服务器上的处理进度", 4, "…");
    pollJob();
  }

  async function apiFetch(url, options) {
    const response = await fetch(url, options);
    if (response.status === 401) {
      window.location.replace("/login");
    }
    return response;
  }

  async function loadAccount() {
    try {
      const response = await apiFetch("/api/auth/me", { cache: "no-store" });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.user) return;
      state.user = data.user;
      elements.accountName.textContent = data.user.username;
      elements.accountAvatar.textContent = String(data.user.username || "?").charAt(0).toUpperCase();
      elements.logoutAccount.disabled = false;
      elements.accountArea.setAttribute("aria-busy", "false");
      state.history = loadHistory(data.user.id);
      renderHistory();
      if (state.jobId && state.busy) saveActiveJob();
      else resumeActiveJob();
    } catch (_) {
      elements.accountName.textContent = "连接失败";
    }
  }

  async function logoutAccount() {
    elements.logoutAccount.disabled = true;
    try {
      const response = await apiFetch("/api/auth/logout", { method: "POST" });
      if (!response.ok) throw new Error(String(response.status));
      clearActiveJob();
      window.location.replace("/login");
    } catch (_) {
      elements.logoutAccount.disabled = false;
      showToast("退出失败，请检查网络后重试。", true);
    }
  }

  function selectedSource() {
    const selected = elements.form.querySelector('input[name="source"]:checked');
    return selected ? selected.value : "auto";
  }

  function selectedQuality() {
    const selected = elements.form.querySelector('input[name="quality"]:checked');
    return selected ? selected.value : "fast";
  }

  function selectedEmbeddedSubtitles() {
    return elements.embeddedSubtitles.checked && !elements.embeddedSubtitles.disabled;
  }

  function selectedOperation() {
    const selected = elements.form.querySelector('input[name="operation"]:checked');
    return selected ? selected.value : "subtitle";
  }

  function selectedInputMode() {
    const selected = elements.form.querySelector('input[name="input-mode"]:checked');
    return selected ? selected.value : "link";
  }

  function updateSubmitLabel() {
    if (state.busy) return;
    const operation = selectedOperation();
    elements.taskHeading.textContent = operation === "video"
      ? "提取视频"
      : operation === "audio" ? "提取音频" : "提取字幕";
    elements.extractButtonLabel.textContent = operation === "video"
      ? "提取视频"
      : operation === "audio"
        ? "提取音频"
        : selectedInputMode() === "upload" ? "开始识别" : "开始提取";
  }

  function syncInputMode() {
    const operation = selectedOperation();
    const mediaMode = operation !== "subtitle";
    const linkRadio = elements.form.querySelector('input[name="input-mode"][value="link"]');
    const uploadRadio = elements.form.querySelector('input[name="input-mode"][value="upload"]');
    if (mediaMode && uploadRadio.checked) linkRadio.checked = true;
    const uploadMode = !mediaMode && selectedInputMode() === "upload";
    const uploadsEnabled = !state.health || !state.health.uploads || state.health.uploads.enabled !== false;
    elements.inputModeGroup.hidden = mediaMode;
    elements.linkInputPanel.hidden = uploadMode;
    elements.uploadInputPanel.hidden = !uploadMode;
    elements.sourceFieldGroup.hidden = uploadMode || mediaMode;
    elements.subtitleFormatGrid.hidden = mediaMode;
    elements.platformAiRow.hidden = uploadMode || mediaMode || elements.embeddedSubtitles.checked;
    const cookieReady = Boolean(state.health && state.health.cookie_enabled && state.health.cookie_configured);
    elements.cookieRow.hidden = uploadMode || !cookieReady;
    elements.input.required = !uploadMode;
    elements.clearInput.title = uploadMode ? "清除视频" : "清空输入";
    uploadRadio.disabled = state.busy || mediaMode || !uploadsEnabled;
    linkRadio.disabled = state.busy;
    elements.videoFile.disabled = state.busy || !uploadsEnabled;
    elements.form.querySelectorAll('input[name="operation"]').forEach((radio) => {
      radio.disabled = state.busy || (radio.value !== "subtitle" && !state.mediaEnabled);
    });
    elements.forceRefreshLabel.textContent = mediaMode ? "重新获取平台信息" : "忽略已有结果";
    elements.forceRefreshHint.textContent = mediaMode ? "不复用已有的视频解析信息" : "重新下载并处理视频";
    syncPrecisionOptions();
    updateSubmitLabel();
  }

  function setInputMode(value) {
    const radio = elements.form.querySelector(`input[name="input-mode"][value="${value}"]`);
    if (radio && !radio.disabled) radio.checked = true;
    syncInputMode();
  }

  function setSelectedSource(value) {
    const radio = elements.form.querySelector(`input[name="source"][value="${value}"]`);
    if (radio) radio.checked = true;
  }

  function setSelectedQuality(value) {
    const radio = elements.form.querySelector(`input[name="quality"][value="${value}"]`);
    if (radio) radio.checked = true;
  }

  function syncPrecisionOptions() {
    const subtitleMode = selectedOperation() === "subtitle";
    const videoSubtitleReady = !state.health
      || !state.health.ocr
      || state.health.ocr.embedded_tracks_enabled !== false;
    elements.embeddedSubtitles.disabled = state.busy || !subtitleMode || !videoSubtitleReady;
    const embedded = subtitleMode && selectedEmbeddedSubtitles();
    if (embedded) {
      setSelectedQuality("accurate");
      setSelectedSource("auto");
    }
    elements.qualityFieldGroup.hidden = !subtitleMode;
    elements.embeddedSubtitleRow.hidden = !subtitleMode;
    elements.form.querySelectorAll('input[name="quality"]').forEach((radio) => {
      radio.disabled = state.busy || !subtitleMode || (embedded && radio.value === "fast");
    });
    elements.form.querySelectorAll('input[name="source"]').forEach((radio) => {
      radio.disabled = state.busy || embedded;
    });
    elements.allowPlatformAi.disabled = state.busy || embedded;
    elements.qualityCaption.textContent = embedded
      ? "会下载视频并优先识别内嵌或烧录在画面中的字幕"
      : selectedQuality() === "accurate"
        ? "使用更强模型和更细致解码，处理时间更长"
        : "适合吐字清晰的视频，优先缩短等待时间";
    elements.platformAiRow.hidden = !subtitleMode || selectedInputMode() === "upload" || embedded;
  }

  function setSelectedOperation(value) {
    const radio = elements.form.querySelector(`input[name="operation"][value="${value}"]`);
    if (radio && !radio.disabled) radio.checked = true;
    syncInputMode();
  }

  function detectPlatform(value) {
    if (/(?:^|\.)?(?:douyin\.com|iesdouyin\.com)\//i.test(value)) return "douyin";
    if (/(BV[0-9A-Za-z]{8,}|(?:bilibili\.com|b23\.tv)\/)/i.test(value)) return "bilibili";
    return "unknown";
  }

  function platformLabel(platform) {
    if (platform === "douyin") return "抖音";
    if (platform === "bilibili") return "B站";
    if (platform === "upload") return "本地视频";
    return "视频平台";
  }

  function formatBytes(value) {
    const bytes = Math.max(0, Number(value || 0));
    if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
    if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(bytes < 10 * 1024 * 1024 ? 1 : 0)} MB`;
    return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
  }

  function setUploadFile(file) {
    state.uploadFile = file || null;
    elements.videoFile.value = "";
    elements.uploadError.textContent = "";
    elements.uploadDropzone.classList.toggle("selected", Boolean(file));
    elements.uploadFileTitle.textContent = file ? file.name : "选择视频";
    elements.uploadFileDetail.textContent = file ? formatBytes(file.size) : "或拖放到这里";
  }

  function clearUnavailableUploadSelection() {
    if (state.currentPayload && state.currentPayload.kind === "upload" && !state.uploadFile) {
      setUploadFile(null);
    }
  }

  function validateUpload() {
    const file = state.uploadFile;
    let message = "";
    if (!file) {
      message = "请先选择视频文件。";
    } else if (!file.size) {
      message = "选择的视频文件为空。";
    } else if (file.size > state.uploadMaxBytes) {
      message = `视频文件不能超过 ${formatBytes(state.uploadMaxBytes)}。`;
    } else if (state.uploadExtensions.length) {
      const suffix = file.name.includes(".") ? `.${file.name.split(".").pop().toLowerCase()}` : "";
      if (!state.uploadExtensions.includes(suffix)) message = "暂不支持这种视频格式。";
    }
    elements.uploadError.textContent = message;
    return !message;
  }

  function updatePlatformDetect() {
    const platform = detectPlatform(elements.input.value.trim());
    const label = platform === "unknown" ? "等待识别平台" : `已识别为${platformLabel(platform)}`;
    elements.platformDetect.className = `platform-detect ${platform}`;
    elements.platformDetect.querySelector("span").textContent = label;
    return platform;
  }

  function buildPayload(overrides) {
    const operation = selectedOperation();
    const payload = operation === "subtitle"
      ? {
          input: elements.input.value.trim(),
          source: selectedSource(),
          format: elements.format.value,
          lang: elements.lang.value || null,
          quality: selectedQuality(),
          embedded_subtitles: selectedEmbeddedSubtitles(),
          use_cookie: elements.useCookie.checked,
          allow_platform_ai: elements.allowPlatformAi.checked,
          force_refresh: elements.forceRefresh.checked
        }
      : {
          kind: "media",
          input: elements.input.value.trim(),
          media_type: operation,
          use_cookie: elements.useCookie.checked,
          force_refresh: elements.forceRefresh.checked
        };
    return Object.assign(payload, overrides || {});
  }

  function validateInput() {
    const value = elements.input.value.trim();
    const platform = detectPlatform(value);
    let message = "";
    if (!value) {
      message = "请输入视频链接或 BV 号。";
    } else if (platform === "unknown") {
      message = "没有识别到 B站或抖音视频链接。";
    }
    elements.input.classList.toggle("invalid", Boolean(message));
    elements.inputError.textContent = message;
    updatePlatformDetect();
    return !message;
  }

  function stopPolling() {
    if (state.pollTimer) clearTimeout(state.pollTimer);
    state.pollTimer = null;
  }

  function setBusy(busy, startedAt) {
    state.busy = busy;
    elements.extractButton.disabled = busy;
    elements.extractButton.classList.toggle("loading", busy);
    elements.extractButtonLabel.textContent = busy ? "任务处理中" : "";
    elements.resultActions.hidden = busy || !state.current;
    elements.copyResult.hidden = Boolean(state.current && state.current.kind === "media");
    syncInputMode();
    if (state.elapsedTimer) clearInterval(state.elapsedTimer);
    state.elapsedTimer = null;
    if (!busy) {
      elements.statusElapsed.textContent = "";
      return;
    }
    state.startedAt = Number(startedAt || Date.now());
    const updateElapsed = () => {
      const elapsed = Math.max(0, Math.floor((Date.now() - state.startedAt) / 1000));
      elements.statusElapsed.textContent = `已用时 ${elapsed} 秒`;
    };
    updateElapsed();
    state.elapsedTimer = setInterval(updateElapsed, 1000);
  }

  function showStatus(kind, title, detail, progress, mark) {
    elements.statusPanel.hidden = false;
    elements.statusPanel.className = `status-panel ${kind || ""}`.trim();
    elements.statusTitle.textContent = title;
    elements.statusDetail.textContent = detail;
    elements.statusMark.querySelector("span").textContent = mark || (kind === "error" ? "!" : "CC");
    const numericProgress = Number(progress);
    elements.progressTrack.hidden = !Number.isFinite(numericProgress);
    elements.progressValue.style.width = Number.isFinite(numericProgress)
      ? `${Math.min(100, Math.max(2, numericProgress))}%`
      : "0%";
    elements.outputShell.hidden = true;
    elements.mediaResult.hidden = true;
    elements.metadataStrip.hidden = true;
    elements.notice.hidden = true;
  }

  function errorDetail(value) {
    if (!value) return {};
    if (value.detail) return value.detail;
    if (value.error) return value.error;
    return value;
  }

  function friendlyError(value, status) {
    const detail = errorDetail(value);
    const reason = detail && typeof detail === "object" ? detail.reason : "";
    const code = detail && typeof detail === "object" ? detail.code : "";
    if (code && errorMessages[code]) return errorMessages[code];
    if (reason && errorMessages[reason]) return errorMessages[reason];
    if (status === 401) return "访问凭据已失效，请重新登录。";
    if (status === 413) return "视频或音频文件超过当前大小限制。";
    if (status === 415) return "暂不支持这种视频格式。";
    if (status === 429) return "请求过于频繁或任务队列已满，请稍后再试。";
    if (status >= 500) return "服务暂时不可用，请稍后重试。";
    if (typeof detail === "string") return detail;
    if (detail && detail.message) return detail.message;
    return "任务失败，请检查输入后重试。";
  }

  function formatDuration(seconds) {
    const value = Number(seconds || 0);
    if (!value) return "";
    const total = Math.round(value);
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const secs = total % 60;
    if (hours) return `${hours}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
    return `${minutes}:${String(secs).padStart(2, "0")}`;
  }

  function formatElapsed(seconds) {
    const value = Number(seconds || 0);
    if (value < 0.1) return `${Math.max(1, Math.round(value * 1000))} ms`;
    return `${value.toFixed(value < 10 ? 2 : 1)} 秒`;
  }

  function addChip(label, className) {
    const chip = document.createElement("span");
    chip.className = `meta-chip ${className || ""}`.trim();
    chip.textContent = label;
    elements.metadataStrip.appendChild(chip);
  }

  function renderMetadata(meta) {
    elements.metadataStrip.textContent = "";
    addChip(platformLabel(meta.platform), meta.platform || "");
    if (meta.media_type) {
      addChip(meta.media_type === "audio" ? "MP3 音频" : "视频文件", meta.media_type === "audio" ? "asr" : "");
    } else {
      addChip(sourceLabels[meta.source] || meta.source || "未知来源", ["asr_local", "ocr_video"].includes(meta.source) ? "asr" : "");
    }
    const quality = meta.effective_quality || meta.quality || meta.requested_quality;
    if (quality && ["asr_local", "ocr_video"].includes(meta.source)) {
      addChip(quality === "accurate" ? "精确模式" : "快速模式", quality === "accurate" ? "asr" : "");
    }
    if (meta.track_source_type === "embedded_text") addChip("内嵌字幕", "cache");
    if (meta.track_source_type === "burned_in_ocr") addChip("画面字幕", "asr");
    if (meta.cache_hit) addChip("已命中缓存", "cache");
    if (meta.duration) addChip(`时长 ${formatDuration(meta.duration)}`);
    if (meta.entry_count) addChip(`${meta.entry_count} 条`);
    if (meta.language) addChip(`语言 ${String(meta.language).toUpperCase()}`);
    if (meta.elapsed_seconds !== undefined) addChip(`用时 ${formatElapsed(meta.elapsed_seconds)}`);
    if (meta.asr_worker_reused) addChip("模型已热启动", "cache");
    elements.metadataStrip.hidden = false;
  }

  function friendlyNotice(meta) {
    if (meta.source === "embedded_text" || meta.track_source_type === "embedded_text") {
      return "已直接提取视频文件中的内嵌字幕轨。";
    }
    if (meta.source === "ocr_video" || meta.track_source_type === "burned_in_ocr") {
      return "已识别烧录在视频画面中的字幕，建议快速校对专有名词。";
    }
    if (meta.ocr_fallback_to_asr || meta.ocr_fallback || meta.fallback_from === "ocr") {
      return "画面未识别到稳定字幕，本次已自动改用精确语音识别。";
    }
    if (meta.platform === "upload") {
      return "识别完成，服务器中的临时视频已自动删除。";
    }
    if (meta.source === "asr_local" && meta.requested_source === "auto") {
      return `未找到可用的${platformLabel(meta.platform)}字幕，本次已使用本地语音识别。`;
    }
    if (meta.track_source_type === "platform_ai") {
      return `本次使用了${platformLabel(meta.platform)}平台自动字幕。`;
    }
    return "";
  }

  function renderResult(data, payload) {
    if (data.kind === "media" || data.download_url) {
      renderMediaResult(data, payload);
      return;
    }
    state.current = {
      kind: "subtitle",
      content: data.content || "",
      filename: data.filename || `video_subtitle.${data.format || "txt"}`,
      contentType: data.content_type || "text/plain;charset=utf-8",
      format: data.format || payload.format,
      metadata: data.metadata || {},
      input: payload.input || payload.filename || ""
    };
    const meta = state.current.metadata;
    elements.resultKicker.textContent = `${platformLabel(meta.platform)}字幕 · ${meta.id || "已完成"}`;
    elements.resultTitle.textContent = meta.title || "提取完成";
    elements.statusPanel.hidden = true;
    elements.queueBadge.hidden = true;
    elements.cancelJob.hidden = true;
    renderMetadata(meta);

    const notice = friendlyNotice(meta);
    elements.notice.textContent = notice;
    elements.notice.hidden = !notice;
    elements.output.textContent = state.current.content;
    elements.outputFormat.textContent = state.current.format.toUpperCase();
    const lineCount = state.current.content ? state.current.content.split("\n").filter(Boolean).length : 0;
    elements.outputStats.textContent = `${lineCount} 行 · ${state.current.content.length.toLocaleString("zh-CN")} 字符`;
    elements.outputShell.hidden = false;
    elements.mediaResult.hidden = true;
    elements.copyResult.hidden = false;
    elements.resultActions.hidden = false;
    elements.forceRefresh.checked = false;
    if (payload.kind !== "upload") addHistory(payload, meta);
  }

  function renderMediaResult(data, payload) {
    state.current = {
      kind: "media",
      filename: data.filename || (data.media_type === "audio" ? "audio.mp3" : "video.mp4"),
      contentType: data.content_type || "application/octet-stream",
      downloadUrl: data.download_url || "",
      size: Number(data.size || 0),
      mediaType: data.media_type || payload.media_type,
      metadata: data.metadata || {},
      input: payload.input || ""
    };
    const meta = state.current.metadata;
    elements.resultKicker.textContent = `${platformLabel(meta.platform)}${state.current.mediaType === "audio" ? "音频" : "视频"} · ${meta.id || "已完成"}`;
    elements.resultTitle.textContent = meta.title || "提取完成";
    elements.statusPanel.hidden = true;
    elements.queueBadge.hidden = true;
    elements.cancelJob.hidden = true;
    renderMetadata(meta);
    elements.notice.hidden = true;
    elements.outputShell.hidden = true;
    elements.mediaFileMark.textContent = state.current.mediaType === "audio"
      ? "MP3"
      : (state.current.filename.split(".").pop() || "VIDEO").toUpperCase();
    elements.mediaFilename.textContent = state.current.filename;
    const ttlMinutes = Math.max(1, Math.round(Number(meta.artifact_ttl_seconds || 0) / 60));
    elements.mediaFileDetail.textContent = `${formatBytes(state.current.size)} · 保留 ${ttlMinutes} 分钟`;
    elements.mediaResult.hidden = false;
    elements.copyResult.hidden = true;
    elements.resultActions.hidden = false;
    elements.forceRefresh.checked = false;
    addHistory(payload, meta);
  }

  function addHistory(payload, meta) {
    const operation = payload.kind === "media" ? payload.media_type : "subtitle";
    const sourceId = meta.id || payload.input;
    const id = `${sourceId}:${operation}`;
    const item = {
      id,
      input: payload.input,
      title: meta.title || sourceId,
      operation,
      source: payload.source,
      quality: payload.quality || "fast",
      embeddedSubtitles: Boolean(payload.embedded_subtitles),
      format: payload.format || (operation === "audio" ? "mp3" : "mp4"),
      lang: payload.lang || "",
      platform: meta.platform || detectPlatform(payload.input),
      time: Date.now()
    };
    state.history = [item].concat(state.history.filter((entry) => entry.id !== id)).slice(0, 8);
    saveHistory();
    renderHistory();
  }

  function renderHistory() {
    elements.recentList.textContent = "";
    elements.recentSection.hidden = state.history.length === 0;
    state.history.forEach((item) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "recent-item";
      const platform = document.createElement("span");
      platform.className = `recent-platform ${item.platform || "bilibili"}`;
      platform.textContent = platformLabel(item.platform || "bilibili");
      const title = document.createElement("span");
      title.className = "recent-title";
      title.textContent = item.title;
      const detail = document.createElement("span");
      detail.className = "recent-detail";
      detail.textContent = `${String(item.format || "txt").toUpperCase()} · ${new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit" }).format(item.time)}`;
      button.append(platform, title, detail);
      button.addEventListener("click", () => {
        if (state.busy) return;
        setSelectedOperation(item.operation || "subtitle");
        setInputMode("link");
        elements.input.value = item.input;
        if ((item.operation || "subtitle") === "subtitle") {
          elements.format.value = item.format;
          elements.lang.value = item.lang || "";
          setSelectedSource(item.source || "auto");
          setSelectedQuality(item.quality || "fast");
          elements.embeddedSubtitles.checked = Boolean(item.embeddedSubtitles);
          syncInputMode();
        }
        elements.forceRefresh.checked = false;
        updatePlatformDetect();
        runExtraction();
      });
      elements.recentList.appendChild(button);
    });
  }

  function finishWithError(value, status) {
    stopPolling();
    const message = friendlyError(value, status || 0);
    clearActiveJob();
    state.jobId = null;
    state.current = null;
    state.resuming = false;
    elements.resultTitle.textContent = "任务失败";
    elements.resultKicker.textContent = "任务工作区";
    elements.resultActions.hidden = true;
    elements.queueBadge.hidden = true;
    elements.cancelJob.hidden = true;
    clearUnavailableUploadSelection();
    showStatus("error", "未能完成任务", message, NaN, "!");
    setBusy(false);
    showToast(message, true);
    loadHealth();
  }

  function handleJob(job) {
    if (!job || !job.status) return;
    state.resuming = false;
    if (job.status === "queued") {
      const ahead = Math.max(0, Number(job.queue_position || 1) - 1);
      elements.queueBadge.textContent = ahead ? `前方 ${ahead} 个任务` : "即将开始";
      elements.queueBadge.hidden = false;
      elements.cancelJob.textContent = "取消排队";
      elements.cancelJob.hidden = false;
      showStatus("queued", "任务正在排队", job.message || "等待处理资源", job.progress || 3, "…");
      return;
    }
    elements.queueBadge.hidden = true;
    elements.cancelJob.textContent = "取消排队";
    elements.cancelJob.hidden = true;
    if (job.status === "running") {
      const detail = stageDetails[job.stage] || "服务器正在处理当前任务";
      showStatus("processing", job.message || "正在处理视频", detail, job.progress || 8, "…");
      return;
    }
    if (job.status === "completed") {
      stopPolling();
      clearActiveJob();
      state.jobId = null;
      renderResult(job.result || {}, state.currentPayload);
      clearUnavailableUploadSelection();
      setBusy(false);
      loadHealth();
      return;
    }
    if (job.status === "cancelled") {
      stopPolling();
      clearActiveJob();
      state.jobId = null;
      state.current = null;
      clearUnavailableUploadSelection();
      showStatus("idle", "任务已取消", "可以修改设置后重新提交", NaN, "CC");
      setBusy(false);
      loadHealth();
      return;
    }
    if (job.status === "failed") {
      finishWithError(job.error || {}, Number(job.error_status || 500));
    }
  }

  async function pollJob() {
    if (!state.jobId || !state.busy) return;
    try {
      const response = await apiFetch(`/api/jobs/${encodeURIComponent(state.jobId)}`, { cache: "no-store" });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        if (response.status === 401) return;
        finishWithError(data, response.status);
        return;
      }
      handleJob(data);
    } catch (_) {
      elements.statusDetail.textContent = "网络连接短暂中断，正在继续查询任务";
    }
    if (state.jobId && state.busy) state.pollTimer = setTimeout(pollJob, 1800);
  }

  function submissionKey(payload) {
    const signature = JSON.stringify(payload);
    if (!state.submissionKey || state.submissionSignature !== signature) {
      state.submissionKey = window.crypto && typeof window.crypto.randomUUID === "function"
        ? window.crypto.randomUUID()
        : `${Date.now()}:${Math.random().toString(36).slice(2)}`;
      state.submissionSignature = signature;
    }
    return state.submissionKey;
  }

  async function runExtraction(overrides) {
    if (state.busy || !validateInput()) return;
    const payload = buildPayload(overrides);
    const endpoint = payload.kind === "media" ? "/api/media-jobs" : "/api/jobs";
    const idempotencyKey = submissionKey(payload);
    state.current = null;
    state.currentPayload = payload;
    setBusy(true);
    elements.resultKicker.textContent = `${platformLabel(detectPlatform(payload.input))}任务`;
    elements.resultTitle.textContent = "正在创建任务";
    elements.resultActions.hidden = true;
    showStatus("processing", "正在提交任务", "正在连接处理服务", 2, "…");
    try {
      const response = await apiFetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey },
        body: JSON.stringify(payload)
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        state.submissionKey = null;
        state.submissionSignature = null;
        finishWithError(data, response.status);
        return;
      }
      stopPolling();
      state.jobId = data.id;
      state.submissionKey = null;
      state.submissionSignature = null;
      if (data.status === "queued" || data.status === "running") saveActiveJob();
      handleJob(data);
      if (state.jobId && state.busy) state.pollTimer = setTimeout(pollJob, 700);
    } catch (_) {
      finishWithError({ reason: "network_error", message: "无法连接处理服务。" }, 0);
    }
  }

  function runUpload() {
    if (state.busy || !validateUpload()) return;
    const file = state.uploadFile;
    const payload = {
      kind: "upload",
      filename: file.name,
      size: file.size,
      last_modified: file.lastModified || 0,
      format: elements.format.value,
      lang: elements.lang.value || null,
      quality: selectedQuality(),
      embedded_subtitles: selectedEmbeddedSubtitles(),
      force_refresh: elements.forceRefresh.checked
    };
    const idempotencyKey = submissionKey(payload);
    const params = new URLSearchParams({
      filename: file.name,
      format: payload.format,
      quality: payload.quality,
      embedded_subtitles: String(payload.embedded_subtitles),
      force_refresh: String(payload.force_refresh)
    });
    if (payload.lang) params.set("lang", payload.lang);

    state.current = null;
    state.currentPayload = payload;
    setBusy(true);
    elements.resultKicker.textContent = "本地视频任务";
    elements.resultTitle.textContent = "正在上传视频";
    elements.resultActions.hidden = true;
    elements.cancelJob.textContent = "取消上传";
    elements.cancelJob.hidden = false;
    showStatus("processing", "正在上传视频", `正在发送 ${formatBytes(file.size)}`, 2, "…");

    const xhr = new XMLHttpRequest();
    state.uploadXhr = xhr;
    xhr.open("POST", `/api/upload-jobs?${params.toString()}`);
    xhr.withCredentials = true;
    xhr.setRequestHeader("Idempotency-Key", idempotencyKey);
    xhr.upload.addEventListener("progress", (event) => {
      if (!event.lengthComputable || state.uploadXhr !== xhr) return;
      const percent = Math.min(100, Math.max(2, Math.round((event.loaded / event.total) * 100)));
      elements.extractButtonLabel.textContent = `上传 ${percent}%`;
      showStatus(
        "processing",
        `正在上传视频 ${percent}%`,
        `已发送 ${formatBytes(event.loaded)} / ${formatBytes(event.total)}`,
        percent,
        "…"
      );
      elements.cancelJob.hidden = false;
    });
    xhr.addEventListener("load", () => {
      if (state.uploadXhr !== xhr) return;
      state.uploadXhr = null;
      elements.cancelJob.textContent = "取消排队";
      let data = {};
      try {
        data = JSON.parse(xhr.responseText || "{}");
      } catch (_) {
        data = {};
      }
      if (xhr.status === 401) {
        window.location.replace("/login");
        return;
      }
      if (xhr.status < 200 || xhr.status >= 300) {
        state.submissionKey = null;
        state.submissionSignature = null;
        finishWithError(data, xhr.status);
        return;
      }
      stopPolling();
      state.jobId = data.id;
      state.submissionKey = null;
      state.submissionSignature = null;
      if (data.status === "queued" || data.status === "running") saveActiveJob();
      handleJob(data);
      if (state.jobId && state.busy) state.pollTimer = setTimeout(pollJob, 700);
    });
    xhr.addEventListener("error", () => {
      if (state.uploadXhr !== xhr) return;
      state.uploadXhr = null;
      elements.cancelJob.textContent = "取消排队";
      finishWithError({ reason: "network_error", message: "视频上传失败，请检查网络。" }, 0);
    });
    xhr.addEventListener("abort", () => {
      if (state.uploadXhr !== xhr) return;
      state.uploadXhr = null;
      state.submissionKey = null;
      state.submissionSignature = null;
      elements.cancelJob.textContent = "取消排队";
      elements.cancelJob.hidden = true;
      elements.resultTitle.textContent = "上传已取消";
      showStatus("idle", "上传已取消", "可以重新选择视频后提交", NaN, "CC");
      setBusy(false);
    });
    xhr.send(file);
  }

  async function cancelCurrentJob() {
    if (state.uploadXhr) {
      state.uploadXhr.abort();
      return;
    }
    if (!state.jobId) return;
    elements.cancelJob.disabled = true;
    try {
      const response = await apiFetch(`/api/jobs/${encodeURIComponent(state.jobId)}`, { method: "DELETE" });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        showToast(friendlyError(data, response.status), true);
        return;
      }
      handleJob(data);
    } catch (_) {
      showToast("取消请求没有送达，请稍后重试。", true);
    } finally {
      elements.cancelJob.disabled = false;
    }
  }

  function showToast(message, error) {
    if (state.toastTimer) clearTimeout(state.toastTimer);
    elements.toast.textContent = message;
    elements.toast.classList.toggle("error", Boolean(error));
    elements.toast.classList.add("visible");
    state.toastTimer = setTimeout(() => elements.toast.classList.remove("visible"), 2600);
  }

  async function copyResult() {
    if (!state.current || state.current.kind === "media") return;
    try {
      await navigator.clipboard.writeText(state.current.content);
    } catch (_) {
      const helper = document.createElement("textarea");
      helper.value = state.current.content;
      helper.style.position = "fixed";
      helper.style.opacity = "0";
      document.body.appendChild(helper);
      helper.select();
      document.execCommand("copy");
      helper.remove();
    }
    showToast("已复制全部字幕", false);
  }

  function downloadResult() {
    if (!state.current) return;
    if (state.current.kind === "media") {
      if (!state.current.downloadUrl) {
        showToast("下载文件已失效，请重新提取。", true);
        return;
      }
      const link = document.createElement("a");
      link.href = state.current.downloadUrl;
      link.download = state.current.filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      showToast("已开始下载", false);
      return;
    }
    const blob = new Blob([state.current.content], { type: state.current.contentType });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = state.current.filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    showToast("已开始下载", false);
  }

  async function pasteInput() {
    try {
      const text = await navigator.clipboard.readText();
      if (!text) throw new Error("empty");
      elements.input.value = text.trim();
      validateInput();
      elements.input.focus();
    } catch (_) {
      showToast("无法读取剪贴板，请手动粘贴。", true);
    }
  }

  async function loadHealth() {
    try {
      const response = await fetch("/api/health", { cache: "no-store" });
      if (!response.ok) throw new Error(String(response.status));
      state.health = await response.json();
      const jobs = state.health.jobs || {};
      elements.serviceState.className = "service-state online";
      elements.serviceLabel.textContent = jobs.running || jobs.queued
        ? `队列 ${Number(jobs.running || 0) + Number(jobs.queued || 0)}/${jobs.max_pending || 8}`
        : "服务在线";
      const platforms = state.health.platforms || {};
      elements.bilibiliChip.classList.toggle("unavailable", platforms.bilibili && platforms.bilibili.status !== "ready");
      elements.douyinChip.classList.toggle(
        "unavailable",
        !platforms.douyin || platforms.douyin.enabled === false || platforms.douyin.status !== "ready"
      );
      const uploads = state.health.uploads || {};
      const uploadsEnabled = uploads.enabled !== false;
      state.uploadMaxBytes = Number(uploads.max_bytes || state.uploadMaxBytes);
      state.uploadExtensions = Array.isArray(uploads.allowed_extensions) ? uploads.allowed_extensions : [];
      elements.uploadLimit.textContent = `最大 ${formatBytes(state.uploadMaxBytes)}`;
      elements.uploadChip.classList.toggle("unavailable", !uploadsEnabled);
      const media = state.health.media || {};
      state.mediaEnabled = media.enabled !== false;
      state.mediaMaxBytes = Number(media.max_bytes || state.mediaMaxBytes);
      if (!state.mediaEnabled && selectedOperation() !== "subtitle") setSelectedOperation("subtitle");
      if (!uploadsEnabled && selectedInputMode() === "upload") setInputMode("link");
      else syncInputMode();
      elements.loginSection.hidden = !state.health.web_qr_login_enabled;
    } catch (_) {
      elements.serviceState.className = "service-state offline";
      elements.serviceLabel.textContent = "服务异常";
      elements.bilibiliChip.classList.add("unavailable");
      elements.douyinChip.classList.add("unavailable");
      elements.uploadChip.classList.add("unavailable");
      state.mediaEnabled = false;
      if (selectedOperation() !== "subtitle") setSelectedOperation("subtitle");
      syncInputMode();
    }
  }

  function stopLoginPolling() {
    if (state.loginPollTimer) clearInterval(state.loginPollTimer);
    state.loginPollTimer = null;
  }

  async function pollLogin(key) {
    const response = await apiFetch(`/api/login/poll?qrcode_key=${encodeURIComponent(key)}`);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      stopLoginPolling();
      elements.loginStatus.textContent = data.detail || "登录轮询失败";
      return;
    }
    if (data.status === "success") {
      stopLoginPolling();
      elements.qrImage.style.display = "none";
      elements.loginStatus.textContent = "登录态已保存。";
      loadHealth();
    } else if (data.status === "waiting_confirm") {
      elements.loginStatus.textContent = "已扫码，等待手机确认。";
    } else if (data.status === "expired") {
      stopLoginPolling();
      elements.qrImage.style.display = "none";
      elements.loginStatus.textContent = "二维码已过期。";
    } else {
      elements.loginStatus.textContent = "等待扫码。";
    }
  }

  async function startLogin() {
    stopLoginPolling();
    elements.qrImage.style.display = "none";
    elements.loginStatus.textContent = "正在生成二维码...";
    const response = await apiFetch("/api/login/qrcode", { method: "POST" });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      elements.loginStatus.textContent = data.detail || "二维码生成失败";
      return;
    }
    elements.qrImage.src = data.qr_svg_data_url;
    elements.qrImage.style.display = "block";
    elements.loginStatus.textContent = "等待扫码。";
    state.loginPollTimer = setInterval(() => pollLogin(data.qrcode_key), 2000);
  }

  elements.form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (selectedInputMode() === "upload") runUpload();
    else runExtraction();
  });
  elements.form.querySelectorAll('input[name="input-mode"]').forEach((radio) => {
    radio.addEventListener("change", syncInputMode);
  });
  elements.form.querySelectorAll('input[name="operation"]').forEach((radio) => {
    radio.addEventListener("change", syncInputMode);
  });
  elements.form.querySelectorAll('input[name="quality"]').forEach((radio) => {
    radio.addEventListener("change", syncPrecisionOptions);
  });
  elements.embeddedSubtitles.addEventListener("change", () => {
    if (elements.embeddedSubtitles.checked) {
      setSelectedQuality("accurate");
      setSelectedSource("auto");
    }
    syncInputMode();
  });
  elements.input.addEventListener("input", () => {
    updatePlatformDetect();
    if (elements.input.classList.contains("invalid")) validateInput();
  });
  elements.input.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
      event.preventDefault();
      if (selectedInputMode() === "link") runExtraction();
    }
  });
  elements.videoFile.addEventListener("change", () => {
    const file = elements.videoFile.files && elements.videoFile.files[0];
    if (file) setUploadFile(file);
  });
  ["dragenter", "dragover"].forEach((eventName) => {
    elements.uploadDropzone.addEventListener(eventName, (event) => {
      event.preventDefault();
      if (!state.busy) elements.uploadDropzone.classList.add("dragging");
    });
  });
  ["dragleave", "drop"].forEach((eventName) => {
    elements.uploadDropzone.addEventListener(eventName, (event) => {
      event.preventDefault();
      elements.uploadDropzone.classList.remove("dragging");
    });
  });
  elements.uploadDropzone.addEventListener("drop", (event) => {
    if (state.busy) return;
    const file = event.dataTransfer && event.dataTransfer.files && event.dataTransfer.files[0];
    if (file) setUploadFile(file);
  });
  elements.paste.addEventListener("click", pasteInput);
  elements.clearInput.addEventListener("click", () => {
    if (selectedInputMode() === "upload") {
      setUploadFile(null);
      return;
    }
    elements.input.value = "";
    elements.inputError.textContent = "";
    elements.input.classList.remove("invalid");
    updatePlatformDetect();
    elements.input.focus();
  });
  elements.copyResult.addEventListener("click", copyResult);
  elements.downloadResult.addEventListener("click", downloadResult);
  elements.cancelJob.addEventListener("click", cancelCurrentJob);
  elements.format.addEventListener("change", () => {
    if (selectedOperation() === "subtitle" && selectedInputMode() === "link" && !state.busy && state.current && state.current.input === elements.input.value.trim()) {
      runExtraction({ force_refresh: false });
    }
  });
  elements.clearHistory.addEventListener("click", () => {
    state.history = [];
    saveHistory();
    renderHistory();
  });
  elements.loginStart.addEventListener("click", startLogin);
  elements.logoutAccount.addEventListener("click", logoutAccount);

  renderHistory();
  updatePlatformDetect();
  syncInputMode();
  loadAccount();
  loadHealth();
  setInterval(loadHealth, 30000);
})();
