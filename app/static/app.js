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
    cookieRow: $("cookie-row"),
    useCookie: $("use-cookie"),
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
    healthLocal: $("health-local"),
    healthCloud: $("health-cloud"),
    healthFiles: $("health-files"),
    bilibiliChip: $("bilibili-chip"),
    douyinChip: $("douyin-chip"),
    uploadChip: $("upload-chip"),
    guestLoginButton: $("guest-login-button"),
    guestAccessBanner: $("guest-access-banner"),
    accountArea: $("account-area"),
    accountAvatar: $("account-avatar"),
    accountAvatarLarge: $("account-avatar-large"),
    accountName: $("account-name"),
    accountTrigger: $("account-trigger"),
    accountPopover: $("account-popover"),
    accountPopoverName: $("account-popover-name"),
    accountCreatedAt: $("account-created-at"),
    accountSessionSummary: $("account-session-summary"),
    openPasswordDialog: $("open-password-dialog"),
    logoutAllDevices: $("logout-all-devices"),
    logoutAccount: $("logout-account"),
    passwordDialog: $("password-dialog"),
    passwordForm: $("password-form"),
    currentPassword: $("current-password"),
    newPassword: $("new-password"),
    confirmNewPassword: $("confirm-new-password"),
    passwordError: $("password-error"),
    closePasswordDialog: $("close-password-dialog"),
    cancelPasswordDialog: $("cancel-password-dialog"),
    submitPassword: $("submit-password"),
    cloudModeZone: $("cloud-mode-zone"),
    cloudConfirmDialog: $("cloud-confirm-dialog"),
    cloudConfirmModel: $("cloud-confirm-model"),
    cloudConfirmCheck: $("cloud-confirm-check"),
    closeCloudConfirm: $("close-cloud-confirm"),
    cancelCloudConfirm: $("cancel-cloud-confirm"),
    submitCloudConfirm: $("submit-cloud-confirm"),
    railNewTask: $("rail-new-task"),
    railSubtitle: $("rail-subtitle"),
    railSubtitleAccess: $("rail-subtitle-access"),
    railVideo: $("rail-video"),
    railAudio: $("rail-audio"),
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
    outputShell: $("output-shell"),
    output: $("output"),
    outputFormat: $("output-format-label"),
    outputStats: $("output-stats-label"),
    resultSearch: $("result-search"),
    searchCount: $("search-count"),
    toggleRaw: $("toggle-raw"),
    toggleWrap: $("toggle-wrap"),
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
    guest: false,
    capabilities: null,
    history: [],
    uploadMaxBytes: 512 * 1024 * 1024,
    uploadExtensions: [],
    mediaEnabled: true,
    wrapOutput: true,
    mobileView: "compose",
    preferencesLoaded: false,
    pageLookupTimer: null,
    biliBaseUrl: "",
    pendingCloudAction: null
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
    authentication_required: "登录已失效，正在返回登录页。",
    guest_session_expired: "游客任务凭据已失效，请重新提交。",
    guest_media_busy: "当前已有一个免登录媒体任务，请等待完成。",
    guest_media_session_limit: "这个浏览器的免登录提取次数较多，请稍后再试。",
    guest_media_global_limit: "当前免登录提取请求较多，请稍后再试。",
    guest_media_disabled: "免登录媒体提取暂时关闭，请登录后重试。",
    guest_media_duration_too_long: "视频时长超过免登录提取限制，请登录后重试。",
    media_duration_too_long: "视频时长超过当前媒体提取限制。",
    cloud_consent_required: "请先确认云端识别会消耗站点额度。",
    current_password_invalid: "当前密码不正确。",
    password_unchanged: "新密码不能与当前密码相同。",
    password_too_short: "新密码至少需要 8 个字符。",
    password_too_long: "新密码不能超过 128 个字符。"
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

  function historyStorageKey(userId) {
    return `video-workspace-history-v4:${userId}`;
  }

  function preferencesStorageKey(userId) {
    return `video-workspace-preferences-v1:${userId}`;
  }

  function storageOwnerKey() {
    return state.user ? String(state.user.id) : "guest";
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
    setSelectedAsrMode(
      ["auto", "high_accuracy", "economy"].includes(value.asrMode)
        ? value.asrMode
        : "auto"
    );
    if (["txt", "srt", "vtt", "markdown", "json"].includes(value.format)) elements.format.value = value.format;
    elements.lang.value = ["", "zh", "en", "ja", "ko"].includes(value.lang) ? value.lang : "zh";
    elements.embeddedSubtitles.checked = value.embeddedSubtitles === true;
    elements.allowPlatformAi.checked = value.allowPlatformAi !== false;
    elements.useCookie.checked = value.useCookie === true;
    state.wrapOutput = value.wrapOutput !== false;
    applyWrapPreference();
    state.preferencesLoaded = true;
    syncInputMode();
  }

  function savePreferences() {
    if (!state.preferencesLoaded) return;
    const value = {
      operation: selectedOperation(),
      inputMode: selectedInputMode(),
      source: selectedSource(),
      quality: "accurate",
      asrMode: selectedAsrMode(),
      format: elements.format.value,
      lang: elements.lang.value,
      embeddedSubtitles: selectedEmbeddedSubtitles(),
      allowPlatformAi: elements.allowPlatformAi.checked,
      useCookie: elements.useCookie.checked,
      wrapOutput: state.wrapOutput
    };
    try {
      localStorage.setItem(preferencesStorageKey(storageOwnerKey()), JSON.stringify(value));
    } catch (_) {
      return;
    }
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
    try {
      localStorage.setItem(historyStorageKey(storageOwnerKey()), JSON.stringify(state.history.slice(0, 8)));
    } catch (_) {
      return;
    }
  }

  function activeJobStorageKey(userId) {
    return `caption-active-job-v1:${userId}`;
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
    elements.useCookie.checked = Boolean(payload.use_cookie);
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
    showStatus("processing", "正在恢复任务", "正在读取最新处理进度", 4, "…");
    pollJob();
  }

  async function apiFetch(url, options) {
    const response = await fetch(url, options);
    if (response.status === 401 && state.user) {
      window.location.replace("/login");
    }
    return response;
  }

  function formatAccountDate(timestamp) {
    const value = Number(timestamp || 0);
    if (!value) return "首次登录";
    return new Intl.DateTimeFormat("zh-CN", {
      year: "numeric",
      month: "short",
      day: "numeric"
    }).format(new Date(value * 1000));
  }

  function setAccountMenu(open) {
    const visible = Boolean(open) && !elements.accountTrigger.disabled;
    elements.accountPopover.hidden = !visible;
    elements.accountTrigger.setAttribute("aria-expanded", String(visible));
  }

  function applyAccessState() {
    const isGuest = !state.user;
    state.guest = isGuest;
    elements.accountArea.hidden = isGuest;
    elements.guestLoginButton.hidden = !isGuest;
    elements.guestAccessBanner.hidden = !isGuest;
    elements.railSubtitleAccess.hidden = !isGuest;
    if (isGuest && selectedOperation() === "subtitle") {
      setSelectedOperation("video");
    }
    syncInputMode();
  }

  function setPasswordDialog(open) {
    const visible = Boolean(open);
    elements.passwordDialog.hidden = !visible;
    document.body.classList.toggle(
      "dialog-open",
      visible || !elements.cloudConfirmDialog.hidden
    );
    if (visible) {
      setAccountMenu(false);
      elements.passwordError.textContent = "";
      elements.passwordForm.reset();
      requestAnimationFrame(() => elements.currentPassword.focus());
    }
  }

  function setCloudConfirmDialog(open, resetMode) {
    const visible = Boolean(open);
    elements.cloudConfirmDialog.hidden = !visible;
    document.body.classList.toggle(
      "dialog-open",
      visible || !elements.passwordDialog.hidden
    );
    if (!visible) {
      state.pendingCloudAction = null;
      elements.cloudConfirmCheck.checked = false;
      elements.submitCloudConfirm.disabled = true;
      if (resetMode) {
        setSelectedAsrMode("auto");
        syncPrecisionOptions();
        savePreferences();
      }
      return;
    }
    setAccountMenu(false);
    elements.cloudConfirmCheck.checked = false;
    elements.submitCloudConfirm.disabled = true;
    elements.cloudConfirmModel.textContent = selectedAsrMode() === "economy"
      ? "Paraformer · 经济模式"
      : "千问 ASR · 高精度";
    requestAnimationFrame(() => elements.cloudConfirmCheck.focus());
  }

  function requestCloudConfirmation(action) {
    if (!["high_accuracy", "economy"].includes(selectedAsrMode())) {
      action();
      return;
    }
    if (!state.user) {
      showToast("云端识别需要先登录。", true);
      window.location.assign("/login");
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
    document.body.classList.toggle("dialog-open", !elements.passwordDialog.hidden);
    action();
  }

  async function loadAccount() {
    try {
      const response = await fetch("/api/auth/me", { cache: "no-store" });
      const data = await response.json().catch(() => ({}));
      if (response.status === 401 || !data.user) {
        state.user = null;
        applyAccessState();
        loadPreferences("guest");
        state.history = loadHistory("guest");
        renderHistory();
        resumeActiveJob();
        return false;
      }
      if (!response.ok) throw new Error(String(response.status));
      state.user = data.user;
      applyAccessState();
      elements.accountName.textContent = data.user.username;
      const initial = String(data.user.username || "?").charAt(0).toUpperCase();
      elements.accountAvatar.textContent = initial;
      elements.accountAvatarLarge.textContent = initial;
      elements.accountPopoverName.textContent = data.user.username;
      elements.accountCreatedAt.textContent = `${formatAccountDate(data.user.created_at)} 加入`;
      const sessions = Math.max(1, Number(data.user.active_sessions || 1));
      elements.accountSessionSummary.textContent = `当前有 ${sessions} 个有效登录会话`;
      elements.accountTrigger.disabled = false;
      elements.accountArea.setAttribute("aria-busy", "false");
      loadPreferences(data.user.id);
      state.history = loadHistory(data.user.id);
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
    if (!window.confirm("确定退出全部设备吗？完成后需要重新登录。")) return;
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

  async function changeAccountPassword(event) {
    event.preventDefault();
    const currentPassword = elements.currentPassword.value;
    const newPassword = elements.newPassword.value;
    if (!currentPassword) {
      elements.passwordError.textContent = "请输入当前密码。";
      elements.currentPassword.focus();
      return;
    }
    if (newPassword.length < 8) {
      elements.passwordError.textContent = "新密码至少需要 8 个字符。";
      elements.newPassword.focus();
      return;
    }
    if (newPassword !== elements.confirmNewPassword.value) {
      elements.passwordError.textContent = "两次输入的新密码不一致。";
      elements.confirmNewPassword.focus();
      return;
    }
    elements.submitPassword.disabled = true;
    elements.submitPassword.textContent = "正在更新";
    elements.passwordError.textContent = "";
    try {
      const response = await apiFetch("/api/auth/change-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          current_password: currentPassword,
          new_password: newPassword
        })
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        elements.passwordError.textContent = friendlyError(data, response.status);
        return;
      }
      setPasswordDialog(false);
      showToast("密码已更新，其他设备已退出。", false);
      await loadAccount();
    } catch (_) {
      elements.passwordError.textContent = "无法连接账号服务，请稍后重试。";
    } finally {
      elements.submitPassword.disabled = false;
      elements.submitPassword.textContent = "更新密码";
    }
  }

  function selectedSource() {
    const selected = elements.form.querySelector('input[name="source"]:checked');
    return selected ? selected.value : "auto";
  }

  function selectedQuality() {
    return "accurate";
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

  function toggleRawVersion() {
    if (!state.current || state.current.kind !== "subtitle" || !state.current.rawContent) return;
    state.current.showingRaw = !state.current.showingRaw;
    elements.toggleRaw.setAttribute("aria-pressed", String(state.current.showingRaw));
    elements.toggleRaw.textContent = state.current.showingRaw ? "整理版" : "原始版";
    elements.resultSearch.value = "";
    renderOutputContent();
    updateOutputStats();
  }

  function renderOutputContent() {
    const content = currentDisplayedContent();
    const query = elements.resultSearch.value.trim();
    elements.output.textContent = "";
    elements.searchCount.textContent = "";
    if (!query || !content) {
      elements.output.textContent = content;
      return;
    }

    const source = content.toLocaleLowerCase();
    const needle = query.toLocaleLowerCase();
    let cursor = 0;
    let count = 0;
    while (cursor < source.length) {
      const index = source.indexOf(needle, cursor);
      if (index < 0) break;
      count += 1;
      cursor = index + Math.max(needle.length, 1);
    }

    cursor = 0;
    let highlighted = 0;
    while (cursor < content.length && highlighted < 200) {
      const index = source.indexOf(needle, cursor);
      if (index < 0) break;
      elements.output.appendChild(document.createTextNode(content.slice(cursor, index)));
      const mark = document.createElement("mark");
      mark.textContent = content.slice(index, index + needle.length);
      elements.output.appendChild(mark);
      cursor = index + Math.max(needle.length, 1);
      highlighted += 1;
    }
    elements.output.appendChild(document.createTextNode(content.slice(cursor)));
    elements.searchCount.textContent = count ? `${count} 处` : "未找到";
    const firstMatch = elements.output.querySelector("mark");
    if (firstMatch) firstMatch.scrollIntoView({ block: "center" });
  }

  function currentDisplayedContent() {
    if (!state.current || state.current.kind !== "subtitle") return "";
    return state.current.showingRaw && state.current.rawContent
      ? state.current.rawContent
      : state.current.content;
  }

  function updateOutputStats() {
    const content = currentDisplayedContent();
    const lineCount = content ? content.split("\n").filter(Boolean).length : 0;
    elements.outputStats.textContent = `${lineCount} 行 · ${content.length.toLocaleString("zh-CN")} 字符`;
  }

  function updateStageTrack(stage, progress, status) {
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
      current = numericProgress >= 85
        ? "render"
        : numericProgress >= 45
          ? "recognize"
          : numericProgress >= 12 ? "fetch" : "prepare";
    }
    const currentIndex = order.indexOf(current);
    elements.stageTrack.querySelectorAll("li").forEach((item) => {
      const index = order.indexOf(item.dataset.stage);
      item.classList.toggle("done", index >= 0 && index < currentIndex);
      item.classList.toggle("active", index === currentIndex);
    });
    elements.stageTrack.hidden = !["queued", "running", "processing"].includes(status || "processing");
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
        ? state.guest ? "免登录提取视频" : "提取视频"
        : operation === "audio"
          ? state.guest ? "免登录提取音频" : "提取音频"
          : selectedInputMode() === "upload" ? "开始识别" : "开始提取";
  }

  function syncRailNavigation() {
    const operation = selectedOperation();
    [elements.railSubtitle, elements.railVideo, elements.railAudio].forEach((button) => {
      const selected = button.dataset.operation === operation;
      button.classList.toggle("active", selected);
      button.setAttribute("aria-current", selected ? "page" : "false");
      button.disabled = state.busy
        || (button.dataset.operation === "subtitle" && state.guest)
        || (button.dataset.operation !== "subtitle" && !state.mediaEnabled);
    });
  }

  function syncInputMode() {
    let operation = selectedOperation();
    if (state.guest && operation === "subtitle") {
      const videoRadio = elements.form.querySelector('input[name="operation"][value="video"]');
      if (videoRadio) videoRadio.checked = true;
      operation = "video";
    }
    const mediaMode = operation !== "subtitle";
    const linkRadio = elements.form.querySelector('input[name="input-mode"][value="link"]');
    const uploadRadio = elements.form.querySelector('input[name="input-mode"][value="upload"]');
    if (mediaMode && uploadRadio.checked) linkRadio.checked = true;
    const uploadMode = !mediaMode && selectedInputMode() === "upload";
    const uploadsEnabled = !state.guest && (!state.capabilities
      || !state.capabilities.uploads
      || state.capabilities.uploads.enabled !== false);
    elements.inputModeGroup.hidden = mediaMode;
    elements.linkInputPanel.hidden = uploadMode;
    elements.uploadInputPanel.hidden = !uploadMode;
    elements.sourceFieldGroup.hidden = uploadMode || mediaMode;
    elements.subtitleFormatGrid.hidden = mediaMode;
    elements.privacyNote.hidden = mediaMode;
    elements.platformAiRow.hidden = uploadMode || mediaMode || elements.embeddedSubtitles.checked;
    const cookieReady = Boolean(
      state.capabilities
      && state.capabilities.features
      && state.capabilities.features.bilibili_cookie
    );
    elements.cookieRow.hidden = state.guest || uploadMode || !cookieReady;
    elements.input.required = !uploadMode;
    elements.clearInput.title = uploadMode ? "清除视频" : "清空输入";
    uploadRadio.disabled = state.busy || state.guest || mediaMode || !uploadsEnabled;
    linkRadio.disabled = state.busy;
    elements.videoFile.disabled = state.busy || !uploadsEnabled;
    elements.form.querySelectorAll('input[name="operation"]').forEach((radio) => {
      radio.disabled = state.busy
        || (radio.value === "subtitle" && state.guest)
        || (radio.value !== "subtitle" && !state.mediaEnabled);
    });
    syncRailNavigation();
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

  function setSelectedAsrMode(value) {
    const radio = elements.form.querySelector(`input[name="asr-mode"][value="${value}"]`);
    if (radio) radio.checked = true;
  }

  function isLocalAsrReady() {
    if (!state.capabilities) return true;
    return Boolean(
      state.capabilities.features
      && state.capabilities.features.local_processing
    );
  }

  function syncPrecisionOptions() {
    const subtitleMode = selectedOperation() === "subtitle";
    const videoSubtitleReady = !state.capabilities
      || !state.capabilities.features
      || state.capabilities.features.embedded_subtitles !== false;
    elements.embeddedSubtitles.disabled = state.busy || !subtitleMode || !videoSubtitleReady;
    const embedded = subtitleMode && selectedEmbeddedSubtitles();
    if (embedded) {
      setSelectedSource("auto");
    }
    elements.qualityFieldGroup.hidden = !subtitleMode;
    elements.embeddedSubtitleRow.hidden = !subtitleMode;
    const localReady = isLocalAsrReady();
    const cloudReady = Boolean(
      state.capabilities
      && state.capabilities.features
      && state.capabilities.features.cloud_enhancement
    );
    const autoBackend = state.capabilities
      && state.capabilities.asr_modes
      && state.capabilities.asr_modes.auto
      ? state.capabilities.asr_modes.auto.processing
      : null;
    const autoReady = !state.capabilities
      || Boolean(state.capabilities.asr_modes && state.capabilities.asr_modes.auto.available);
    const autoUsesLocal = !state.capabilities || autoBackend === "local";
    const autoRadio = elements.form.querySelector('input[name="asr-mode"][value="auto"]');
    elements.asrAutoTitle.textContent = autoUsesLocal ? "本地基础" : "自动识别";
    elements.asrAutoDetail.textContent = autoUsesLocal
      ? "默认 · 不使用云端额度"
      : "智能选择可用服务";
    elements.form.querySelectorAll('input[name="asr-mode"]').forEach((radio) => {
      const unavailable = radio.value === "auto"
        ? !autoReady
        : !cloudReady;
      radio.disabled = state.busy || !subtitleMode || unavailable;
    });
    if (
      state.capabilities
      && selectedAsrMode() !== "auto"
      && !cloudReady
      && autoRadio
      && !autoRadio.disabled
    ) {
      autoRadio.checked = true;
    }
    elements.form.querySelectorAll('input[name="source"]').forEach((radio) => {
      radio.disabled = state.busy || embedded;
    });
    elements.allowPlatformAi.disabled = state.busy || embedded;
    elements.hotwords.disabled = state.busy || !subtitleMode;
    elements.hotwordsRow.hidden = !subtitleMode;
    const currentMode = selectedAsrMode();
    elements.cloudModeZone.classList.toggle(
      "selected",
      currentMode === "high_accuracy" || currentMode === "economy"
    );
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
              ? "先提取平台字幕，没有字幕时在本站内部识别"
              : "先提取平台字幕，没有字幕时使用当前可用识别服务";
    elements.privacyNote.textContent = !currentModeReady
      ? "平台字幕提取不受影响；需要语音识别时请稍后重试。"
      : currentMode === "auto" && localReady
        ? "基础模式在本站内部完成语音识别，不会把音频发送给第三方云端。临时媒体会在任务结束后自动删除。"
        : "云端高级模式会把临时音频发送至阿里云百炼处理；任务完成后会清理本站临时副本。";
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

  function hidePageSelector() {
    elements.pageSelectorRow.hidden = true;
    elements.pageSelect.textContent = "";
    state.biliBaseUrl = "";
  }

  function schedulePageLookup() {
    if (state.pageLookupTimer) clearTimeout(state.pageLookupTimer);
    if (detectPlatform(elements.input.value.trim()) !== "bilibili") {
      hidePageSelector();
      return;
    }
    state.pageLookupTimer = setTimeout(loadBilibiliPages, 450);
  }

  async function loadBilibiliPages() {
    state.pageLookupTimer = null;
    const input = elements.input.value.trim();
    if (detectPlatform(input) !== "bilibili") {
      hidePageSelector();
      return;
    }
    const params = new URLSearchParams({
      input,
      use_cookie: String(elements.useCookie.checked)
    });
    try {
      const response = await apiFetch(`/api/bilibili/pages?${params.toString()}`, {
        cache: "no-store"
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || elements.input.value.trim() !== input || !Array.isArray(data.pages)) {
        hidePageSelector();
        return;
      }
      if (data.pages.length <= 1) {
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
      hidePageSelector();
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
    elements.retryAccurate.hidden = busy || elements.retryAccurate.hidden;
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
    if (["queued", "processing"].includes(kind)) {
      updateStageTrack("", numericProgress, kind === "queued" ? "queued" : "processing");
    } else {
      elements.stageTrack.hidden = true;
    }
    elements.outputShell.hidden = true;
    elements.mediaResult.hidden = true;
    elements.idleOutput.hidden = kind === "error";
    elements.idleOutput.classList.toggle(
      "processing",
      ["queued", "processing"].includes(kind)
    );
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
    if (meta.track_source_type === "embedded_text") addChip("内嵌字幕", "cache");
    if (meta.track_source_type === "burned_in_ocr") addChip("画面字幕", "asr");
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
    if (meta.platform === "upload") {
      return "识别完成，临时视频已自动删除。";
    }
    if (meta.source === "asr_local" && meta.requested_source === "auto") {
      return `未找到可用的${platformLabel(meta.platform)}字幕，本次已使用本地语音识别。`;
    }
    if (meta.source === "asr_aliyun" && meta.requested_source === "auto") {
      return `未找到可用的${platformLabel(meta.platform)}字幕，本次已使用阿里云百炼语音识别。`;
    }
    if (meta.track_source_type === "platform_ai") {
      return `本次使用了${platformLabel(meta.platform)}平台自动字幕。`;
    }
    return "";
  }

  function shouldOfferAccurateRetry(meta, payload) {
    if (!payload || payload.kind === "upload" || payload.kind === "media") return false;
    if (payload.quality === "fast") return true;
    if (meta.track_source_type === "platform_ai") return true;
    if (meta.quality_warning) return true;
    if (Number(meta.low_confidence_segment_ratio || 0) >= 0.25) return true;
    return Number(meta.repeated_segment_ratio || 0) >= 0.1;
  }

  function renderResult(data, payload) {
    if (data.kind === "media" || data.download_url) {
      renderMediaResult(data, payload);
      return;
    }
    state.current = {
      kind: "subtitle",
      content: data.content || "",
      rawContent: data.raw_content || "",
      showingRaw: false,
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
    elements.resultSearch.value = "";
    renderOutputContent();
    applyWrapPreference();
    elements.outputFormat.textContent = state.current.format.toUpperCase();
    updateOutputStats();
    elements.toggleRaw.hidden = !state.current.rawContent;
    elements.toggleRaw.setAttribute("aria-pressed", "false");
    elements.toggleRaw.textContent = "原始版";
    elements.outputShell.hidden = false;
    elements.mediaResult.hidden = true;
    elements.idleOutput.hidden = true;
    elements.copyResult.hidden = false;
    elements.retryAccurate.hidden = !shouldOfferAccurateRetry(meta, payload);
    elements.resultActions.hidden = false;
    elements.forceRefresh.checked = false;
    if (payload.kind !== "upload") addHistory(payload, meta);
    setMobileView("result");
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
    addHistory(payload, meta);
    setMobileView("result");
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
      quality: payload.quality || "accurate",
      asrMode: payload.asr_mode || "auto",
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
          elements.lang.value = item.lang || "zh";
          elements.hotwords.value = "";
          setSelectedSource(item.source || "auto");
          setSelectedAsrMode(item.asrMode || "auto");
          elements.embeddedSubtitles.checked = Boolean(item.embeddedSubtitles);
          syncInputMode();
        }
        elements.forceRefresh.checked = false;
        updatePlatformDetect();
        schedulePageLookup();
        submitCurrentForm();
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
    setMobileView("result");
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
      updateStageTrack("starting", job.progress || 3, "queued");
      return;
    }
    elements.queueBadge.hidden = true;
    elements.cancelJob.textContent = "取消排队";
    elements.cancelJob.hidden = true;
    if (job.status === "running") {
      const detail = stageDetails[job.stage] || "正在处理当前任务";
      showStatus("processing", job.message || "正在处理视频", detail, job.progress || 8, "…");
      updateStageTrack(job.stage, job.progress || 8, "running");
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
    setMobileView("result");
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
    const content = currentDisplayedContent();
    try {
      await navigator.clipboard.writeText(content);
    } catch (_) {
      const helper = document.createElement("textarea");
      helper.value = content;
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
    try {
      const healthResponse = await fetch("/api/health", { cache: "no-store" });
      if (!healthResponse.ok) throw new Error(String(healthResponse.status));
      const health = await healthResponse.json();
      if (health.status !== "ok") throw new Error("unhealthy");
      const configEndpoint = state.user ? "/api/client-config" : "/api/public-config";
      const configResponse = state.user
        ? await apiFetch(configEndpoint, { cache: "no-store" })
        : await fetch(configEndpoint, { cache: "no-store" });
      if (!configResponse.ok) throw new Error(String(configResponse.status));
      state.capabilities = await configResponse.json();
      const features = state.capabilities.features || {};
      const platforms = state.capabilities.platforms || {};
      const isGuest = !state.user;
      elements.serviceState.className = "service-state online";
      elements.serviceLabel.textContent = "服务在线";
      elements.healthSummary.textContent = "已连接";
      setHealthValue(
        elements.healthLocal,
        isGuest ? "登录后可用" : features.local_processing ? "可用" : "暂不可用",
        isGuest || features.local_processing ? "" : "warn"
      );
      setHealthValue(
        elements.healthCloud,
        isGuest ? "登录后可用" : features.cloud_enhancement ? "可选" : "未启用",
        isGuest || features.cloud_enhancement ? "" : "warn"
      );
      const filesReady = isGuest
        ? Boolean(features.guest_media)
        : Boolean(features.uploads && features.media);
      setHealthValue(
        elements.healthFiles,
        filesReady ? isGuest ? "免登录可用" : "可用" : "部分受限",
        filesReady ? "" : "warn"
      );
      elements.bilibiliChip.classList.toggle("unavailable", platforms.bilibili === false);
      elements.douyinChip.classList.toggle(
        "unavailable",
        platforms.douyin === false
      );
      const uploads = isGuest ? {} : state.capabilities.uploads || {};
      const uploadsEnabled = !isGuest && uploads.enabled !== false;
      if (!isGuest) {
        state.uploadMaxBytes = Number(uploads.max_bytes || state.uploadMaxBytes);
        state.uploadExtensions = Array.isArray(uploads.allowed_extensions) ? uploads.allowed_extensions : [];
        elements.uploadLimit.textContent = `最大 ${formatBytes(state.uploadMaxBytes)}`;
      } else {
        const guestMedia = state.capabilities.guest_media || {};
        elements.uploadLimit.textContent = "登录后可上传";
        elements.guestAccessBanner.querySelector("strong").textContent = guestMedia.enabled
          ? `免登录可提取视频或音频，最长 ${Math.max(1, Math.round(Number(guestMedia.max_duration_seconds || 0) / 60))} 分钟`
          : "免登录媒体提取暂不可用";
      }
      elements.uploadChip.classList.toggle(
        "unavailable",
        !uploadsEnabled || platforms.upload === false
      );
      const media = isGuest
        ? state.capabilities.guest_media || {}
        : state.capabilities.media || {};
      state.mediaEnabled = media.enabled !== false && (!isGuest || features.guest_media === true);
      if (!state.mediaEnabled && !isGuest && selectedOperation() !== "subtitle") {
        setSelectedOperation("subtitle");
      }
      if (!uploadsEnabled && selectedInputMode() === "upload") setInputMode("link");
      else syncInputMode();
      elements.loginSection.hidden = isGuest || !features.bilibili_qr_login;
    } catch (_) {
      elements.serviceState.className = "service-state offline";
      elements.serviceLabel.textContent = "服务异常";
      elements.healthSummary.textContent = "连接失败";
      setHealthValue(elements.healthLocal, "无法读取", "error");
      setHealthValue(elements.healthCloud, "无法读取", "error");
      setHealthValue(elements.healthFiles, "无法读取", "error");
      elements.bilibiliChip.classList.add("unavailable");
      elements.douyinChip.classList.add("unavailable");
      elements.uploadChip.classList.add("unavailable");
      state.mediaEnabled = false;
      if (!state.guest && selectedOperation() !== "subtitle") setSelectedOperation("subtitle");
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
    if (
      selectedOperation() === "subtitle"
      && ["high_accuracy", "economy"].includes(selectedAsrMode())
    ) {
      requestCloudConfirmation(action);
      return;
    }
    if (selectedInputMode() === "upload") runUpload(false);
    else runExtraction();
  }

  elements.form.addEventListener("submit", (event) => {
    event.preventDefault();
    submitCurrentForm();
  });
  elements.form.querySelectorAll('input[name="input-mode"]').forEach((radio) => {
    radio.addEventListener("change", () => {
      syncInputMode();
      savePreferences();
    });
  });
  elements.form.querySelectorAll('input[name="operation"]').forEach((radio) => {
    radio.addEventListener("change", () => {
      syncInputMode();
      savePreferences();
    });
  });
  [elements.railSubtitle, elements.railVideo, elements.railAudio].forEach((button) => {
    button.addEventListener("click", () => {
      if (state.busy || button.disabled) return;
      setSelectedOperation(button.dataset.operation || "subtitle");
      setMobileView("compose");
      elements.composerPane.scrollTo({ top: 0, behavior: "smooth" });
      savePreferences();
    });
  });
  elements.railNewTask.addEventListener("click", () => {
    if (state.busy) {
      showToast("当前任务完成后即可新建任务。", true);
      return;
    }
    setSelectedOperation(state.guest ? "video" : "subtitle");
    setInputMode("link");
    elements.input.value = "";
    elements.inputError.textContent = "";
    elements.input.classList.remove("invalid");
    elements.forceRefresh.checked = false;
    setUploadFile(null);
    hidePageSelector();
    updatePlatformDetect();
    setMobileView("compose");
    elements.composerPane.scrollTo({ top: 0, behavior: "smooth" });
    elements.input.focus();
  });
  elements.form.querySelectorAll('input[name="asr-mode"]').forEach((radio) => {
    radio.addEventListener("change", () => {
      syncPrecisionOptions();
      savePreferences();
    });
  });
  elements.form.querySelectorAll('input[name="source"]').forEach((radio) => {
    radio.addEventListener("change", savePreferences);
  });
  elements.embeddedSubtitles.addEventListener("change", () => {
    if (elements.embeddedSubtitles.checked) {
      setSelectedSource("auto");
    }
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
    if (selectedInputMode() === "upload") {
      setUploadFile(null);
      return;
    }
    elements.input.value = "";
    elements.inputError.textContent = "";
    elements.input.classList.remove("invalid");
    updatePlatformDetect();
    hidePageSelector();
    elements.input.focus();
  });
  elements.copyResult.addEventListener("click", copyResult);
  elements.downloadResult.addEventListener("click", downloadResult);
  elements.retryAccurate.addEventListener("click", retryAccurate);
  elements.cancelJob.addEventListener("click", cancelCurrentJob);
  elements.format.addEventListener("change", () => {
    savePreferences();
    if (selectedOperation() === "subtitle" && selectedInputMode() === "link" && !state.busy && state.current && state.current.input === elements.input.value.trim()) {
      if (["high_accuracy", "economy"].includes(selectedAsrMode())) {
        requestCloudConfirmation(() => runExtraction({
          force_refresh: false,
          cloud_consent: true
        }));
      } else {
        runExtraction({ force_refresh: false });
      }
    }
  });
  elements.lang.addEventListener("change", savePreferences);
  elements.allowPlatformAi.addEventListener("change", savePreferences);
  elements.useCookie.addEventListener("change", () => {
    savePreferences();
    schedulePageLookup();
  });
  elements.pageSelect.addEventListener("change", () => {
    if (!state.biliBaseUrl) return;
    elements.input.value = `${state.biliBaseUrl}?p=${encodeURIComponent(elements.pageSelect.value)}`;
    updatePlatformDetect();
  });
  elements.resultSearch.addEventListener("input", renderOutputContent);
  elements.toggleRaw.addEventListener("click", toggleRawVersion);
  elements.toggleWrap.addEventListener("click", () => {
    state.wrapOutput = !state.wrapOutput;
    applyWrapPreference();
    savePreferences();
  });
  elements.mobileCompose.addEventListener("click", () => setMobileView("compose"));
  elements.mobileResult.addEventListener("click", () => setMobileView("result"));
  elements.healthTrigger.addEventListener("click", () => {
    setHealthPopover(elements.healthPopover.hidden);
  });
  elements.accountTrigger.addEventListener("click", () => {
    setAccountMenu(elements.accountPopover.hidden);
  });
  elements.openPasswordDialog.addEventListener("click", () => setPasswordDialog(true));
  elements.closePasswordDialog.addEventListener("click", () => setPasswordDialog(false));
  elements.cancelPasswordDialog.addEventListener("click", () => setPasswordDialog(false));
  elements.passwordForm.addEventListener("submit", changeAccountPassword);
  elements.logoutAllDevices.addEventListener("click", logoutAllDevices);
  elements.passwordDialog.addEventListener("click", (event) => {
    if (event.target === elements.passwordDialog) setPasswordDialog(false);
  });
  elements.cloudConfirmCheck.addEventListener("change", () => {
    elements.submitCloudConfirm.disabled = !elements.cloudConfirmCheck.checked;
  });
  elements.closeCloudConfirm.addEventListener("click", () => setCloudConfirmDialog(false, false));
  elements.cancelCloudConfirm.addEventListener("click", () => setCloudConfirmDialog(false, true));
  elements.submitCloudConfirm.addEventListener("click", confirmCloudAction);
  elements.cloudConfirmDialog.addEventListener("click", (event) => {
    if (event.target === elements.cloudConfirmDialog) setCloudConfirmDialog(false, false);
  });
  document.addEventListener("click", (event) => {
    if (!elements.healthPopover.hidden && !event.target.closest(".health-menu")) {
      setHealthPopover(false);
    }
    if (!elements.accountPopover.hidden && !event.target.closest(".account-area")) {
      setAccountMenu(false);
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    setHealthPopover(false);
    setAccountMenu(false);
    if (!elements.passwordDialog.hidden) setPasswordDialog(false);
    if (!elements.cloudConfirmDialog.hidden) setCloudConfirmDialog(false, false);
  });
  elements.clearHistory.addEventListener("click", () => {
    state.history = [];
    saveHistory();
    renderHistory();
  });
  elements.loginStart.addEventListener("click", startLogin);
  elements.logoutAccount.addEventListener("click", logoutAccount);

  async function initializeApp() {
    renderHistory();
    applyWrapPreference();
    setMobileView("compose");
    updatePlatformDetect();
    syncInputMode();
    await loadAccount();
    await loadHealth();
    requestAnimationFrame(() => document.body.classList.add("app-ready"));
  }

  initializeApp();
  setInterval(loadHealth, 30000);
})();
