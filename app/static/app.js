(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const elements = {
    form: $("extract-form"),
    input: $("video-input"),
    inputError: $("input-error"),
    paste: $("paste-input"),
    clearInput: $("clear-input"),
    newTask: $("new-task"),
    taskHeading: $("task-heading"),
    platformDetect: $("platform-detect"),
    platformNotice: $("platform-notice"),
    platformNoticeTitle: $("platform-notice-title"),
    platformNoticeDetail: $("platform-notice-detail"),
    platformNoticeAction: $("platform-notice-action"),
    pageSelectorRow: $("page-selector-row"),
    pageSelect: $("page-select"),
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
    privacyNote: $("privacy-note"),
    asrAutoTitle: $("asr-auto-title"),
    asrAutoDetail: $("asr-auto-detail"),
    embeddedSubtitleRow: $("embedded-subtitle-row"),
    embeddedSubtitles: $("embedded-subtitles"),
    subtitleFormatGrid: $("subtitle-format-grid"),
    platformAiRow: $("platform-ai-row"),
    format: $("format-select"),
    lang: $("lang-select"),
    hotwordsRow: $("hotwords-row"),
    hotwords: $("hotwords-input"),
    allowPlatformAi: $("allow-platform-ai"),
    forceRefresh: $("force-refresh"),
    forceRefreshLabel: $("force-refresh-label"),
    forceRefreshHint: $("force-refresh-hint"),
    extractButton: $("extract-button"),
    extractButtonLabel: $("extract-button-label"),
    serviceState: $("health-trigger"),
    serviceLabel: $("service-label"),
    healthTrigger: $("health-trigger"),
    healthPopover: $("health-popover"),
    healthSummary: $("health-summary"),
    healthBilibili: $("health-bilibili"),
    healthDouyin: $("health-douyin"),
    healthLocal: $("health-local"),
    healthCloud: $("health-cloud"),
    healthFiles: $("health-files"),
    bilibiliChip: $("bilibili-chip"),
    douyinChip: $("douyin-chip"),
    uploadChip: $("upload-chip"),
    themeToggle: $("theme-toggle"),
    accountArea: $("account-area"),
    accountAvatar: $("account-avatar"),
    accountAvatarLarge: $("account-avatar-large"),
    accountName: $("account-name"),
    accountTrigger: $("account-trigger"),
    accountPopover: $("account-popover"),
    accountPopoverName: $("account-popover-name"),
    accountCreatedAt: $("account-created-at"),
    accountSessionSummary: $("account-session-summary"),
    accountQuota: $("account-quota"),
    accountQuotaLabel: $("account-quota-label"),
    accountQuotaBar: $("account-quota-bar"),
    accountCode: $("account-code"),
    adminLink: $("admin-link"),
    logoutAllDevices: $("logout-all-devices"),
    logoutAccount: $("logout-account"),
    cloudModeZone: $("cloud-mode-zone"),
    cloudSelectionLabel: $("cloud-selection-label"),
    cloudRoutingNote: $("cloud-routing-note"),
    cloudConfirmRoute: $("cloud-confirm-route"),
    cloudConfirmDialog: $("cloud-confirm-dialog"),
    cloudConfirmModel: $("cloud-confirm-model"),
    cloudConfirmCheck: $("cloud-confirm-check"),
    closeCloudConfirm: $("close-cloud-confirm"),
    cancelCloudConfirm: $("cancel-cloud-confirm"),
    submitCloudConfirm: $("submit-cloud-confirm"),
    resultKicker: $("result-kicker"),
    resultTitle: $("result-title"),
    resultActions: $("result-actions"),
    retryAccurate: $("retry-accurate"),
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
    stageTrack: $("stage-track"),
    metadataStrip: $("metadata-strip"),
    notice: $("result-notice"),
    idleOutput: $("idle-output"),
    idleFormat: $("idle-format"),
    idleTitle: $("idle-title"),
    idleDetail: $("idle-detail"),
    retryTask: $("retry-task"),
    outputShell: $("output-shell"),
    output: $("output"),
    segmentList: $("segment-list"),
    segmentTimeline: $("segment-timeline"),
    viewSegments: $("view-segments"),
    viewSource: $("view-source"),
    outputFormat: $("output-format-label"),
    resultFormat: $("result-format"),
    outputStats: $("output-stats-label"),
    resultSearch: $("result-search"),
    searchCount: $("search-count"),
    toggleRaw: $("toggle-raw"),
    toggleWrap: $("toggle-wrap"),
    mediaResult: $("media-result"),
    mediaFileMark: $("media-file-mark"),
    mediaFilename: $("media-filename"),
    mediaFileDetail: $("media-file-detail"),
    openHistory: $("open-history"),
    historyCount: $("history-count"),
    historyDrawer: $("history-drawer"),
    historyList: $("history-list"),
    historyCaption: $("history-caption"),
    refreshHistory: $("refresh-history"),
    closeHistory: $("close-history"),
    resultExpiry: $("result-expiry"),
    settingsSummary: $("settings-summary"),
    composerPane: $("composer-pane"),
    resultPane: $("result-pane"),
    mobileCompose: $("mobile-tab-compose"),
    mobileResult: $("mobile-tab-result"),
    mobileResultDot: $("mobile-result-dot"),
    toast: $("toast")
  };

  const state = {
    busy: false,
    startedAt: 0,
    elapsedTimer: null,
    pollTimer: null,
    pollController: null,
    pollFailures: 0,
    pollPaused: false,
    searchTimer: null,
    toastTimer: null,
    uploadXhr: null,
    uploadFile: null,
    jobId: null,
    submissionKey: null,
    submissionSignature: null,
    currentPayload: null,
    current: null,
    resuming: false,
    user: null,
    capabilities: null,
    healthLoading: false,
    history: [],
    historyError: false,
    historyController: null,
    retentionSeconds: 86400,
    uploadMaxBytes: 512 * 1024 * 1024,
    uploadExtensions: [],
    mediaEnabled: true,
    wrapOutput: true,
    resultView: "segments",
    mobileView: "compose",
    preferencesLoaded: false,
    pageLookupTimer: null,
    pageLookupVersion: 0,
    biliBaseUrl: "",
    pendingCloudAction: null,
    dialogReturnFocus: null
  };

  const sourceLabels = {
    official_no_cookie: "平台字幕",
    official_with_cookie: "平台字幕",
    asr_local: "本地语音识别",
    asr_aliyun: "百炼语音识别",
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
    asr_worker_crashed: "基础识别意外中断，请稍后重试。",
    asr_model_download_failed: "基础识别暂不可用，请稍后重试。",
    download_failed: "视频、音频或字幕下载失败，请稍后重试。",
    asr_failed: "本地语音识别失败，请稍后重试。",
    asr_provider_not_configured: "云端语音识别尚未完成配置。",
    asr_provider_auth_failed: "云端语音识别凭证无效或模型权限不足。",
    asr_provider_unavailable: "云端语音识别暂时不可用，请稍后重试。",
    asr_provider_rejected: "云端语音识别无法处理这个音频。",
    asr_provider_failed: "云端语音识别任务失败，请稍后重试。",
    asr_provider_response_invalid: "云端语音识别返回的数据异常。",
    asr_result_download_failed: "识别已完成，但结果下载失败，请重试。",
    asr_audio_fetch_failed: "云端服务暂时无法读取音频，请稍后重试。",
    asr_rate_limited: "云端请求过于频繁，请稍后重试。",
    asr_quota_exhausted: "免费额度已用尽，系统没有继续产生付费调用。",
    asr_daily_limit_reached: "今天的云端识别额度已用尽。",
    asr_monthly_limit_reached: "本月的云端识别额度已用尽。",
    asr_total_limit_reached: "云端识别总免费额度保护线已达到。",
    asr_user_daily_limit_reached: "你今天可使用的识别时长已用尽。",
    ocr_missing: "画面字幕识别组件尚未准备完成。",
    ocr_failed: "画面字幕识别失败，可取消画面字幕选项后改用语音识别。",
    ocr_empty: "没有在视频画面中识别到稳定字幕。",
    ocr_timeout: "画面字幕识别超时，请尝试更短的视频。",
    platform_temporarily_unavailable: "平台暂时拒绝了视频请求，请稍后重试。",
    platform_unreachable: "暂时无法连接视频平台，请稍后重试。",
    platform_blocked: "B站当前拒绝了本站的访问（平台风控）。可以改为上传本地视频，或稍后再试。",
    douyin_browser_missing: "抖音处理组件尚未准备完成。",
    douyin_browser_busy: "抖音浏览器资源正忙，请稍后重试。",
    douyin_adapter_missing: "抖音处理组件尚未准备完成。",
    unsupported_upload_format: "暂不支持这种视频格式。",
    invalid_upload_media: "无法读取这个视频，请换一个文件。",
    upload_video_missing: "选择的文件不包含视频画面。",
    upload_audio_missing: "这个视频没有可识别的音轨。",
    upload_too_large: "视频文件超过当前上传限制。",
    upload_storage_busy: "上传空间正忙，请稍后再试。",
    upload_interrupted: "视频上传中断，请重试。",
    upload_expired: "上传视频已过期，请重新选择。",
    media_storage_busy: "媒体处理空间正忙，请稍后再试。",
    media_too_large: "媒体文件超过当前下载限制。",
    video_stream_missing: "没有找到可下载的视频画面。",
    audio_stream_missing: "没有找到可提取的音轨。",
    media_convert_failed: "音频转换失败，请稍后重试。",
    ffmpeg_failed: "媒体探测或转换失败，请确认文件可正常播放。",
    disk_space_low: "处理空间暂时不足，请稍后重试。",
    no_audio_stream: "视频没有音轨，无法识别语音或生成 MP3。",
    subtitle_unavailable: "没有找到可读取的字幕或语音内容。",
    job_queue_full: "任务队列已满，请稍后重试。",
    job_expired: "服务可能已重启或任务已过期，请重新提交。",
    artifact_expired: "下载文件已过期，请重新提取。",
    artifact_not_found: "下载文件不存在或已过期。",
    job_not_found: "服务可能已重启或任务已过期，请重新提交。",
    idempotency_conflict: "这次提交与上一次请求不一致，请重新提交。",
    authentication_required: "访问凭据已失效，正在返回验证页。",
    media_duration_too_long: "视频时长超过当前媒体提取限制。",
    cloud_consent_required: "请先确认云端识别会消耗站点额度。",
    daily_quota_reached: "今天的任务额度已用完，零点后重置。",
    member_busy: "你已有任务在处理，等它们完成后再提交。",
    cookie_expired: "站点的 B站登录已失效，请联系站长重新扫码。"
  };

  const stageDetails = {
    starting: "处理线程已接收任务",
    validating: "正在校验视频内容",
    cache: "正在查找可复用的处理结果",
    discover: "正在查找平台字幕与语言轨道",
    platform: "正在读取视频信息与音轨",
    checking_existing_subtitle: "正在检查平台已有字幕",
    downloading_audio: "正在下载并校验音轨",
    preprocessing: "正在生成临时识别音频",
    waiting_for_provider: "正在向云端提交识别任务",
    transcribing: "云端正在识别音频",
    postprocessing: "正在整理识别时间轴",
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

  /* Visual effects live in fx.js and listen for these events; the
     workspace keeps working when that script is missing or motion is off. */
  function fx(name, detail) {
    document.dispatchEvent(new CustomEvent(`workspace:${name}`, { detail: detail || {} }));
  }

  const THEME_KEY = "video-workspace-theme";
  const THEME_MODES = ["system", "light", "dark"];
  const THEME_LABELS = { system: "跟随系统", light: "浅色", dark: "深色" };

  /* ---------- Local storage ---------- */

  function historyStorageKey(userId) {
    return `video-workspace-history-v4:${userId}`;
  }

  function preferencesStorageKey(userId) {
    return `video-workspace-preferences-v1:${userId}`;
  }

  function activeJobStorageKey(userId) {
    return `caption-active-job-v1:${userId}`;
  }

  function storageOwnerKey() {
    return state.user ? String(state.user.id) : "pending";
  }

  function loadPreferences(userId) {
    let value = {};
    try {
      value = JSON.parse(localStorage.getItem(preferencesStorageKey(userId)) || "{}");
    } catch (_) {
      value = {};
    }
    if (!value || typeof value !== "object" || Array.isArray(value)) value = {};
    const operation = ["subtitle", "video", "audio"].includes(value.operation)
      ? value.operation
      : state.user ? "subtitle" : "video";
    setSelectedOperation(!state.user && operation === "subtitle" ? "video" : operation);
    setInputMode(state.user && value.inputMode === "upload" ? "upload" : "link");
    setSelectedSource(["auto", "official", "asr"].includes(value.source) ? value.source : "auto");
    setSelectedAsrMode(["auto", "high_accuracy", "economy"].includes(value.asrMode) ? value.asrMode : "auto");
    if (["txt", "srt", "vtt", "markdown", "json"].includes(value.format)) elements.format.value = value.format;
    elements.lang.value = ["", "zh", "en", "ja", "ko"].includes(value.lang) ? value.lang : "zh";
    elements.embeddedSubtitles.checked = value.embeddedSubtitles === true;
    elements.allowPlatformAi.checked = value.allowPlatformAi !== false;
    state.wrapOutput = value.wrapOutput !== false;
    state.resultView = value.resultView === "source" ? "source" : "segments";
    applyWrapPreference();
    state.preferencesLoaded = true;
    syncInputMode();
  }

  function savePreferences() {
    updateSettingsSummary();
    if (!state.preferencesLoaded) return;
    const value = {
      operation: selectedOperation(),
      inputMode: selectedInputMode(),
      source: selectedSource(),
      quality: "balanced",
      asrMode: selectedAsrMode(),
      format: elements.format.value,
      lang: elements.lang.value,
      embeddedSubtitles: selectedEmbeddedSubtitles(),
      allowPlatformAi: elements.allowPlatformAi.checked,
      wrapOutput: state.wrapOutput,
      resultView: state.resultView
    };
    try {
      localStorage.setItem(preferencesStorageKey(storageOwnerKey()), JSON.stringify(value));
    } catch (_) {
      return;
    }
  }

  function removeLegacyHistory(userId) {
    try {
      localStorage.removeItem(historyStorageKey(userId));
    } catch (_) {
      return;
    }
  }

  function clearActiveJob() {
    try {
      localStorage.removeItem(activeJobStorageKey(storageOwnerKey()));
    } catch (_) {
      return;
    }
  }

  function saveActiveJob() {
    if (!state.jobId || !state.currentPayload) return;
    try {
      const persistedPayload = Object.assign({}, state.currentPayload);
      delete persistedPayload.hotwords;
      localStorage.setItem(activeJobStorageKey(storageOwnerKey()), JSON.stringify({
        jobId: state.jobId,
        payload: persistedPayload,
        startedAt: state.startedAt || Date.now(),
        savedAt: Date.now()
      }));
    } catch (_) {
      return;
    }
  }

  /* ---------- Theme ---------- */

  function storedTheme() {
    try {
      const value = localStorage.getItem(THEME_KEY);
      return value === "light" || value === "dark" ? value : "system";
    } catch (_) {
      return "system";
    }
  }

  function applyTheme(mode) {
    const root = document.documentElement;
    if (mode === "light" || mode === "dark") root.dataset.theme = mode;
    else delete root.dataset.theme;
    elements.themeToggle.dataset.mode = mode;
    elements.themeToggle.title = `外观：${THEME_LABELS[mode]}`;
    elements.themeToggle.setAttribute("aria-label", `切换外观，当前${THEME_LABELS[mode]}`);
    document.querySelectorAll('meta[name="theme-color"]').forEach((meta) => {
      if (!meta.dataset.original) meta.dataset.original = meta.getAttribute("content") || "";
      const forced = mode === "dark" ? "#07060d" : mode === "light" ? "#f6f4fb" : "";
      meta.setAttribute("content", forced || meta.dataset.original);
    });
  }

  function cycleTheme() {
    const next = THEME_MODES[(THEME_MODES.indexOf(storedTheme()) + 1) % THEME_MODES.length];
    try {
      if (next === "system") localStorage.removeItem(THEME_KEY);
      else localStorage.setItem(THEME_KEY, next);
    } catch (_) {
      /* the choice still applies to this page */
    }
    const apply = () => applyTheme(next);
    if (window.FX && typeof window.FX.themeTransition === "function") {
      window.FX.themeTransition(apply, elements.themeToggle);
    } else {
      apply();
    }
    showToast(`外观：${THEME_LABELS[next]}`, false);
  }

  /* ---------- Active job restore ---------- */

  function restoreForm(payload) {
    if (!payload) return;
    setSelectedOperation(payload.kind === "media" ? payload.media_type : "subtitle");
    setInputMode(payload.kind === "upload" ? "upload" : "link");
    if (payload.kind !== "media") {
      elements.format.value = payload.format || "txt";
      elements.lang.value = payload.lang || "zh";
      elements.hotwords.value = payload.hotwords || "";
      setSelectedAsrMode(payload.asr_mode || "auto");
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
    if (payload.kind !== "media") setSelectedSource(payload.source || "auto");
    updatePlatformDetect();
    schedulePageLookup();
    syncInputMode();
  }

  function resumeActiveJob() {
    if (state.busy) return;
    let saved;
    try {
      saved = JSON.parse(localStorage.getItem(activeJobStorageKey(storageOwnerKey())) || "null");
    } catch (_) {
      clearActiveJob();
      return;
    }
    if (!saved || !saved.jobId || !saved.payload || Date.now() - Number(saved.savedAt || 0) > 86400 * 1000) {
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
    showStatus("processing", "正在恢复任务", "正在读取最新处理进度", 4, "…");
    pollJob();
  }

  /* ---------- Account ---------- */

  async function apiFetch(url, options) {
    const response = await fetch(url, options);
    if (response.status === 401) {
      clearActiveJob();
      window.location.replace("/login");
    }
    return response;
  }

  function formatAccountDate(timestamp) {
    const value = Number(timestamp || 0);
    if (!value) return "首次登录";
    return new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "short", day: "numeric" })
      .format(new Date(value * 1000));
  }

  function setAccountMenu(open) {
    const visible = Boolean(open) && !elements.accountTrigger.disabled;
    elements.accountPopover.hidden = !visible;
    elements.accountTrigger.setAttribute("aria-expanded", String(visible));
  }

  function applyAccessState() {
    elements.accountArea.hidden = !state.user;
    elements.adminLink.hidden = !state.user || !state.user.is_admin;
    document.body.classList.toggle("is-owner", Boolean(state.user && state.user.is_admin));
    syncInputMode();
  }

  function formatReset(seconds) {
    const value = Math.max(0, Number(seconds || 0));
    if (value >= 3600) return `${Math.floor(value / 3600)} 小时后重置`;
    return `${Math.max(1, Math.ceil(value / 60))} 分钟后重置`;
  }

  function renderQuota(quota) {
    const data = quota || {};
    const limit = Number(data.limit || 0);
    const used = Math.max(0, Number(data.used || 0));
    elements.accountQuota.hidden = false;
    if (!limit) {
      elements.accountQuotaLabel.textContent = `今日已提交 ${used} 个任务 · 不限次数`;
      elements.accountQuotaBar.style.setProperty("--quota", "0");
      elements.accountQuota.classList.remove("low");
      return;
    }
    const ratio = Math.min(1, used / limit);
    elements.accountQuotaLabel.textContent = `今日 ${used} / ${limit} 次 · ${formatReset(data.resets_in)}`;
    elements.accountQuotaBar.style.setProperty("--quota", ratio.toFixed(3));
    elements.accountQuota.classList.toggle("low", limit - used <= Math.max(1, Math.round(limit * 0.15)));
  }

  function syncBodyLock() {
    document.body.classList.toggle(
      "dialog-open",
      !elements.cloudConfirmDialog.hidden
    );
    document.body.classList.toggle("drawer-open", !elements.historyDrawer.hidden);
  }

  function setCloudConfirmDialog(open, resetMode) {
    const visible = Boolean(open);
    if (visible && elements.cloudConfirmDialog.hidden) {
      state.dialogReturnFocus = document.activeElement && document.activeElement.tagName === "BUTTON"
        ? document.activeElement : elements.extractButton;
    }
    elements.cloudConfirmDialog.hidden = !visible;
    syncBodyLock();
    if (!visible) {
      state.pendingCloudAction = null;
      elements.cloudConfirmCheck.checked = false;
      elements.submitCloudConfirm.disabled = true;
      if (resetMode) {
        setSelectedAsrMode("auto");
        syncPrecisionOptions();
        savePreferences();
      }
      restoreDialogFocus();
      return;
    }
    setAccountMenu(false);
    elements.cloudConfirmCheck.checked = false;
    elements.submitCloudConfirm.disabled = true;
    elements.cloudConfirmModel.textContent = selectedAsrMode() === "economy"
      ? "Paraformer · 经济模式"
      : "千问 ASR · 高精度";
    elements.cloudConfirmRoute.textContent = selectedInputMode() === "upload" || selectedSource() === "asr"
      ? "本次将使用云端识别，可能消耗计费额度。"
      : "优先使用平台字幕；仅在没有可用字幕时调用云端。";
    requestAnimationFrame(() => { if (!elements.cloudConfirmDialog.hidden) elements.cloudConfirmCheck.focus(); });
  }

  function requestCloudConfirmation(action) {
    if (!["high_accuracy", "economy"].includes(selectedAsrMode())) {
      action();
      return;
    }
    state.pendingCloudAction = action;
    setCloudConfirmDialog(true, false);
  }

  function confirmCloudAction() {
    if (!elements.cloudConfirmCheck.checked || !state.pendingCloudAction) return;
    const action = state.pendingCloudAction;
    state.pendingCloudAction = null;
    elements.cloudConfirmDialog.hidden = true;
    elements.cloudConfirmCheck.checked = false;
    elements.submitCloudConfirm.disabled = true;
    syncBodyLock();
    restoreDialogFocus();
    action();
  }

  function restoreDialogFocus() {
    const target = state.dialogReturnFocus;
    state.dialogReturnFocus = null;
    if (target && target.isConnected && !target.disabled) target.focus();
  }

  async function loadAccount() {
    try {
      const response = await fetch("/api/auth/me", { cache: "no-store" });
      const data = await response.json().catch(() => ({}));
      if (response.status === 401 || !data.user) {
        clearActiveJob();
        window.location.replace("/login");
        return false;
      }
      if (!response.ok) throw new Error(String(response.status));
      state.user = data.user;
      applyAccessState();
      const label = data.user.label || data.user.username || "成员";
      elements.accountName.textContent = label;
      const initial = Array.from(String(label))[0].toUpperCase();
      elements.accountAvatar.textContent = initial;
      elements.accountAvatarLarge.textContent = initial;
      elements.accountPopoverName.textContent = label;
      elements.accountCreatedAt.textContent = data.user.is_admin
        ? "站长 · 拥有全部权限"
        : `${formatAccountDate(data.user.created_at)} 获得邀请`;
      const sessions = Math.max(1, Number(data.user.active_sessions || 1));
      const devices = Math.max(sessions, Number(data.user.max_devices || sessions));
      elements.accountSessionSummary.textContent = `已在 ${sessions} / ${devices} 台设备上验证`;
      elements.accountCode.textContent = data.user.code_hint
        ? `激活码 ···${data.user.code_hint}${data.user.code_expires_at
          ? ` · ${formatAccountDate(data.user.code_expires_at)} 到期` : " · 长期有效"}`
        : "";
      renderQuota(data.user.quota);
      elements.accountTrigger.disabled = false;
      elements.accountArea.setAttribute("aria-busy", "false");
      loadPreferences(data.user.id);
      removeLegacyHistory(data.user.id);
      loadHistory();
      renderHistory();
      if (state.jobId && state.busy) saveActiveJob();
      else resumeActiveJob();
      return true;
    } catch (_) {
      elements.accountName.textContent = "连接失败";
      return false;
    }
  }

  async function logoutAccount() {
    elements.accountTrigger.disabled = true;
    try {
      const response = await apiFetch("/api/auth/logout", { method: "POST" });
      if (!response.ok) throw new Error(String(response.status));
      clearActiveJob();
      window.location.replace("/login");
    } catch (_) {
      elements.accountTrigger.disabled = false;
      showToast("退出失败，请检查网络后重试。", true);
    }
  }

  async function logoutAllDevices() {
    if (!window.confirm("确定退出全部设备吗？之后每台设备都要重新输入激活码。")) return;
    elements.logoutAllDevices.disabled = true;
    try {
      const response = await apiFetch("/api/auth/logout-all", { method: "POST" });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(friendlyError(data, response.status));
      clearActiveJob();
      window.location.replace("/login");
    } catch (error) {
      elements.logoutAllDevices.disabled = false;
      showToast(error.message || "无法退出全部设备，请稍后重试。", true);
    }
  }

  /* ---------- Form state ---------- */

  function selectedSource() {
    const selected = elements.form.querySelector('input[name="source"]:checked');
    return selected ? selected.value : "auto";
  }

  function selectedQuality() {
    return "balanced";
  }

  function selectedAsrMode() {
    const selected = elements.form.querySelector('input[name="asr-mode"]:checked');
    return selected ? selected.value : "auto";
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

  function uploadsEnabled() {
    return !state.capabilities
      || !state.capabilities.uploads
      || state.capabilities.uploads.enabled !== false;
  }

  function setMobileView(view) {
    const next = view === "result" ? "result" : "compose";
    state.mobileView = next;
    document.body.classList.toggle("view-compose", next === "compose");
    document.body.classList.toggle("view-result", next === "result");
    elements.mobileCompose.setAttribute("aria-pressed", String(next === "compose"));
    elements.mobileResult.setAttribute("aria-pressed", String(next === "result"));
    if (next === "result") elements.mobileResultDot.hidden = true;
  }

  function applyWrapPreference() {
    elements.output.classList.toggle("wrap", state.wrapOutput);
    elements.toggleWrap.classList.toggle("active", state.wrapOutput);
    elements.toggleWrap.setAttribute("aria-pressed", String(state.wrapOutput));
    elements.toggleWrap.title = state.wrapOutput ? "关闭自动换行" : "开启自动换行";
  }

  function updateSubmitLabel() {
    if (state.busy) return;
    const operation = selectedOperation();
    const unavailable = operation !== "subtitle" && !state.mediaEnabled;
    elements.extractButton.disabled = unavailable;
    elements.taskHeading.textContent = operation === "video"
      ? "提取视频"
      : operation === "audio" ? "提取音频" : "提取字幕";
    elements.extractButtonLabel.textContent = unavailable
      ? "当前暂不可用"
      : operation === "video"
        ? "提取视频"
        : operation === "audio"
          ? "提取音频"
          : selectedInputMode() === "upload" ? "开始识别" : "开始提取";
  }

  function syncInputMode() {
    updateSettingsSummary();
    const operation = selectedOperation();
    const mediaMode = operation !== "subtitle";
    document.body.dataset.operation = operation;
    const linkRadio = elements.form.querySelector('input[name="input-mode"][value="link"]');
    const uploadRadio = elements.form.querySelector('input[name="input-mode"][value="upload"]');
    if (mediaMode && uploadRadio.checked) linkRadio.checked = true;
    const uploadMode = !mediaMode && selectedInputMode() === "upload";
    const canUpload = uploadsEnabled();
    elements.inputModeGroup.hidden = mediaMode;
    elements.linkInputPanel.hidden = uploadMode;
    elements.uploadInputPanel.hidden = !uploadMode;
    elements.sourceFieldGroup.hidden = uploadMode || mediaMode;
    elements.subtitleFormatGrid.hidden = mediaMode;
    elements.privacyNote.hidden = mediaMode;
    elements.platformAiRow.hidden = uploadMode || mediaMode || elements.embeddedSubtitles.checked;
    elements.input.required = !uploadMode;
    elements.input.disabled = state.busy;
    elements.paste.disabled = state.busy;
    elements.clearInput.disabled = state.busy;
    elements.newTask.disabled = state.busy;
    elements.format.disabled = state.busy;
    elements.lang.disabled = state.busy;
    elements.forceRefresh.disabled = state.busy;
    elements.clearInput.title = "清空输入";
    uploadRadio.disabled = state.busy || mediaMode || !canUpload;
    linkRadio.disabled = state.busy;
    elements.videoFile.disabled = state.busy || !canUpload;
    elements.form.querySelectorAll('input[name="operation"]').forEach((radio) => {
      radio.disabled = state.busy || (radio.value !== "subtitle" && !state.mediaEnabled);
    });
    elements.forceRefreshLabel.textContent = mediaMode ? "重新获取平台信息" : "忽略已有结果";
    elements.forceRefreshHint.textContent = mediaMode ? "不复用已有的视频解析信息" : "重新下载并处理视频";
    syncPrecisionOptions();
    updateSubmitLabel();
    updatePlatformNotice();
    syncEmptyState();
  }

  function syncEmptyState() {
    if (state.current || state.busy || ["error", "cancelled", "expired"].includes(elements.resultPane.dataset.state)) return;
    const operation = selectedOperation();
    const label = operation === "video" ? "视频" : operation === "audio" ? "音频" : "字幕";
    elements.idleTitle.textContent = `尚无${label}`;
    elements.idleFormat.textContent = operation === "video"
      ? "MP4" : operation === "audio" ? "MP3" : elements.format.value.toUpperCase();
    elements.idleDetail.textContent = "等待提交任务";
    elements.resultTitle.textContent = `${label}结果`;
  }

  function resetResult() {
    state.current = null;
    state.currentPayload = null;
    elements.resultPane.dataset.state = "idle";
    elements.resultActions.hidden = true;
    elements.statusPanel.hidden = true;
    elements.outputShell.hidden = true;
    elements.mediaResult.hidden = true;
    elements.metadataStrip.hidden = true;
    elements.notice.hidden = true;
    elements.resultExpiry.hidden = true;
    elements.retryTask.hidden = true;
    elements.output.textContent = "";
    elements.segmentList.textContent = "";
    elements.resultKicker.textContent = "任务结果";
    elements.idleOutput.hidden = false;
    elements.idleOutput.classList.remove("processing");
    syncEmptyState();
    renderHistory();
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

  function setSelectedAsrMode(value) {
    const radio = elements.form.querySelector(`input[name="asr-mode"][value="${value}"]`);
    if (radio) radio.checked = true;
  }

  function setSelectedOperation(value) {
    const radio = elements.form.querySelector(`input[name="operation"][value="${value}"]`);
    if (radio && !radio.disabled) radio.checked = true;
    syncInputMode();
  }

  function isLocalAsrReady() {
    if (!state.capabilities) return true;
    return Boolean(state.capabilities.features && state.capabilities.features.local_processing);
  }

  function updateSettingsSummary() {
    elements.settingsSummary.hidden = selectedOperation() !== "subtitle";
    const language = elements.lang.options[elements.lang.selectedIndex];
    elements.settingsSummary.textContent = `${language ? language.textContent : "中文"} · ${elements.format.value.toUpperCase()}`;
  }

  function syncPrecisionOptions() {
    const subtitleMode = selectedOperation() === "subtitle";
    const videoSubtitleReady = !state.capabilities
      || !state.capabilities.features
      || state.capabilities.features.embedded_subtitles !== false;
    elements.embeddedSubtitles.disabled = state.busy || !subtitleMode || !videoSubtitleReady;
    const embedded = subtitleMode && selectedEmbeddedSubtitles();
    if (embedded) setSelectedSource("auto");
    const officialOnly = subtitleMode && selectedInputMode() === "link" && selectedSource() === "official";
    if (officialOnly) setSelectedAsrMode("auto");
    elements.qualityFieldGroup.hidden = !subtitleMode || officialOnly;
    elements.embeddedSubtitleRow.hidden = !subtitleMode;
    const localReady = isLocalAsrReady();
    const cloudReady = Boolean(
      state.capabilities && state.capabilities.features && state.capabilities.features.cloud_enhancement
    );
    const autoBackend = state.capabilities && state.capabilities.asr_modes && state.capabilities.asr_modes.auto
      ? state.capabilities.asr_modes.auto.processing
      : null;
    const autoReady = !state.capabilities
      || Boolean(state.capabilities.asr_modes && state.capabilities.asr_modes.auto && state.capabilities.asr_modes.auto.available);
    const autoUsesLocal = !state.capabilities || autoBackend === "local";
    const autoRadio = elements.form.querySelector('input[name="asr-mode"][value="auto"]');
    elements.asrAutoTitle.textContent = autoUsesLocal ? "本地均衡" : "自动识别";
    elements.asrAutoDetail.textContent = autoUsesLocal ? "默认 · 兼顾速度与准确率" : "智能选择可用服务";
    elements.form.querySelectorAll('input[name="asr-mode"]').forEach((radio) => {
      const unavailable = radio.value === "auto" ? !autoReady : !cloudReady;
      radio.disabled = state.busy || !subtitleMode || unavailable;
    });
    if (state.capabilities && selectedAsrMode() !== "auto" && !cloudReady && autoRadio && !autoRadio.disabled) {
      autoRadio.checked = true;
    }
    elements.form.querySelectorAll('input[name="source"]').forEach((radio) => {
      radio.disabled = state.busy || embedded;
    });
    elements.allowPlatformAi.disabled = state.busy || embedded;
    elements.hotwords.disabled = state.busy || !subtitleMode;
    elements.hotwordsRow.hidden = !subtitleMode;
    const currentMode = selectedAsrMode();
    const cloudSelected = currentMode === "high_accuracy" || currentMode === "economy";
    elements.cloudSelectionLabel.textContent = currentMode === "high_accuracy"
      ? "千问 ASR · 已选择" : currentMode === "economy" ? "Paraformer · 已选择" : "云端增强";
    if (elements.cloudModeZone.dataset.selectedMode !== currentMode) {
      elements.cloudModeZone.open = cloudSelected;
      elements.cloudModeZone.dataset.selectedMode = currentMode;
    }
    elements.cloudRoutingNote.textContent = cloudReady
      ? "按音频时长消耗站点额度，提交前需确认。"
      : "云端服务暂不可用，基础识别仍可单独使用。";
    elements.cloudModeZone.classList.toggle("selected", cloudSelected);
    const currentModeReady = currentMode === "auto" ? autoReady : cloudReady;
    elements.qualityCaption.textContent = !currentModeReady
      ? "当前识别服务暂不可用，平台已有字幕仍可正常提取"
      : embedded
        ? "会下载视频并优先识别内嵌或烧录在画面中的字幕"
        : currentMode === "economy"
          ? "平台字幕优先；没有字幕时发送临时音频至 Paraformer"
          : currentMode === "high_accuracy"
            ? "平台字幕优先；没有字幕时发送临时音频至千问 ASR"
            : autoUsesLocal
              ? "先提取平台字幕，没有字幕时在本站内部均衡识别"
              : "先提取平台字幕，没有字幕时使用当前可用识别服务";
    if (currentModeReady && !embedded && (selectedInputMode() === "upload" || selectedSource() === "asr")) {
      elements.qualityCaption.textContent = cloudSelected
        ? "直接使用所选云端模型识别音轨"
        : autoUsesLocal ? "使用本地模型识别音轨" : "使用当前可用服务识别音轨";
    }
    elements.privacyNote.textContent = !currentModeReady
      ? "平台字幕提取不受影响；需要语音识别时请稍后重试。"
      : currentMode === "auto" && localReady
        ? "基础模式在本站内部完成语音识别，不会把音频发送给第三方云端。临时媒体会在任务结束后自动删除。"
        : "云端高级模式会把临时音频发送至阿里云百炼处理；任务完成后会清理本站临时副本。";
    elements.platformAiRow.hidden = !subtitleMode || selectedInputMode() === "upload" || embedded;
  }

  /* ---------- Platform detection ---------- */

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

  function bilibiliStatus() {
    const statuses = state.capabilities && state.capabilities.platform_status;
    const status = statuses && statuses.bilibili;
    return status && typeof status === "object" ? status : { state: "ok" };
  }

  function markBilibiliLimited(message) {
    if (!state.capabilities) state.capabilities = {};
    state.capabilities.platform_status = Object.assign({}, state.capabilities.platform_status, {
      bilibili: { state: "limited", message: message || errorMessages.platform_blocked }
    });
    updatePlatformNotice();
    updatePlatformHealth();
  }

  function updatePlatformNotice() {
    const limited = bilibiliStatus().state === "limited";
    const platform = detectPlatform(elements.input.value.trim());
    const show = limited && platform === "bilibili" && selectedInputMode() === "link";
    elements.platformNotice.hidden = !show;
    if (!show) return;
    elements.platformNoticeTitle.textContent = "B站暂时限制了本站访问";
    elements.platformNoticeDetail.textContent = selectedOperation() === "subtitle" && uploadsEnabled()
      ? "可以先把视频保存到本地，再改用上传文件识别；也可以稍后再试。"
      : "这通常是平台的临时风控，请稍后再试。";
    elements.platformNoticeAction.hidden = !(selectedOperation() === "subtitle" && uploadsEnabled() && !state.busy);
  }

  function updatePlatformHealth() {
    const limited = bilibiliStatus().state === "limited";
    elements.bilibiliChip.classList.toggle("limited", limited);
    elements.bilibiliChip.title = limited ? "B站暂时限制了本站访问" : "B站可用";
    setHealthValue(elements.healthBilibili, limited ? "暂时受限" : "可用", limited ? "warn" : "");
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
    elements.uploadFileTitle.textContent = file ? file.name : "选择视频文件";
    elements.uploadFileDetail.textContent = file ? formatBytes(file.size) : "点击选择，或拖放到此处";
  }

  function clearUnavailableUploadSelection() {
    if (state.currentPayload && state.currentPayload.kind === "upload" && !state.uploadFile) setUploadFile(null);
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
    if (document.body.dataset.platform !== platform) {
      document.body.dataset.platform = platform;
      fx("platform", { platform });
    }
    updatePlatformNotice();
    return platform;
  }

  function hidePageSelector() {
    elements.pageSelectorRow.hidden = true;
    elements.pageSelect.textContent = "";
    state.biliBaseUrl = "";
  }

  function schedulePageLookup() {
    state.pageLookupVersion += 1;
    if (state.pageLookupTimer) clearTimeout(state.pageLookupTimer);
    if (detectPlatform(elements.input.value.trim()) !== "bilibili") {
      hidePageSelector();
      return;
    }
    state.pageLookupTimer = setTimeout(loadBilibiliPages, 450);
  }

  async function loadBilibiliPages() {
    state.pageLookupTimer = null;
    const version = ++state.pageLookupVersion;
    const input = elements.input.value.trim();
    if (detectPlatform(input) !== "bilibili") {
      hidePageSelector();
      return;
    }
    const params = new URLSearchParams({ input });
    try {
      const response = await apiFetch(`/api/bilibili/pages?${params.toString()}`, { cache: "no-store" });
      const data = await response.json().catch(() => ({}));
      if (version !== state.pageLookupVersion || elements.input.value.trim() !== input) return;
      const detail = errorDetail(data);
      if (!response.ok && detail && detail.code === "platform_blocked") markBilibiliLimited(detail.message);
      if (!response.ok || !Array.isArray(data.pages) || data.pages.length <= 1) {
        hidePageSelector();
        return;
      }
      elements.pageSelect.textContent = "";
      data.pages.forEach((page, index) => {
        const option = document.createElement("option");
        option.value = String(page.page || index + 1);
        option.textContent = `P${page.page || index + 1} · ${page.title || "未命名分段"}`;
        elements.pageSelect.appendChild(option);
      });
      elements.pageSelect.value = String(data.current_page || 1);
      state.biliBaseUrl = data.base_url || "";
      elements.pageSelectorRow.hidden = false;
    } catch (_) {
      if (version === state.pageLookupVersion && elements.input.value.trim() === input) hidePageSelector();
    }
  }

  function buildPayload(overrides) {
    const operation = selectedOperation();
    const payload = operation === "subtitle"
      ? {
          input: elements.input.value.trim(),
          source: selectedSource(),
          format: elements.format.value,
          lang: elements.lang.value || null,
          hotwords: elements.hotwords.value.trim() || null,
          quality: selectedQuality(),
          asr_mode: selectedAsrMode(),
          cloud_consent: false,
          embedded_subtitles: selectedEmbeddedSubtitles(),
          allow_platform_ai: elements.allowPlatformAi.checked,
          force_refresh: elements.forceRefresh.checked
        }
      : {
          kind: "media",
          input: elements.input.value.trim(),
          media_type: operation,
          force_refresh: elements.forceRefresh.checked
        };
    return Object.assign(payload, overrides || {});
  }

  function validateInput() {
    const value = elements.input.value.trim();
    const platform = detectPlatform(value);
    let message = "";
    if (!value) message = "请输入视频链接或 BV 号。";
    else if (platform === "unknown") message = "没有识别到 B站或抖音视频链接。";
    elements.input.classList.toggle("invalid", Boolean(message));
    elements.input.setAttribute("aria-invalid", String(Boolean(message)));
    elements.inputError.textContent = message;
    updatePlatformDetect();
    return !message;
  }

  /* ---------- Busy state and status ---------- */

  function stopPolling() {
    if (state.pollTimer) clearTimeout(state.pollTimer);
    state.pollTimer = null;
    if (state.pollController) state.pollController.abort();
    state.pollController = null;
    state.pollFailures = 0;
    state.pollPaused = false;
  }

  function formatClock(totalSeconds) {
    const seconds = Math.max(0, Math.floor(totalSeconds));
    if (seconds < 60) return `${seconds} 秒`;
    const minutes = Math.floor(seconds / 60);
    return `${minutes} 分 ${String(seconds % 60).padStart(2, "0")} 秒`;
  }

  function setBusy(busy, startedAt) {
    if (state.busy !== busy) fx("busy", { busy });
    state.busy = busy;
    elements.extractButton.disabled = busy;
    elements.extractButton.classList.toggle("loading", busy);
    elements.extractButtonLabel.textContent = busy ? "任务处理中" : "";
    elements.resultActions.hidden = busy || !state.current;
    elements.retryAccurate.hidden = busy || elements.retryAccurate.hidden;
    elements.copyResult.hidden = Boolean(state.current && state.current.kind === "media");
    syncInputMode();
    renderHistory();
    if (state.elapsedTimer) clearInterval(state.elapsedTimer);
    state.elapsedTimer = null;
    if (!busy) {
      elements.statusElapsed.textContent = "";
      return;
    }
    state.startedAt = Number(startedAt || Date.now());
    const updateElapsed = () => {
      elements.statusElapsed.textContent = `已用时 ${formatClock((Date.now() - state.startedAt) / 1000)}`;
    };
    updateElapsed();
    state.elapsedTimer = setInterval(updateElapsed, 1000);
  }

  function updateStageTrack(stage, progress, status) {
    const media = state.currentPayload && state.currentPayload.kind === "media";
    elements.stageTrack.querySelector('[data-stage="recognize"] span').textContent = media ? "转换" : "识别";
    const stageGroups = {
      starting: "prepare",
      validating: "prepare",
      cache: "prepare",
      discover: "fetch",
      platform: "fetch",
      checking_existing_subtitle: "fetch",
      download: "fetch",
      downloading_audio: "fetch",
      media_download: "fetch",
      embedded_subtitle: "fetch",
      ocr_wait: "recognize",
      ocr: "recognize",
      ocr_fallback: "recognize",
      asr_wait: "recognize",
      transcribe: "recognize",
      preprocessing: "recognize",
      waiting_for_provider: "recognize",
      transcribing: "recognize",
      postprocessing: "render",
      media_convert: "recognize",
      render: "render",
      media_finalize: "render"
    };
    const order = ["prepare", "fetch", "recognize", "render"];
    let current = stageGroups[stage];
    if (!current) {
      const numericProgress = Number(progress);
      current = numericProgress >= 85 ? "render"
        : numericProgress >= 45 ? "recognize"
          : numericProgress >= 12 ? "fetch" : "prepare";
    }
    const currentIndex = order.indexOf(current);
    fx("stage", { stage: current, progress: Number(progress) || 0, status: status || "processing" });
    elements.stageTrack.querySelectorAll("li").forEach((item) => {
      const index = order.indexOf(item.dataset.stage);
      item.classList.toggle("done", index >= 0 && index < currentIndex);
      item.classList.toggle("active", index === currentIndex);
    });
    elements.stageTrack.hidden = !["queued", "running", "processing"].includes(status || "processing");
  }

  function showStatus(kind, title, detail, progress, mark) {
    elements.resultExpiry.hidden = true;
    elements.resultPane.dataset.state = kind || "idle";
    elements.retryTask.hidden = kind !== "error";
    elements.retryTask.textContent = "返回任务设置";
    elements.statusPanel.hidden = false;
    elements.statusPanel.className = `status-panel ${kind || ""}`.trim();
    elements.statusTitle.textContent = title;
    elements.statusDetail.textContent = detail;
    elements.statusMark.querySelector("span").textContent = mark || (kind === "error" ? "!" : "CC");
    const numericProgress = Number(progress);
    if (Number.isFinite(numericProgress)) {
      elements.progressTrack.setAttribute("aria-valuenow", String(Math.min(100, Math.max(0, numericProgress))));
    } else {
      elements.progressTrack.removeAttribute("aria-valuenow");
    }
    elements.progressTrack.hidden = !Number.isFinite(numericProgress);
    elements.progressValue.style.width = Number.isFinite(numericProgress)
      ? `${Math.min(100, Math.max(2, numericProgress))}%`
      : "0%";
    if (["queued", "processing"].includes(kind)) {
      updateStageTrack("", numericProgress, kind === "queued" ? "queued" : "processing");
    } else {
      elements.stageTrack.hidden = true;
    }
    elements.outputShell.hidden = true;
    elements.mediaResult.hidden = true;
    elements.idleOutput.hidden = ["error", "reconnecting"].includes(kind);
    elements.idleOutput.classList.toggle("processing", ["queued", "processing"].includes(kind));
    if (["queued", "processing"].includes(kind)) {
      elements.idleTitle.textContent = kind === "queued" ? "等待处理" : "正在生成结果";
      elements.idleDetail.textContent = "可以离开页面，任务会在后台继续";
    }
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
    if (status === 401) return "访问凭据已失效，请重新输入激活码。";
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

  function formatTimestamp(seconds) {
    const total = Math.max(0, Math.floor(Number(seconds || 0)));
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const secs = total % 60;
    const mmss = `${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
    return hours ? `${hours}:${mmss}` : mmss;
  }

  function formatElapsed(seconds) {
    const value = Number(seconds || 0);
    if (value < 0.1) return `${Math.max(1, Math.round(value * 1000))} ms`;
    return `${value.toFixed(value < 10 ? 2 : 1)} 秒`;
  }

  /* ---------- Result rendering ---------- */

  function addChip(label, className) {
    const chip = document.createElement("span");
    chip.className = `meta-chip ${className || ""}`.trim();
    chip.textContent = label;
    elements.metadataStrip.appendChild(chip);
  }

  function renderMetadata(meta) {
    elements.metadataStrip.textContent = "";
    addChip(platformLabel(meta.platform), ["bilibili", "douyin", "upload"].includes(meta.platform) ? meta.platform : "");
    if (meta.media_type) {
      addChip(meta.media_type === "audio" ? "MP3 音频" : "视频文件", meta.media_type === "audio" ? "asr" : "");
    } else {
      addChip(
        sourceLabels[meta.source] || meta.source || "未知来源",
        ["asr_local", "asr_aliyun", "ocr_video"].includes(meta.source) ? "asr" : ""
      );
    }
    const asrMode = meta.asr_mode || meta.requested_asr_mode;
    if (asrMode && ["asr_local", "asr_aliyun"].includes(meta.source)) {
      addChip(
        asrMode === "economy" ? "经济模式" : asrMode === "high_accuracy" ? "高精度" : "自动模式",
        asrMode === "economy" ? "" : "asr"
      );
    }
    if (meta.track_source_type === "embedded_text" && meta.source !== "embedded_text") addChip("内嵌字幕", "cache");
    if (meta.track_source_type === "burned_in_ocr" && meta.source !== "ocr_video") addChip("画面字幕", "asr");
    if (meta.cache_hit) addChip("已命中缓存", "cache");
    if (meta.duration) addChip(`时长 ${formatDuration(meta.duration)}`);
    if (meta.entry_count) addChip(`${meta.entry_count} 条`);
    if (meta.language) addChip(`语言 ${String(meta.language).toUpperCase()}`);
    if (meta.elapsed_seconds !== undefined) addChip(`用时 ${formatElapsed(meta.elapsed_seconds)}`);
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
    if (meta.platform === "upload") return "识别完成，临时视频已自动删除。";
    if (meta.source === "asr_local" && meta.requested_source === "auto") {
      return `未找到可用的${platformLabel(meta.platform)}字幕，本次已使用本地语音识别。`;
    }
    if (meta.source === "asr_aliyun" && meta.requested_source === "auto") {
      return `未找到可用的${platformLabel(meta.platform)}字幕，本次已使用阿里云百炼语音识别。`;
    }
    if (meta.track_source_type === "platform_ai") return `本次使用了${platformLabel(meta.platform)}平台自动字幕。`;
    return "";
  }

  function shouldOfferAccurateRetry(meta, payload) {
    if (!payload || !payload.input || payload.kind === "upload" || payload.kind === "media") return false;
    if (!state.capabilities || !state.capabilities.features || !state.capabilities.features.cloud_enhancement) return false;
    if (payload.quality === "fast") return true;
    if (meta.track_source_type === "platform_ai") return true;
    if (meta.quality_warning) return true;
    if (Number(meta.low_confidence_segment_ratio || 0) >= 0.25) return true;
    return Number(meta.repeated_segment_ratio || 0) >= 0.1;
  }

  function normalizeSegments(items) {
    if (!Array.isArray(items)) return [];
    return items.filter((item) => item && typeof item.text === "string" && item.text.trim())
      .map((item) => ({ start: Number(item.start) || 0, end: Number(item.end) || 0, text: item.text }));
  }

  function currentDisplayedContent() {
    if (!state.current || state.current.kind !== "subtitle") return "";
    return state.current.showingRaw && state.current.rawContent ? state.current.rawContent : state.current.content;
  }

  function displayedSegments() {
    if (!state.current || state.current.kind !== "subtitle") return [];
    return state.current.showingRaw && state.current.rawContent
      ? state.current.rawSegments
      : state.current.segments;
  }

  function activeResultView() {
    return state.resultView === "segments" && displayedSegments().length ? "segments" : "source";
  }

  function countMatches(source, needle) {
    let cursor = 0;
    let count = 0;
    while (cursor < source.length) {
      const index = source.indexOf(needle, cursor);
      if (index < 0) break;
      count += 1;
      cursor = index + Math.max(needle.length, 1);
    }
    return count;
  }

  function appendHighlighted(container, text, needle, budget) {
    if (!needle) {
      container.textContent = text;
      return budget;
    }
    const source = text.toLocaleLowerCase();
    let cursor = 0;
    while (cursor < text.length && budget > 0) {
      const index = source.indexOf(needle, cursor);
      if (index < 0) break;
      container.appendChild(document.createTextNode(text.slice(cursor, index)));
      const mark = document.createElement("mark");
      mark.textContent = text.slice(index, index + needle.length);
      container.appendChild(mark);
      cursor = index + Math.max(needle.length, 1);
      budget -= 1;
    }
    container.appendChild(document.createTextNode(text.slice(cursor)));
    return budget;
  }

  function renderSegments(needle) {
    const segments = displayedSegments();
    const fragment = document.createDocumentFragment();
    let budget = 200;
    let matches = 0;
    let firstMatch = null;
    segments.forEach((segment, index) => {
      const item = document.createElement("li");
      item.className = "segment";
      const time = document.createElement("button");
      time.type = "button";
      time.className = "segment-time";
      time.dataset.index = String(index);
      time.textContent = formatTimestamp(segment.start);
      time.title = "复制这一句";
      const text = document.createElement("p");
      text.className = "segment-text";
      if (needle) {
        const found = countMatches(segment.text.toLocaleLowerCase(), needle);
        if (found) {
          matches += found;
          item.classList.add("match");
          if (!firstMatch) firstMatch = item;
        }
      }
      budget = appendHighlighted(text, segment.text, needle, budget);
      item.append(time, text);
      fragment.appendChild(item);
    });
    elements.segmentList.textContent = "";
    elements.segmentList.appendChild(fragment);
    fx("segments", { segments, list: elements.segmentList, timeline: elements.segmentTimeline, needle });
    return { matches, firstMatch };
  }

  function renderOutputContent() {
    const view = activeResultView();
    const content = currentDisplayedContent();
    const query = elements.resultSearch.value.trim();
    const needle = query.toLocaleLowerCase();
    elements.viewSegments.setAttribute("aria-pressed", String(view === "segments"));
    elements.viewSource.setAttribute("aria-pressed", String(view === "source"));
    elements.viewSegments.disabled = !displayedSegments().length;
    elements.segmentList.hidden = view !== "segments";
    elements.segmentTimeline.hidden = view !== "segments";
    elements.output.hidden = view !== "source";
    elements.toggleWrap.hidden = view !== "source";
    elements.searchCount.textContent = "";
    elements.output.textContent = "";
    if (view === "segments") {
      elements.output.textContent = content;
      const { matches, firstMatch } = renderSegments(query ? needle : "");
      if (query) elements.searchCount.textContent = matches ? `${matches} 处` : "未找到";
      if (firstMatch) firstMatch.scrollIntoView({ block: "center" });
      return;
    }
    elements.segmentList.textContent = "";
    if (!query || !content) {
      elements.output.textContent = content;
      return;
    }
    const count = countMatches(content.toLocaleLowerCase(), needle);
    appendHighlighted(elements.output, content, needle, 200);
    elements.searchCount.textContent = count ? `${count} 处` : "未找到";
    const firstMark = elements.output.querySelector("mark");
    if (firstMark) firstMark.scrollIntoView({ block: "center" });
  }

  function updateOutputStats() {
    if (activeResultView() === "segments") {
      const segments = displayedSegments();
      const characters = segments.reduce((total, segment) => total + segment.text.length, 0);
      elements.outputStats.textContent = `${segments.length} 句 · ${characters.toLocaleString("zh-CN")} 字`;
      return;
    }
    const content = currentDisplayedContent();
    const lineCount = content ? content.split("\n").filter(Boolean).length : 0;
    elements.outputStats.textContent = `${lineCount} 行 · ${content.length.toLocaleString("zh-CN")} 字符`;
  }

  function setResultView(view) {
    state.resultView = view === "source" ? "source" : "segments";
    savePreferences();
    renderOutputContent();
    updateOutputStats();
  }

  function toggleRawVersion() {
    if (!state.current || state.current.kind !== "subtitle" || !state.current.rawContent) return;
    state.current.showingRaw = !state.current.showingRaw;
    elements.toggleRaw.setAttribute("aria-pressed", String(state.current.showingRaw));
    elements.toggleRaw.textContent = state.current.showingRaw ? "整理版" : "原始版";
    elements.resultSearch.value = "";
    renderOutputContent();
    updateOutputStats();
  }

  function renderResult(data, payload, jobId, expiresAt) {
    payload = payload || {};
    elements.resultPane.dataset.state = "complete";
    elements.retryTask.hidden = true;
    if (data.kind === "media" || data.download_url) {
      renderMediaResult(data, payload, jobId, expiresAt);
      return;
    }
    state.current = {
      kind: "subtitle",
      resultJobId: jobId || null,
      expiresAt: Number(expiresAt || 0),
      content: data.content || "",
      rawContent: data.raw_content || "",
      segments: normalizeSegments(data.segments),
      rawSegments: normalizeSegments(data.raw_segments),
      showingRaw: false,
      filename: data.filename || `video_subtitle.${data.format || "txt"}`,
      contentType: data.content_type || "text/plain;charset=utf-8",
      format: data.format || payload.format || "txt",
      metadata: data.metadata || {},
      input: payload.input || payload.filename || ""
    };
    const meta = state.current.metadata;
    elements.resultKicker.textContent = `${platformLabel(meta.platform)}字幕 · ${meta.id || "已完成"}`;
    elements.resultTitle.textContent = meta.title || "提取完成";
    elements.resultTitle.title = meta.title || "";
    elements.statusPanel.hidden = true;
    elements.queueBadge.hidden = true;
    elements.cancelJob.hidden = true;
    renderMetadata(meta);
    const notice = friendlyNotice(meta);
    elements.notice.textContent = notice;
    elements.notice.hidden = !notice;
    elements.resultSearch.value = "";
    applyWrapPreference();
    elements.outputFormat.textContent = state.current.format.toUpperCase();
    elements.resultFormat.value = state.current.format === "md" ? "markdown" : state.current.format;
    elements.resultFormat.disabled = !state.current.resultJobId;
    elements.downloadResult.disabled = false;
    elements.toggleRaw.disabled = false;
    elements.outputShell.removeAttribute("aria-busy");
    elements.toggleRaw.hidden = !state.current.rawContent;
    elements.toggleRaw.setAttribute("aria-pressed", "false");
    elements.toggleRaw.textContent = "原始版";
    elements.outputShell.hidden = false;
    renderOutputContent();
    updateOutputStats();
    elements.mediaResult.hidden = true;
    elements.idleOutput.hidden = true;
    elements.copyResult.hidden = false;
    elements.retryAccurate.hidden = !shouldOfferAccurateRetry(meta, payload);
    elements.resultActions.hidden = false;
    elements.forceRefresh.checked = false;
    updateResultExpiry();
    loadHistory();
    setMobileView("result");
  }

  function renderMediaResult(data, payload, jobId, expiresAt) {
    state.current = {
      kind: "media",
      resultJobId: jobId || null,
      expiresAt: Number(expiresAt || 0),
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
    elements.resultTitle.title = meta.title || "";
    elements.statusPanel.hidden = true;
    elements.queueBadge.hidden = true;
    elements.cancelJob.hidden = true;
    renderMetadata(meta);
    elements.notice.hidden = true;
    elements.outputShell.hidden = true;
    elements.idleOutput.hidden = true;
    elements.retryAccurate.hidden = true;
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
    updateResultExpiry();
    loadHistory();
    setMobileView("result");
  }

  function updateResultExpiry() {
    const current = state.current;
    if (!current || !Number.isFinite(current.expiresAt) || !current.expiresAt || state.busy) {
      elements.resultExpiry.hidden = true;
      return;
    }
    if (current.expiresAt * 1000 <= Date.now()) {
      state.current = null;
      elements.output.textContent = "";
      elements.segmentList.textContent = "";
      elements.resultActions.hidden = true;
      showStatus("expired", "结果已过期", "已超过保留时间，请重新提交任务。", NaN, "!");
      elements.idleOutput.hidden = true;
      elements.retryTask.hidden = false;
      elements.resultTitle.textContent = "结果已过期";
      renderHistory();
      return;
    }
    const deadline = new Intl.DateTimeFormat("zh-CN", {
      month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false
    }).format(new Date(current.expiresAt * 1000));
    elements.resultExpiry.textContent = `${current.kind === "media" ? "下载文件" : "字幕结果"}保留至 ${deadline}`;
    elements.resultExpiry.hidden = false;
  }

  /* ---------- History drawer ---------- */

  async function loadHistory() {
    if (!state.user) return;
    if (state.historyController) state.historyController.abort();
    const controller = new AbortController();
    state.historyController = controller;
    const timeout = setTimeout(() => controller.abort(), 12000);
    elements.refreshHistory.disabled = true;
    try {
      const response = await apiFetch("/api/jobs?limit=20", { cache: "no-store", signal: controller.signal });
      const data = await response.json();
      if (!response.ok || !Array.isArray(data.jobs)) throw new Error("history_unavailable");
      if (state.historyController !== controller) return;
      state.history = data.jobs.filter((item) => item && typeof item.id === "string"
        && typeof item.status === "string" && Number.isFinite(Number(item.created_at)));
      state.retentionSeconds = Number(data.retention_seconds) > 0 ? Number(data.retention_seconds) : 86400;
      state.historyError = false;
    } catch (_) {
      if (state.historyController !== controller) return;
      state.historyError = true;
    } finally {
      clearTimeout(timeout);
      if (state.historyController === controller) {
        state.historyController = null;
        elements.refreshHistory.disabled = false;
        renderHistory();
      }
    }
  }

  function setHistoryDrawer(open) {
    const visible = Boolean(open);
    if (visible === !elements.historyDrawer.hidden) return;
    elements.historyDrawer.hidden = !visible;
    elements.openHistory.setAttribute("aria-expanded", String(visible));
    syncBodyLock();
    if (visible) {
      setAccountMenu(false);
      setHealthPopover(false);
      loadHistory();
      elements.closeHistory.focus();
    } else if (elements.openHistory.getClientRects().length) {
      elements.openHistory.focus();
    }
  }

  async function openHistoryItem(item) {
    if (state.busy) return;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 12000);
    setBusy(true);
    try {
      const response = await apiFetch(`/api/jobs/${encodeURIComponent(item.id)}`, {
        cache: "no-store", signal: controller.signal
      });
      const job = await response.json();
      if (!response.ok) {
        if (response.status === 404 || response.status === 410) {
          state.history = state.history.filter((entry) => entry.id !== item.id);
          throw new Error("这条记录已过期，当前结果未被覆盖。");
        }
        throw new Error("暂时无法读取记录，请稍后重试。");
      }
      if (!validJobSnapshot(job)) throw new Error("记录暂不可用，请稍后重试。");
      setHistoryDrawer(false);
      state.currentPayload = { kind: item.kind, media_type: item.media_type };
      state.current = null;
      if (["queued", "running"].includes(job.status)) {
        state.jobId = job.id;
        setBusy(true, Number(job.created_at) * 1000 || Date.now());
        saveActiveJob();
        handleJob(job);
        pollJob();
        setMobileView("result");
      } else {
        handleJob(job);
      }
    } catch (error) {
      setBusy(false);
      updateResultExpiry();
      showToast(error.name === "AbortError" ? "读取记录超时，请重试。" : error.message, true);
    } finally {
      clearTimeout(timeout);
    }
  }

  function renderHistory() {
    const container = elements.historyList;
    container.textContent = "";
    elements.openHistory.hidden = !state.user;
    const caption = `字幕最多保留 ${Math.round(state.retentionSeconds / 3600)} 小时，可直接重新打开`;
    elements.historyCaption.textContent = state.historyError ? "记录暂不可用，可刷新重试" : caption;
    state.history = state.history.filter((item) => !item.expires_at || item.expires_at * 1000 > Date.now());
    elements.historyCount.textContent = String(state.history.length);
    elements.historyCount.hidden = !state.history.length;
    const labels = { queued: "排队中", running: "处理中", completed: "已完成", failed: "未完成", cancelled: "已取消" };
    if (!state.history.length) {
      const empty = document.createElement("p");
      empty.className = "history-empty";
      empty.textContent = state.historyError ? "暂时无法读取记录" : "暂无近期任务";
      container.append(empty);
      return;
    }
    const activeId = state.current && state.current.resultJobId || state.jobId;
    state.history.forEach((item) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `recent-item ${["failed", "cancelled"].includes(item.status) ? item.status : ""}`.trim();
      button.setAttribute("aria-current", String(item.id === activeId));
      button.disabled = state.busy;
      button.title = item.title || "视频任务";
      const platform = document.createElement("span");
      platform.className = `recent-platform ${["bilibili", "douyin", "upload"].includes(item.platform) ? item.platform : "upload"}`;
      platform.textContent = item.kind === "media" ? (item.media_type === "audio" ? "音频" : "视频") : "字幕";
      const title = document.createElement("span");
      title.className = "recent-title";
      title.textContent = item.title || "视频任务";
      const detail = document.createElement("span");
      detail.className = "recent-detail";
      const time = new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit" })
        .format(new Date(Number(item.created_at || 0) * 1000));
      detail.textContent = `${labels[item.status] || "未完成"} · ${platformLabel(item.platform)} · ${time}`;
      button.append(platform, title, detail);
      button.addEventListener("click", () => openHistoryItem(item));
      container.appendChild(button);
    });
  }

  /* ---------- Jobs ---------- */

  function finishWithError(value, status) {
    stopPolling();
    const message = friendlyError(value, status || 0);
    const detail = errorDetail(value);
    if (detail && detail.code === "platform_blocked") markBilibiliLimited(detail.message);
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
    fx("failed", { message });
    setBusy(false);
    setMobileView("result");
    showToast(message, true);
    loadHealth();
    loadHistory();
  }

  function handleJob(job) {
    if (!job || !job.status) return;
    state.resuming = false;
    if (job.status === "queued") {
      elements.resultTitle.textContent = "任务排队中";
      const ahead = Math.max(0, Number(job.queue_position || 1) - 1);
      elements.queueBadge.textContent = ahead ? `前方 ${ahead} 个任务` : "即将开始";
      elements.queueBadge.hidden = false;
      elements.cancelJob.textContent = "取消排队";
      elements.cancelJob.hidden = false;
      showStatus("queued", "任务正在排队", job.message || "等待处理资源", job.progress || 3, "…");
      updateStageTrack("starting", job.progress || 3, "queued");
      return;
    }
    elements.queueBadge.hidden = true;
    elements.cancelJob.textContent = "取消排队";
    elements.cancelJob.hidden = true;
    if (job.status === "running") {
      elements.resultTitle.textContent = state.currentPayload && state.currentPayload.kind === "media"
        ? state.currentPayload.media_type === "audio" ? "正在提取音频" : "正在提取视频"
        : "正在提取字幕";
      const detail = stageDetails[job.stage] || "正在处理当前任务";
      showStatus("processing", job.message || "正在处理视频", detail, job.progress || 8, "…");
      updateStageTrack(job.stage, job.progress || 8, "running");
      return;
    }
    if (job.status === "completed") {
      stopPolling();
      clearActiveJob();
      state.jobId = null;
      renderResult(job.result || {}, state.currentPayload, job.id, job.expires_at);
      if (state.current) fx("complete", { kind: state.current.kind });
      clearUnavailableUploadSelection();
      setBusy(false);
      updateResultExpiry();
      loadHealth();
      return;
    }
    if (job.status === "cancelled") {
      stopPolling();
      clearActiveJob();
      state.jobId = null;
      state.current = null;
      elements.resultTitle.textContent = "任务已取消";
      clearUnavailableUploadSelection();
      showStatus("cancelled", "任务已取消", "可以修改设置后重新提交", NaN, "CC");
      elements.idleTitle.textContent = "任务已取消";
      elements.idleDetail.textContent = "可以修改设置后重新提交";
      setBusy(false);
      loadHealth();
      loadHistory();
      return;
    }
    if (job.status === "failed") finishWithError(job.error || {}, Number(job.error_status || 500));
  }

  function validJobSnapshot(job) {
    return job && typeof job.id === "string" && job.id.length > 0 && job.id.length <= 128
      && ["queued", "running", "completed", "failed", "cancelled"].includes(job.status)
      && (job.status !== "completed" || job.result && typeof job.result === "object"
        && (typeof job.result.content === "string" || typeof job.result.download_url === "string"));
  }

  function transientStatus(status) {
    return status === 408 || status === 429 || status >= 500;
  }

  function notePollingFailure() {
    state.pollFailures += 1;
    state.pollPaused = state.pollFailures >= 6;
    saveActiveJob();
    elements.cancelJob.hidden = true;
    elements.queueBadge.hidden = true;
    showStatus("reconnecting", "连接暂时中断", state.pollPaused
      ? "暂时无法读取进度，任务编号已保留。恢复连接后可继续查询。"
      : "正在重新连接，任务编号已保留，不会重复提交。", NaN, "!");
    elements.retryTask.textContent = "重新连接";
    elements.retryTask.hidden = !state.pollPaused;
  }

  async function pollJob() {
    if (!state.jobId || !state.busy || state.pollController || state.pollPaused) return;
    if (state.pollTimer) clearTimeout(state.pollTimer);
    state.pollTimer = null;
    const jobId = state.jobId;
    const controller = new AbortController();
    state.pollController = controller;
    const timeout = setTimeout(() => controller.abort(), 12000);
    let retryDelay = 0;
    try {
      const response = await apiFetch(`/api/jobs/${encodeURIComponent(jobId)}`, {
        cache: "no-store", signal: controller.signal
      });
      const data = await response.json().catch(() => ({}));
      if (state.pollController !== controller || state.jobId !== jobId) return;
      if (!response.ok) {
        if (!transientStatus(response.status)) {
          finishWithError(data, response.status);
          return;
        }
        const retryAfter = response.headers.get("Retry-After");
        const seconds = Number(retryAfter);
        retryDelay = Math.min(60000, Math.max(0, Number.isFinite(seconds)
          ? seconds * 1000 : Date.parse(retryAfter) - Date.now())) || 0;
        throw new Error("retryable_job_response");
      }
      if (!validJobSnapshot(data) || data.id !== jobId) throw new Error("invalid_job_response");
      state.pollFailures = 0;
      saveActiveJob();
      handleJob(data);
    } catch (_) {
      if (state.pollController === controller && state.jobId === jobId) notePollingFailure();
    } finally {
      clearTimeout(timeout);
      if (state.pollController === controller) state.pollController = null;
      if (state.jobId === jobId && state.busy && !state.pollPaused) {
        const delay = state.pollFailures ? Math.min(30000, 1000 * 2 ** state.pollFailures)
          : document.hidden ? 8000 : 1500;
        state.pollTimer = setTimeout(pollJob, Math.max(delay, retryDelay));
      }
    }
  }

  function reconnectJob() {
    if (!state.jobId || !state.busy || state.pollController) return;
    state.pollPaused = false;
    state.pollFailures = 0;
    elements.retryTask.hidden = true;
    elements.statusDetail.textContent = "正在重新读取任务进度";
    pollJob();
  }

  async function changeResultFormat() {
    updateResultExpiry();
    const current = state.current;
    if (!current || current.kind !== "subtitle" || !current.resultJobId || state.busy) return;
    const format = elements.resultFormat.value;
    if (format === current.format) return;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    elements.resultFormat.disabled = true;
    elements.downloadResult.disabled = true;
    elements.toggleRaw.disabled = true;
    elements.outputShell.setAttribute("aria-busy", "true");
    try {
      const response = await apiFetch(
        `/api/jobs/${encodeURIComponent(current.resultJobId)}/result?format=${encodeURIComponent(format)}`,
        { cache: "no-store", signal: controller.signal }
      );
      const data = await response.json().catch(() => ({}));
      updateResultExpiry();
      if (state.current !== current) return;
      if (!response.ok || typeof data.content !== "string") {
        showToast(response.ok ? "格式转换暂时不可用，已保留当前结果。" : friendlyError(data, response.status), true);
        return;
      }
      Object.assign(current, {
        content: data.content, rawContent: data.raw_content || "", format: data.format,
        filename: data.filename, contentType: data.content_type
      });
      if (!current.rawContent) current.showingRaw = false;
      elements.outputFormat.textContent = current.format.toUpperCase();
      elements.resultSearch.value = "";
      if (activeResultView() === "segments") {
        showToast(`复制与下载将使用 ${elements.resultFormat.selectedOptions[0].textContent} 格式`, false);
      }
      renderOutputContent();
      updateOutputStats();
    } catch (_) {
      if (state.current === current) showToast("无法连接服务，已保留当前结果。", true);
    } finally {
      clearTimeout(timeout);
      if (state.current === current) {
        elements.resultFormat.value = current.format === "md" ? "markdown" : current.format;
        elements.resultFormat.disabled = false;
        elements.downloadResult.disabled = false;
        elements.toggleRaw.disabled = false;
        elements.outputShell.removeAttribute("aria-busy");
      }
    }
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
    setMobileView("result");
    try {
      const response = await apiFetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey },
        body: JSON.stringify(payload)
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        if (!transientStatus(response.status)) {
          state.submissionKey = null;
          state.submissionSignature = null;
        }
        finishWithError(data, response.status);
        return;
      }
      if (!validJobSnapshot(data)) throw new Error("invalid_job_response");
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

  function runUpload(cloudConsent) {
    if (state.busy || !validateUpload()) return;
    const file = state.uploadFile;
    const payload = {
      kind: "upload",
      filename: file.name,
      size: file.size,
      last_modified: file.lastModified || 0,
      format: elements.format.value,
      lang: elements.lang.value || null,
      hotwords: elements.hotwords.value.trim() || null,
      quality: selectedQuality(),
      asr_mode: selectedAsrMode(),
      cloud_consent: Boolean(cloudConsent),
      embedded_subtitles: selectedEmbeddedSubtitles(),
      force_refresh: elements.forceRefresh.checked
    };
    const idempotencyKey = submissionKey(payload);
    const params = new URLSearchParams({
      filename: file.name,
      format: payload.format,
      quality: payload.quality,
      asr_mode: payload.asr_mode,
      cloud_consent: String(payload.cloud_consent),
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
    setMobileView("result");

    const xhr = new XMLHttpRequest();
    state.uploadXhr = xhr;
    xhr.open("POST", `/api/upload-jobs?${params.toString()}`);
    xhr.withCredentials = true;
    xhr.setRequestHeader("Idempotency-Key", idempotencyKey);
    if (payload.hotwords) xhr.setRequestHeader("X-ASR-Hotwords", encodeURIComponent(payload.hotwords));
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
      updateStageTrack("download", percent, "running");
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
        if (!transientStatus(xhr.status)) {
          state.submissionKey = null;
          state.submissionSignature = null;
        }
        finishWithError(data, xhr.status);
        return;
      }
      if (!validJobSnapshot(data)) {
        finishWithError({ message: "未收到有效任务编号，请重试。" }, 0);
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

  /* ---------- Result actions ---------- */

  function showToast(message, error) {
    if (state.toastTimer) clearTimeout(state.toastTimer);
    elements.toast.textContent = message;
    elements.toast.classList.toggle("error", Boolean(error));
    elements.toast.classList.add("visible");
    state.toastTimer = setTimeout(() => elements.toast.classList.remove("visible"), 2600);
  }

  async function writeClipboard(text) {
    try {
      await navigator.clipboard.writeText(text);
    } catch (_) {
      const helper = document.createElement("textarea");
      helper.value = text;
      helper.setAttribute("readonly", "");
      helper.className = "visually-hidden";
      document.body.appendChild(helper);
      helper.select();
      document.execCommand("copy");
      helper.remove();
    }
  }

  async function copyResult() {
    updateResultExpiry();
    if (!state.current || state.current.kind === "media") return;
    await writeClipboard(currentDisplayedContent());
    showToast("已复制全部字幕", false);
  }

  async function copySegment(index) {
    updateResultExpiry();
    const segment = displayedSegments()[index];
    if (!segment) return;
    await writeClipboard(segment.text);
    showToast(`已复制 ${formatTimestamp(segment.start)} 这一句`, false);
  }

  function downloadResult() {
    updateResultExpiry();
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
    const blob = new Blob([currentDisplayedContent()], { type: state.current.contentType });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = state.current.showingRaw
      ? state.current.filename.replace(/(\.[^.]+)$/, "_raw$1")
      : state.current.filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    showToast("已开始下载", false);
  }

  function retryAccurate() {
    if (state.busy || !state.current || state.current.kind !== "subtitle") return;
    setSelectedOperation("subtitle");
    setInputMode("link");
    setSelectedAsrMode("high_accuracy");
    setSelectedSource("asr");
    elements.embeddedSubtitles.checked = false;
    elements.allowPlatformAi.checked = false;
    elements.forceRefresh.checked = true;
    syncInputMode();
    savePreferences();
    requestCloudConfirmation(() => {
      runExtraction({
        source: "asr",
        quality: "accurate",
        asr_mode: "high_accuracy",
        cloud_consent: true,
        embedded_subtitles: false,
        allow_platform_ai: false,
        force_refresh: true
      });
    });
  }

  async function pasteInput() {
    try {
      const text = await navigator.clipboard.readText();
      if (!text) throw new Error("empty");
      elements.input.value = text.trim();
      validateInput();
      schedulePageLookup();
      elements.input.focus();
    } catch (_) {
      showToast("无法读取剪贴板，请手动粘贴。", true);
    }
  }

  function startNewTask() {
    if (state.busy) {
      showToast("当前任务完成后即可新建任务。", true);
      return;
    }
    setSelectedOperation("subtitle");
    setInputMode("link");
    elements.input.value = "";
    elements.inputError.textContent = "";
    elements.input.classList.remove("invalid");
    elements.input.removeAttribute("aria-invalid");
    elements.forceRefresh.checked = false;
    setUploadFile(null);
    resetResult();
    hidePageSelector();
    updatePlatformDetect();
    setMobileView("compose");
    elements.input.focus();
  }

  /* ---------- Service health ---------- */

  function setHealthValue(element, text, level) {
    element.textContent = text;
    element.classList.toggle("warn", level === "warn");
    element.classList.toggle("error", level === "error");
  }

  function setHealthPopover(open) {
    const visible = Boolean(open);
    elements.healthPopover.hidden = !visible;
    elements.healthTrigger.setAttribute("aria-expanded", String(visible));
  }

  async function loadHealth() {
    if (state.healthLoading) return;
    state.healthLoading = true;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 12000);
    try {
      const healthResponse = await fetch("/api/health", { cache: "no-store", signal: controller.signal });
      if (!healthResponse.ok) throw new Error(String(healthResponse.status));
      const health = await healthResponse.json();
      if (health.status !== "ok") throw new Error("unhealthy");
      const configResponse = await apiFetch("/api/client-config", { cache: "no-store", signal: controller.signal });
      if (!configResponse.ok) throw new Error(String(configResponse.status));
      state.capabilities = await configResponse.json();
      const features = state.capabilities.features || {};
      const platforms = state.capabilities.platforms || {};
      const bilibiliLimited = bilibiliStatus().state === "limited";
      elements.serviceState.className = `service-state ${bilibiliLimited ? "degraded" : "online"}`;
      elements.serviceLabel.textContent = bilibiliLimited ? "部分受限" : "服务在线";
      elements.healthSummary.textContent = bilibiliLimited ? "B站暂时受限" : "全部正常";
      setHealthValue(elements.healthDouyin, platforms.douyin === false ? "暂不可用" : "可用", platforms.douyin === false ? "warn" : "");
      setHealthValue(elements.healthLocal, features.local_processing ? "可用" : "暂不可用",
        features.local_processing ? "" : "warn");
      setHealthValue(elements.healthCloud, features.cloud_enhancement ? "可选" : "未启用",
        features.cloud_enhancement ? "" : "warn");
      const filesReady = Boolean(features.uploads && features.media);
      setHealthValue(elements.healthFiles, filesReady ? "可用" : "部分受限", filesReady ? "" : "warn");
      elements.bilibiliChip.classList.toggle("unavailable", platforms.bilibili === false);
      elements.douyinChip.classList.toggle("unavailable", platforms.douyin === false);
      updatePlatformHealth();
      const uploads = state.capabilities.uploads || {};
      const canUpload = uploads.enabled !== false;
      state.uploadMaxBytes = Number(uploads.max_bytes || state.uploadMaxBytes);
      state.uploadExtensions = Array.isArray(uploads.allowed_extensions) ? uploads.allowed_extensions : [];
      elements.uploadLimit.textContent = `最大 ${formatBytes(state.uploadMaxBytes)}`;
      elements.uploadChip.classList.toggle("unavailable", !canUpload || platforms.upload === false);
      const media = state.capabilities.media || {};
      state.mediaEnabled = media.enabled !== false;
      if (!state.busy && !state.mediaEnabled && selectedOperation() !== "subtitle") {
        setSelectedOperation("subtitle");
      }
      if (!state.busy && !canUpload && selectedInputMode() === "upload") setInputMode("link");
      else syncInputMode();
    } catch (_) {
      elements.serviceState.className = "service-state offline";
      elements.serviceLabel.textContent = "服务异常";
      elements.healthSummary.textContent = "连接失败";
      [elements.healthBilibili, elements.healthDouyin, elements.healthLocal, elements.healthCloud, elements.healthFiles]
        .forEach((element) => setHealthValue(element, "无法读取", "error"));
      elements.bilibiliChip.classList.add("unavailable");
      elements.douyinChip.classList.add("unavailable");
      elements.uploadChip.classList.add("unavailable");
      if (!state.capabilities) state.mediaEnabled = false;
      syncInputMode();
    } finally {
      clearTimeout(timeout);
      state.healthLoading = false;
    }
  }

  /* ---------- Submission ---------- */

  function submitCurrentForm() {
    if (state.busy) return;
    if (selectedInputMode() === "upload") {
      if (!validateUpload()) return;
    } else if (!validateInput()) {
      return;
    }
    const action = selectedInputMode() === "upload"
      ? () => runUpload(true)
      : () => runExtraction({ cloud_consent: true });
    if (selectedOperation() === "subtitle" && ["high_accuracy", "economy"].includes(selectedAsrMode())) {
      requestCloudConfirmation(action);
      return;
    }
    if (selectedInputMode() === "upload") runUpload(false);
    else runExtraction();
  }

  /* ---------- Event wiring ---------- */

  elements.form.addEventListener("submit", (event) => {
    event.preventDefault();
    submitCurrentForm();
  });
  elements.form.querySelectorAll('input[name="input-mode"], input[name="operation"]').forEach((radio) => {
    radio.addEventListener("change", () => {
      syncInputMode();
      savePreferences();
    });
  });
  elements.form.querySelectorAll('input[name="asr-mode"], input[name="source"]').forEach((radio) => {
    radio.addEventListener("change", () => {
      syncPrecisionOptions();
      savePreferences();
    });
  });
  elements.newTask.addEventListener("click", startNewTask);
  elements.embeddedSubtitles.addEventListener("change", () => {
    if (elements.embeddedSubtitles.checked) setSelectedSource("auto");
    syncInputMode();
    savePreferences();
  });
  elements.input.addEventListener("input", () => {
    updatePlatformDetect();
    schedulePageLookup();
    if (elements.input.classList.contains("invalid")) validateInput();
  });
  elements.input.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
      event.preventDefault();
      if (selectedInputMode() === "link") submitCurrentForm();
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
    elements.input.value = "";
    elements.inputError.textContent = "";
    elements.input.classList.remove("invalid");
    elements.input.removeAttribute("aria-invalid");
    updatePlatformDetect();
    hidePageSelector();
    elements.input.focus();
  });
  elements.platformNoticeAction.addEventListener("click", () => {
    setInputMode("upload");
    savePreferences();
    elements.videoFile.focus();
  });
  elements.copyResult.addEventListener("click", copyResult);
  elements.downloadResult.addEventListener("click", downloadResult);
  elements.retryAccurate.addEventListener("click", retryAccurate);
  elements.retryTask.addEventListener("click", () => {
    if (state.pollPaused && state.jobId) {
      reconnectJob();
      return;
    }
    setMobileView("compose");
    elements.composerPane.scrollIntoView({ block: "start", behavior: "smooth" });
    if (selectedInputMode() === "link") elements.input.focus();
    else elements.videoFile.focus();
  });
  elements.cancelJob.addEventListener("click", cancelCurrentJob);
  elements.format.addEventListener("change", () => {
    syncEmptyState();
    savePreferences();
  });
  elements.resultFormat.addEventListener("change", changeResultFormat);
  elements.lang.addEventListener("change", savePreferences);
  elements.allowPlatformAi.addEventListener("change", savePreferences);
  elements.pageSelect.addEventListener("change", () => {
    if (!state.biliBaseUrl) return;
    elements.input.value = `${state.biliBaseUrl}?p=${encodeURIComponent(elements.pageSelect.value)}`;
    updatePlatformDetect();
  });
  elements.resultSearch.addEventListener("input", () => {
    clearTimeout(state.searchTimer);
    state.searchTimer = setTimeout(renderOutputContent, 120);
  });
  elements.viewSegments.addEventListener("click", () => setResultView("segments"));
  elements.viewSource.addEventListener("click", () => setResultView("source"));
  elements.segmentList.addEventListener("click", (event) => {
    const button = event.target.closest(".segment-time");
    if (button) copySegment(Number(button.dataset.index));
  });
  elements.toggleRaw.addEventListener("click", toggleRawVersion);
  elements.toggleWrap.addEventListener("click", () => {
    state.wrapOutput = !state.wrapOutput;
    applyWrapPreference();
    savePreferences();
  });
  elements.mobileCompose.addEventListener("click", () => setMobileView("compose"));
  elements.mobileResult.addEventListener("click", () => setMobileView("result"));
  elements.healthTrigger.addEventListener("click", () => setHealthPopover(elements.healthPopover.hidden));
  elements.themeToggle.addEventListener("click", cycleTheme);
  elements.accountTrigger.addEventListener("click", () => setAccountMenu(elements.accountPopover.hidden));
  elements.logoutAllDevices.addEventListener("click", logoutAllDevices);
  elements.cloudConfirmCheck.addEventListener("change", () => {
    elements.submitCloudConfirm.disabled = !elements.cloudConfirmCheck.checked;
  });
  elements.closeCloudConfirm.addEventListener("click", () => setCloudConfirmDialog(false, false));
  elements.cancelCloudConfirm.addEventListener("click", () => setCloudConfirmDialog(false, true));
  elements.submitCloudConfirm.addEventListener("click", confirmCloudAction);
  elements.cloudConfirmDialog.addEventListener("click", (event) => {
    if (event.target === elements.cloudConfirmDialog) setCloudConfirmDialog(false, false);
  });
  elements.openHistory.addEventListener("click", () => setHistoryDrawer(elements.historyDrawer.hidden));
  elements.closeHistory.addEventListener("click", () => setHistoryDrawer(false));
  elements.refreshHistory.addEventListener("click", loadHistory);
  elements.historyDrawer.addEventListener("click", (event) => {
    if (event.target === elements.historyDrawer) setHistoryDrawer(false);
  });
  document.addEventListener("click", (event) => {
    if (!elements.healthPopover.hidden && !event.target.closest(".health-menu")) setHealthPopover(false);
    if (!elements.accountPopover.hidden && !event.target.closest(".account-area")) setAccountMenu(false);
  });
  document.addEventListener("keydown", (event) => {
    const dialog = !elements.cloudConfirmDialog.hidden ? elements.cloudConfirmDialog
      : !elements.historyDrawer.hidden ? elements.historyDrawer : null;
    if (event.key === "Tab" && dialog) {
      const controls = Array.from(dialog.querySelectorAll('button:not(:disabled), input:not(:disabled), [tabindex="0"]'))
        .filter((element) => element.getClientRects().length > 0);
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (first && (!dialog.contains(document.activeElement)
        || event.shiftKey && document.activeElement === first
        || !event.shiftKey && document.activeElement === last)) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
      }
    }
    if (event.key !== "Escape") return;
    setHealthPopover(false);
    setAccountMenu(false);
    if (!elements.cloudConfirmDialog.hidden) setCloudConfirmDialog(false, false);
    if (!elements.historyDrawer.hidden) setHistoryDrawer(false);
  });
  elements.logoutAccount.addEventListener("click", logoutAccount);
  window.addEventListener("online", reconnectJob);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) {
      updateResultExpiry();
      loadHistory();
    }
    if (!document.hidden && !state.pollPaused) reconnectJob();
  });

  async function initializeApp() {
    applyTheme(storedTheme());
    const platform = (navigator.userAgentData && navigator.userAgentData.platform) || navigator.platform || "";
    if (!/mac|iphone|ipad/i.test(platform)) $("shortcut-modifier").textContent = "Ctrl";
    renderHistory();
    applyWrapPreference();
    setMobileView("compose");
    updatePlatformDetect();
    syncInputMode();
    if (!await loadAccount()) return;
    await loadHealth();
    requestAnimationFrame(() => document.body.classList.add("app-ready"));
    fx("ready", { owner: Boolean(state.user && state.user.is_admin) });
  }

  initializeApp();
  setInterval(loadHealth, 30000);
  setInterval(() => {
    if (!document.hidden) {
      updateResultExpiry();
      renderHistory();
    }
  }, 30000);
})();
