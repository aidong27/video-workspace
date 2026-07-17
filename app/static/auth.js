(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const elements = {
    form: $("auth-form"),
    title: $("auth-title"),
    kicker: $("auth-kicker"),
    loginTab: $("login-tab"),
    registerTab: $("register-tab"),
    username: $("username"),
    password: $("password"),
    inviteField: $("invite-field"),
    inviteCode: $("invite-code"),
    confirmField: $("confirm-field"),
    confirmPassword: $("confirm-password"),
    error: $("form-error"),
    submit: $("submit-button"),
    submitLabel: $("submit-label"),
    authSwitch: $("auth-switch"),
    serviceStatus: $("service-status")
  };

  const isRegister = window.location.pathname === "/register";
  let registrationEnabled = true;

  function setMode() {
    document.title = `${isRegister ? "注册" : "登录"} - 视频字幕提取`;
    elements.title.textContent = isRegister ? "创建账号" : "登录";
    elements.kicker.textContent = isRegister ? "邀请注册" : "账号访问";
    elements.submitLabel.textContent = isRegister ? "注册并进入" : "登录";
    elements.loginTab.classList.toggle("active", !isRegister);
    elements.registerTab.classList.toggle("active", isRegister);
    elements.loginTab.setAttribute("aria-current", isRegister ? "false" : "page");
    elements.registerTab.setAttribute("aria-current", isRegister ? "page" : "false");
    elements.inviteField.hidden = !isRegister;
    elements.confirmField.hidden = !isRegister;
    elements.inviteCode.required = isRegister;
    elements.confirmPassword.required = isRegister;
    elements.password.autocomplete = isRegister ? "new-password" : "current-password";
    elements.authSwitch.innerHTML = isRegister
      ? '已有账号？<a href="/login">返回登录</a>'
      : '没有账号？<a href="/register">使用邀请码注册</a>';
  }

  function setLoading(loading) {
    elements.submit.disabled = loading || (isRegister && !registrationEnabled);
    elements.submit.classList.toggle("loading", loading);
  }

  function showError(message, field) {
    elements.error.textContent = message || "";
    [elements.username, elements.password, elements.inviteCode, elements.confirmPassword]
      .forEach((input) => input.classList.remove("invalid"));
    if (field) field.classList.add("invalid");
  }

  function responseMessage(data, status) {
    const detail = data && data.detail;
    if (detail && typeof detail === "object" && detail.message) return detail.message;
    if (typeof detail === "string") return detail;
    if (status === 429) return "尝试次数过多，请稍后再试。";
    if (status >= 500) return "服务暂时不可用，请稍后再试。";
    return isRegister ? "注册失败，请检查填写内容。" : "登录失败，请检查用户名和密码。";
  }

  function validate() {
    const username = elements.username.value.trim();
    const password = elements.password.value;
    if (!/^[A-Za-z0-9_.-]{3,32}$/.test(username)) {
      showError("用户名需为 3-32 位字母、数字、点、下划线或连字符。", elements.username);
      return false;
    }
    if (password.length < 8) {
      showError("密码至少需要 8 个字符。", elements.password);
      return false;
    }
    if (isRegister && !elements.inviteCode.value.trim()) {
      showError("请输入邀请码。", elements.inviteCode);
      return false;
    }
    if (isRegister && password !== elements.confirmPassword.value) {
      showError("两次输入的密码不一致。", elements.confirmPassword);
      return false;
    }
    showError("");
    return true;
  }

  async function submit(event) {
    event.preventDefault();
    if (!validate()) return;
    setLoading(true);
    const payload = {
      username: elements.username.value.trim(),
      password: elements.password.value
    };
    if (isRegister) payload.invite_code = elements.inviteCode.value.trim();
    try {
      const response = await fetch(isRegister ? "/api/auth/register" : "/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        showError(responseMessage(data, response.status));
        return;
      }
      window.location.replace("/");
    } catch (_) {
      showError("无法连接服务器，请检查网络后重试。");
    } finally {
      setLoading(false);
    }
  }

  async function loadStatus() {
    try {
      const response = await fetch("/api/health", { cache: "no-store" });
      if (!response.ok) throw new Error(String(response.status));
      const health = await response.json();
      registrationEnabled = Boolean(health.auth && health.auth.registration_enabled);
      elements.serviceStatus.className = "service-status online";
      elements.serviceStatus.querySelector("strong").textContent = "服务在线";
      if (isRegister && !registrationEnabled) {
        showError("服务器尚未开放邀请注册。");
        elements.submit.disabled = true;
      }
    } catch (_) {
      elements.serviceStatus.className = "service-status offline";
      elements.serviceStatus.querySelector("strong").textContent = "服务连接异常";
    }
  }

  elements.form.addEventListener("submit", submit);
  [elements.username, elements.password, elements.inviteCode, elements.confirmPassword].forEach((input) => {
    input.addEventListener("input", () => {
      input.classList.remove("invalid");
      if (elements.error.textContent) elements.error.textContent = "";
    });
  });

  setMode();
  loadStatus();
  elements.username.focus();
})();
