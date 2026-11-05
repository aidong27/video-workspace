/* 字幕工作台 · owner console: activation codes, the Bilibili login, the gate log. */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const calm = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const TABS = ["members", "bilibili", "gate", "system"];
  const THEME_KEY = "video-workspace-theme";
  const THEME_MODES = ["system", "light", "dark"];
  const THEME_LABELS = { system: "跟随系统", light: "浅色", dark: "深色" };
  const CODE_GLYPHS = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
  const STATE_PILL = {
    active: ["有效", "ok"],
    disabled: ["已停用", "bad"],
    expired: ["已过期", "warn"],
    no_code: ["无激活码", "warn"]
  };
  const DENIED_DETAIL = {
    unknown: "未知激活码",
    malformed: "格式不对",
    revoked: "用了已停用的激活码",
    expired: "用了过期的激活码"
  };

  const state = {
    members: [],
    defaults: {},
    gate: null,
    bili: null,
    tab: "members",
    qr: null,
    editing: null,
    lastCode: null,
    logoutAfterCode: false,
    returnFocus: null,
    toastTimer: null
  };

  /* ---------- Helpers ---------- */

  async function api(path, options) {
    const init = Object.assign({ cache: "no-store", credentials: "same-origin" }, options || {});
    if (init.body !== undefined && typeof init.body !== "string") {
      init.body = JSON.stringify(init.body);
      init.headers = Object.assign({ "Content-Type": "application/json" }, init.headers || {});
    }
    const response = await fetch(path, init);
    if (response.status === 401) {
      window.location.replace("/login");
      throw new Error("验证已失效。");
    }
    const data = await response.json().catch(() => ({}));
    const detail = data && data.detail;
    if (response.status === 403 && detail && detail.reason === "admin_required") {
      window.location.replace("/");
      throw new Error("需要站长权限。");
    }
    if (!response.ok) {
      const message = detail && typeof detail === "object" ? detail.message : typeof detail === "string" ? detail : "";
      throw new Error(message || `请求失败（${response.status}）`);
    }
    return data;
  }

  function toast(message, error) {
    const element = $("toast");
    clearTimeout(state.toastTimer);
    element.textContent = message;
    element.classList.toggle("error", Boolean(error));
    element.classList.add("visible");
    state.toastTimer = setTimeout(() => element.classList.remove("visible"), 2800);
  }

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function firstChar(label) {
    return (Array.from(String(label || "?"))[0] || "?").toUpperCase();
  }

  function stamp(timestamp) {
    if (!timestamp) return "—";
    return new Intl.DateTimeFormat("zh-CN", {
      month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false
    }).format(new Date(timestamp * 1000));
  }

  function ago(timestamp) {
    if (!timestamp) return "从未";
    const diff = Date.now() / 1000 - Number(timestamp);
    if (diff < 60) return "刚刚";
    if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`;
    if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`;
    if (diff < 86400 * 30) return `${Math.floor(diff / 86400)} 天前`;
    return stamp(timestamp);
  }

  function expiresIn(timestamp) {
    const diff = Number(timestamp) - Date.now() / 1000;
    if (diff <= 0) return "已过期";
    if (diff < 3600) return `${Math.ceil(diff / 60)} 分钟后到期`;
    if (diff < 86400) return `${Math.ceil(diff / 3600)} 小时后到期`;
    return `${Math.ceil(diff / 86400)} 天后到期`;
  }

  function countUp(element, value, suffix) {
    const target = Math.round(Number(value) || 0);
    const start = Number(element.dataset.value || 0);
    element.dataset.value = String(target);
    const tail = suffix || "";
    if (calm() || start === target) {
      element.textContent = `${target}${tail}`;
      return;
    }
    const began = performance.now();
    const step = (now) => {
      const progress = Math.min(1, (now - began) / 750);
      const eased = 1 - Math.pow(1 - progress, 3);
      element.textContent = `${Math.round(start + (target - start) * eased)}${tail}`;
      if (progress < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  async function copyText(text) {
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
    const toggle = $("theme-toggle");
    toggle.dataset.mode = mode;
    toggle.title = `外观：${THEME_LABELS[mode]}`;
  }

  function cycleTheme() {
    const next = THEME_MODES[(THEME_MODES.indexOf(storedTheme()) + 1) % THEME_MODES.length];
    try {
      if (next === "system") localStorage.removeItem(THEME_KEY);
      else localStorage.setItem(THEME_KEY, next);
    } catch (_) {
      /* still applies to this page */
    }
    const apply = () => applyTheme(next);
    if (window.FX && window.FX.themeTransition) window.FX.themeTransition(apply, $("theme-toggle"));
    else apply();
    toast(`外观：${THEME_LABELS[next]}`);
  }

  /* ---------- Dialogs ---------- */

  function openDialog(id) {
    const dialog = $(id);
    if (!dialog.hidden) return;
    state.returnFocus = document.activeElement;
    dialog.hidden = false;
    document.body.classList.add("dialog-open");
    requestAnimationFrame(() => {
      const target = dialog.querySelector("input:not([type=hidden]), select, .primary-dialog-button");
      if (target) target.focus();
    });
  }

  function closeDialog(id) {
    const dialog = $(id);
    if (dialog.hidden) return;
    dialog.hidden = true;
    if (!document.querySelector(".dialog-backdrop:not([hidden])")) document.body.classList.remove("dialog-open");
    if (id === "code-dialog") {
      $("code-value").textContent = "";
      state.lastCode = null;
      if (state.logoutAfterCode) {
        window.location.replace("/login");
        return;
      }
    }
    const target = state.returnFocus;
    state.returnFocus = null;
    if (target && target.isConnected && typeof target.focus === "function") target.focus();
  }

  document.querySelectorAll(".dialog-backdrop").forEach((dialog) => {
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog || (event.target instanceof Element && event.target.closest("[data-close]"))) {
        closeDialog(dialog.id);
      }
    });
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    const open = Array.from(document.querySelectorAll(".dialog-backdrop:not([hidden])")).pop();
    if (open) closeDialog(open.id);
  });

  /* ---------- Code reveal ---------- */

  function scramble(target, code) {
    if (calm()) {
      target.textContent = code;
      return;
    }
    const started = performance.now();
    const duration = 1200;
    const frame = (now) => {
      if (!state.lastCode || state.lastCode.code !== code) return;
      const progress = Math.min(1, (now - started) / duration);
      const settled = Math.floor(progress * code.length);
      const noise = code.slice(settled).replace(/[^-]/g, () => CODE_GLYPHS[Math.floor(Math.random() * CODE_GLYPHS.length)]);
      target.textContent = code.slice(0, settled);
      if (noise) target.appendChild(el("span", "scramble", noise));
      if (progress < 1) requestAnimationFrame(frame);
      else target.textContent = code;
    };
    requestAnimationFrame(frame);
  }

  function showCode(label, code) {
    state.lastCode = { label, code };
    $("code-member").textContent = label;
    openDialog("code-dialog");
    scramble($("code-value"), code);
    if (window.FX && window.FX.burst) {
      const rect = $("code-value").getBoundingClientRect();
      window.FX.burst(rect.left + rect.width / 2, rect.top + rect.height / 2);
    }
  }

  $("copy-code").addEventListener("click", async () => {
    if (!state.lastCode) return;
    await copyText(state.lastCode.code);
    toast("激活码已复制");
  });

  $("copy-invite").addEventListener("click", async () => {
    if (!state.lastCode) return;
    const { label, code } = state.lastCode;
    await copyText(
      `${label}，这是字幕工作台的激活码：\n${code}\n\n打开 ${window.location.origin} 输入即可使用。`
      + "这个码只给你一个人用，请不要外传。"
    );
    toast("邀请文案已复制");
  });

  /* ---------- Members ---------- */

  async function loadMembers() {
    const data = await api("/api/admin/members");
    state.members = Array.isArray(data.members) ? data.members : [];
    state.defaults = data.defaults || {};
    renderMembers();
    renderStats();
  }

  function renderMembers() {
    const grid = $("member-grid");
    const defaults = state.defaults;
    const jobs = defaults.daily_job_limit ? `每天 ${defaults.daily_job_limit} 个任务` : "每天不限任务数";
    $("member-defaults").textContent = `新成员默认最多 ${defaults.max_devices || 3} 台设备、${jobs}、`
      + `同时最多 ${defaults.max_active_jobs || 2} 个任务；站长不受这些限制。`;
    document.querySelectorAll("#issue-dialog option[data-default]").forEach((option) => {
      option.textContent = option.parentElement.id === "issue-devices"
        ? `默认（${defaults.max_devices || 3} 台）`
        : `默认（${defaults.daily_job_limit ? `${defaults.daily_job_limit} 次` : "不限"}）`;
    });
    grid.textContent = "";
    if (!state.members.length) {
      const empty = el("div", "member-empty");
      empty.append(el("strong", "", "还没有成员"), el("span", "", "点「发放激活码」给第一位朋友发码。"));
      grid.appendChild(empty);
      return;
    }
    state.members.forEach((member, index) => grid.appendChild(memberCard(member, index)));
  }

  function memberCard(member, index) {
    const classes = ["panel", "member"];
    if (member.role === "owner") classes.push("owner");
    if (member.state !== "active") classes.push(member.state);
    const card = el("article", classes.join(" "));
    card.dataset.id = String(member.id);
    card.style.setProperty("--i", String(Math.min(index, 12)));

    const head = el("header", "member-head");
    const title = el("div");
    title.append(
      el("strong", "", member.label),
      el("small", "", member.role === "owner" ? "站长 · 不受限制" : `${ago(member.created_at)}加入`)
    );
    const [pillText, pillTone] = STATE_PILL[member.state] || ["未知", ""];
    head.append(el("span", "member-avatar", firstChar(member.label)), title, el("span", `pill ${pillTone}`, pillText));
    card.appendChild(head);

    const code = el("div", "member-code");
    if (member.code) {
      code.append(
        el("code", "", `•••• •••• ${member.code.hint}`),
        el("small", "", member.code.expires_at ? expiresIn(member.code.expires_at) : "长期有效")
      );
    } else {
      code.append(el("code", "", "没有可用的激活码"), el("small", "", "点「生成激活码」"));
    }
    card.appendChild(code);

    const limit = Number(member.daily_job_limit || 0);
    const used = Number(member.jobs_today || 0);
    const meter = el("div", `meter${limit && used >= limit ? " full" : ""}`);
    const meterLabel = el("div", "meter-label");
    meterLabel.append(el("span", "", "今日任务"), el("span", "", limit ? `${used} / ${limit}` : `${used} · 不限`));
    const bar = el("i");
    const fill = el("b");
    fill.style.setProperty("--v", limit ? String(Math.min(1, used / limit)) : used ? "1" : "0");
    bar.appendChild(fill);
    meter.append(meterLabel, bar);
    card.appendChild(meter);

    const meta = el("div", "member-meta");
    const lastUsed = (member.code && member.code.last_used_at) || member.last_login_at;
    meta.append(
      el("span", "", `设备 ${member.devices.length}/${member.max_devices}`),
      el("span", "", `最近验证 ${ago(lastUsed)}`),
      el("span", "", `累计验证 ${member.code ? member.code.use_count : 0} 次`)
    );
    card.appendChild(meta);

    if (member.devices.length) {
      const details = el("details", "devices");
      details.appendChild(el("summary", "", `${member.devices.length} 台已验证设备`));
      const list = el("ul");
      member.devices.forEach((device) => {
        const item = el("li");
        const info = el("span");
        info.append(el("strong", "", device.device), el("small", "", `${device.ip || "未知地址"} · ${ago(device.last_seen_at)}活跃`));
        const kick = el("button", "chip-button", "下线");
        kick.type = "button";
        kick.dataset.action = "kick";
        kick.dataset.session = String(device.id);
        item.append(info, kick);
        list.appendChild(item);
      });
      details.appendChild(list);
      card.appendChild(details);
    }

    const actions = el("footer", "member-actions");
    const add = (action, label, extra) => {
      const button = el("button", `chip-button${extra ? ` ${extra}` : ""}`, label);
      button.type = "button";
      button.dataset.action = action;
      actions.appendChild(button);
    };
    add("reset", member.code ? "重置激活码" : "生成激活码");
    add("edit", "编辑");
    if (member.role !== "owner") add("toggle", member.state === "disabled" ? "启用" : "停用");
    if (member.devices.length) add("signout", "全部下线");
    if (member.role !== "owner") add("delete", "删除", "danger");
    card.appendChild(actions);
    return card;
  }

  async function memberAction(button, member) {
    const action = button.dataset.action;
    const owner = member.role === "owner";
    if (action === "edit") {
      openEdit(member);
      return;
    }
    if (action === "reset") {
      const warning = owner
        ? "重置后你自己的激活码会立刻失效，包括当前这台设备在内的所有设备都要用新码重新验证。继续吗？"
        : `重置后，${member.label} 现在的激活码会立刻失效，TA 的设备需要用新码重新验证。继续吗？`;
      if (member.code && !window.confirm(warning)) return;
      const data = await api(`/api/admin/members/${member.id}/reset`, { method: "POST" });
      state.logoutAfterCode = owner;
      showCode(member.label, data.code);
      if (!owner) await loadMembers();
      return;
    }
    if (action === "toggle") {
      const enable = member.state === "disabled";
      if (!enable && !window.confirm(`停用 ${member.label}？TA 的所有设备会立即退出，激活码也无法再用。`)) return;
      await api(`/api/admin/members/${member.id}`, { method: "PATCH", body: { active: enable } });
      toast(enable ? `已启用 ${member.label}` : `已停用 ${member.label}`);
    } else if (action === "signout") {
      const warning = owner ? "让你的所有设备下线（包括这一台）？" : `让 ${member.label} 的所有设备下线？TA 可以用激活码重新验证。`;
      if (!window.confirm(warning)) return;
      await api(`/api/admin/members/${member.id}/sign-out`, { method: "POST" });
      toast("已全部下线");
    } else if (action === "kick") {
      await api(`/api/admin/members/${member.id}/sessions/${encodeURIComponent(button.dataset.session)}`, { method: "DELETE" });
      toast("这台设备已下线");
    } else if (action === "delete") {
      if (!window.confirm(`删除 ${member.label}？激活码、设备和用量记录会一起删除，无法恢复。`)) return;
      await api(`/api/admin/members/${member.id}`, { method: "DELETE" });
      toast(`已删除 ${member.label}`);
    }
    await loadMembers();
  }

  $("member-grid").addEventListener("click", async (event) => {
    const button = event.target instanceof Element ? event.target.closest("button[data-action]") : null;
    if (!button) return;
    const card = button.closest(".member");
    const member = state.members.find((item) => String(item.id) === card.dataset.id);
    if (!member) return;
    button.disabled = true;
    try {
      await memberAction(button, member);
    } catch (error) {
      toast(error.message, true);
    } finally {
      button.disabled = false;
    }
  });

  /* ---------- Issue and edit ---------- */

  $("issue-open").addEventListener("click", () => {
    $("issue-form").reset();
    $("issue-error").textContent = "";
    openDialog("issue-dialog");
  });

  $("issue-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const label = $("issue-label").value.trim();
    if (!label) {
      $("issue-error").textContent = "写一下这个激活码给谁用。";
      $("issue-label").focus();
      return;
    }
    const body = { label, expires_in_days: Number($("issue-days").value) || null };
    if ($("issue-devices").value) body.max_devices = Number($("issue-devices").value);
    if ($("issue-jobs").value !== "") body.daily_job_limit = Number($("issue-jobs").value);
    const submit = $("issue-submit");
    submit.disabled = true;
    $("issue-error").textContent = "";
    try {
      const data = await api("/api/admin/members", { method: "POST", body });
      closeDialog("issue-dialog");
      state.logoutAfterCode = false;
      showCode(label, data.code);
      await loadMembers();
    } catch (error) {
      $("issue-error").textContent = error.message;
    } finally {
      submit.disabled = false;
    }
  });

  function openEdit(member) {
    state.editing = member;
    $("edit-title").textContent = `编辑 ${member.label}`;
    $("edit-label").value = member.label;
    $("edit-days").value = "keep";
    $("edit-days").disabled = !member.code;
    $("edit-devices").value = member.max_devices_override ? String(member.max_devices_override) : "";
    $("edit-jobs").value = member.daily_job_limit_override === null || member.daily_job_limit_override === undefined
      ? "" : String(member.daily_job_limit_override);
    if ($("edit-devices").value === "" && member.max_devices_override) $("edit-devices").value = "";
    $("edit-error").textContent = "";
    openDialog("edit-dialog");
  }

  $("edit-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const member = state.editing;
    if (!member) return;
    const label = $("edit-label").value.trim();
    if (!label) {
      $("edit-error").textContent = "名称不能为空。";
      return;
    }
    const body = {
      label,
      max_devices: $("edit-devices").value ? Number($("edit-devices").value) : null,
      daily_job_limit: $("edit-jobs").value === "" ? null : Number($("edit-jobs").value)
    };
    if ($("edit-days").value !== "keep") body.expires_in_days = Number($("edit-days").value);
    const submit = $("edit-submit");
    submit.disabled = true;
    try {
      await api(`/api/admin/members/${member.id}`, { method: "PATCH", body });
      closeDialog("edit-dialog");
      toast("已保存");
      await loadMembers();
    } catch (error) {
      $("edit-error").textContent = error.message;
    } finally {
      submit.disabled = false;
    }
  });

  /* ---------- Bilibili account ---------- */

  async function loadBili(refresh) {
    try {
      state.bili = await api(`/api/admin/bilibili${refresh ? "?refresh=true" : ""}`);
    } catch (error) {
      state.bili = { state: "unknown", message: error.message };
    }
    renderBili();
    renderStats();
  }

  function renderBili() {
    const status = state.bili || {};
    let title = "还没有登录 B站";
    let sub = "扫码后，所有成员都能读取 B站字幕、分 P 和视频";
    let pill = ["未登录", "warn"];
    if (status.state === "ok") {
      title = status.uname || "已登录";
      sub = [status.mid ? `UID ${status.mid}` : "", Number.isFinite(status.level) ? `Lv${status.level}` : "",
        status.vip ? status.vip_label || "大会员" : ""].filter(Boolean).join(" · ") || "登录有效";
      pill = ["已登录", "ok"];
    } else if (status.state === "expired") {
      title = "B站登录已失效";
      sub = "重新扫码即可恢复";
      pill = ["已失效", "bad"];
    } else if (status.state === "blocked") {
      title = "B站暂时拒绝了本站";
      sub = "登录还在，冷却结束后会自动重试";
      pill = ["受限", "warn"];
    } else if (status.state === "unknown") {
      title = "暂时无法确认登录状态";
      sub = status.message || "稍后再刷新试试";
      pill = ["未知", "warn"];
    }
    $("bili-title").textContent = title;
    $("bili-sub").textContent = sub;
    const pillElement = $("bili-state");
    pillElement.className = `pill ${pill[1]}`;
    pillElement.textContent = pill[0];
    const details = $("bili-details");
    details.textContent = "";
    const add = (term, value) => {
      const row = el("div");
      row.append(el("dt", "", term), el("dd", "", value));
      details.appendChild(row);
    };
    add("登录保存于", status.saved_at ? stamp(status.saved_at) : "—");
    add("最近确认", status.checked_at ? ago(status.checked_at) : "—");
    add("请求方式", status.state && status.state !== "none" ? "登录态 · 顺序限速" : "匿名（会被拒绝）");
    add("可见范围", "仅站长");
    $("bili-login").querySelector("span").textContent = status.state && status.state !== "none" ? "重新扫码" : "扫码登录";
    $("bili-logout").hidden = !status.state || status.state === "none";
  }

  function stopQr() {
    if (state.qr) {
      clearInterval(state.qr.poll);
      clearInterval(state.qr.tick);
    }
    state.qr = null;
  }

  function qrStatus(title, detail) {
    $("qr-status").textContent = title;
    $("qr-detail").textContent = detail || "";
  }

  function expireQr(message) {
    stopQr();
    $("qr-card").classList.remove("scanned");
    $("qr-card").classList.add("expired");
    qrStatus("二维码已过期", message || "重新生成一个再扫");
    $("qr-again").hidden = false;
  }

  function tickQr() {
    const qr = state.qr;
    if (!qr) return;
    const left = Math.max(0, (qr.expires - Date.now()) / 1000);
    $("qr-ring").style.strokeDashoffset = String(100 - (left / qr.total) * 100);
    if (left <= 0) expireQr();
  }

  async function pollQr() {
    const qr = state.qr;
    if (!qr || qr.busy) return;
    qr.busy = true;
    const card = $("qr-card");
    try {
      const data = await api(`/api/admin/bilibili/qrcode/${encodeURIComponent(qr.key)}`);
      if (state.qr !== qr) return;
      if (data.status === "waiting_confirm") {
        card.classList.add("scanned");
        qrStatus("已扫码", "请在手机上点「确认登录」");
      } else if (data.status === "waiting_scan") {
        qrStatus("用 B站 App 扫一扫", "打开 B站 App，点右上角的扫一扫");
      } else if (data.status === "success") {
        stopQr();
        card.classList.remove("scanned");
        card.classList.add("success");
        const account = data.account || {};
        qrStatus("登录成功", account.uname ? `欢迎，${account.uname}` : "B站登录已保存");
        state.bili = account;
        renderBili();
        renderStats();
        toast("B站登录成功，所有成员现在都能读取 B站内容了");
        if (window.FX && window.FX.burst) {
          const rect = card.querySelector(".qr-frame").getBoundingClientRect();
          window.FX.burst(rect.left + rect.width / 2, rect.top + rect.height / 2);
        }
        setTimeout(() => { if (!state.qr) card.hidden = true; }, 3200);
      } else if (data.status === "expired") {
        expireQr(data.message);
      } else if (data.status === "failed") {
        stopQr();
        qrStatus("登录没有完成", data.message || "重新生成二维码再试一次");
        $("qr-again").hidden = false;
      } else if (data.message) {
        $("qr-detail").textContent = data.message;
      }
    } catch (error) {
      $("qr-detail").textContent = error.message;
    } finally {
      qr.busy = false;
    }
  }

  async function startQr() {
    stopQr();
    const card = $("qr-card");
    card.hidden = false;
    card.className = "panel qr-card";
    $("qr-again").hidden = true;
    $("qr-image").removeAttribute("src");
    $("qr-ring").style.strokeDashoffset = "0";
    qrStatus("正在生成二维码…", "");
    card.scrollIntoView({ block: "nearest", behavior: calm() ? "auto" : "smooth" });
    try {
      const data = await api("/api/admin/bilibili/qrcode", { method: "POST" });
      $("qr-image").src = data.qr_svg_data_url;
      state.qr = {
        key: data.qrcode_key,
        total: Number(data.expires_in) || 180,
        expires: Date.now() + (Number(data.expires_in) || 180) * 1000,
        poll: setInterval(pollQr, 2000),
        tick: setInterval(tickQr, 1000),
        busy: false
      };
      qrStatus("用 B站 App 扫一扫", "打开 B站 App，点右上角的扫一扫");
      tickQr();
    } catch (error) {
      qrStatus("二维码获取失败", error.message);
      $("qr-again").hidden = false;
    }
  }

  $("bili-login").addEventListener("click", startQr);
  $("qr-again").addEventListener("click", startQr);
  $("qr-cancel").addEventListener("click", () => {
    stopQr();
    $("qr-card").hidden = true;
  });
  $("bili-refresh").addEventListener("click", async () => {
    $("bili-refresh").disabled = true;
    await loadBili(true);
    $("bili-refresh").disabled = false;
    toast("已刷新 B站登录状态");
  });
  $("bili-logout").addEventListener("click", async () => {
    if (!window.confirm("退出后，本站不再以你的 B站账号发请求，成员读取 B站内容会受限。确定退出？")) return;
    try {
      const data = await api("/api/admin/bilibili", { method: "DELETE" });
      toast(data.remote_signed_out ? "已退出，并在 B站注销了这次登录" : "已删除本站保存的 B站登录");
      await loadBili(true);
    } catch (error) {
      toast(error.message, true);
    }
  });

  /* ---------- Gate log ---------- */

  async function loadGate() {
    try {
      state.gate = await api("/api/admin/gate");
    } catch (error) {
      toast(error.message, true);
      return;
    }
    renderGate();
    renderStats();
  }

  function renderGate() {
    const data = state.gate || { summary: { locked: [] }, events: [] };
    const locked = $("gate-locked");
    locked.textContent = "";
    (data.summary.locked || []).forEach((item) => {
      const chip = el("div", "lock-chip");
      const minutes = Math.max(1, Math.ceil(item.retry_after / 60));
      chip.append(
        el("span", "", "已锁定"),
        el("code", "", item.ip),
        el("span", "", `失败 ${item.failures} 次 · 还剩 ${minutes} 分钟`)
      );
      const unlock = el("button", "chip-button", "解锁");
      unlock.type = "button";
      unlock.dataset.ip = item.ip;
      chip.appendChild(unlock);
      locked.appendChild(chip);
    });
    const list = $("gate-events");
    list.textContent = "";
    if (!data.events.length) {
      list.appendChild(el("li", "event-empty", "还没有人来敲过门。"));
      return;
    }
    data.events.forEach((item) => {
      const row = el("li", `event ${item.kind}`);
      const text = item.kind === "granted"
        ? `放行 · ${item.member || "成员"}`
        : `拦截 · ${DENIED_DETAIL[item.detail] || "激活码不正确"}${item.member ? ` · ${item.member}` : ""}`;
      row.append(el("i"), el("time", "", stamp(item.at)), el("span", "", text), el("code", "", item.ip));
      list.appendChild(row);
    });
  }

  $("gate-locked").addEventListener("click", async (event) => {
    const button = event.target instanceof Element ? event.target.closest("button[data-ip]") : null;
    if (!button) return;
    button.disabled = true;
    try {
      await api("/api/admin/gate/unlock", { method: "POST", body: { ip: button.dataset.ip } });
      toast(`已解锁 ${button.dataset.ip}`);
      await loadGate();
    } catch (error) {
      toast(error.message, true);
      button.disabled = false;
    }
  });

  /* ---------- System ---------- */

  const LABELS = {
    status: "总体状态", generated_at: "生成时间", version: "服务版本", active_users: "有效成员",
    worker_alive: "主 Worker", workers_alive: "在线 Worker", worker_count: "Worker 数量", queued: "排队任务",
    running: "运行任务", max_pending: "最大排队数", persistent_enabled: "常驻模式", exit_on_idle: "空闲退出",
    idle_seconds: "空闲阈值", idle_exit_in_seconds: "距空闲退出", alive: "进程存活", warm: "模型已预热",
    start_count: "启动次数", process_rss_mb: "进程内存", process_swap_mb: "进程交换", rss_mb: "子进程内存",
    swap_mb: "子进程交换", snapshot_consistent: "快照一致", system_available_mb: "系统可用内存",
    swap_total_mb: "交换总量", swap_used_mb: "已用交换", available: "可用", total_bytes: "总容量",
    free_bytes: "可用容量", free_ratio: "可用比例", minimum_free_bytes: "最低保留", upload_reservations: "上传预留",
    upload_reserved_bytes: "上传预留容量", media_reservations: "媒体预留", media_reserved_bytes: "媒体预留容量",
    enabled: "已启用", ready: "已就绪", paid_allowed: "允许付费", usage: "用量", failures: "失败",
    api_adapter_ready: "API 适配器", playwright_ready: "Playwright", chromium_ready: "Chromium",
    cookie_cached: "Cookie 缓存", ffmpeg: "FFmpeg", ffprobe: "FFprobe", bilibili: "B站", douyin: "抖音"
  };
  const SECTIONS = [
    ["service", "服务"], ["queue", "任务队列"], ["asr_worker", "本地识别进程"], ["memory", "内存"],
    ["disk", "磁盘"], ["temporary_storage", "临时空间"], ["cloud_asr", "云端识别"], ["platforms", "平台"],
    ["tools", "工具"]
  ];

  function formatBytes(value) {
    const units = ["B", "KB", "MB", "GB", "TB"];
    let size = Math.max(0, value);
    let unit = 0;
    while (size >= 1024 && unit < units.length - 1) {
      size /= 1024;
      unit += 1;
    }
    return `${size.toFixed(size >= 100 || unit === 0 ? 0 : 1)} ${units[unit]}`;
  }

  function formatValue(key, value) {
    if (value === null || value === undefined || value === "") return "—";
    if (typeof value === "boolean") return value ? "是" : "否";
    if (typeof value === "number" && Number.isFinite(value)) {
      if (key.endsWith("_bytes")) return formatBytes(value);
      if (key.endsWith("_mb")) return `${value.toLocaleString("zh-CN", { maximumFractionDigits: 1 })} MB`;
      if (key.endsWith("_ratio")) return `${(value * 100).toFixed(1)}%`;
      if (key.endsWith("_seconds")) return value < 60 ? `${Math.round(value)} 秒` : `${Math.round(value / 60)} 分钟`;
      if (key === "generated_at") return stamp(value);
      return value.toLocaleString("zh-CN", { maximumFractionDigits: 2 });
    }
    if (Array.isArray(value)) return value.length ? value.join("、") : "无";
    return String(value);
  }

  function flatten(value, prefix, rows, depth) {
    Object.entries(value || {}).forEach(([key, child]) => {
      if (rows.length >= 14) return;
      const label = prefix ? `${prefix} · ${LABELS[key] || key}` : LABELS[key] || key;
      if (child && typeof child === "object" && !Array.isArray(child) && depth < 2) flatten(child, label, rows, depth + 1);
      else if (!(child && typeof child === "object" && !Array.isArray(child))) rows.push({ key, label, value: child });
    });
    return rows;
  }

  async function loadSystem() {
    try {
      const data = await api("/api/admin/diagnostics");
      const grid = $("system-grid");
      grid.textContent = "";
      SECTIONS.forEach(([key, title]) => {
        if (!data[key]) return;
        const card = el("article", "panel system-card");
        card.appendChild(el("h3", "", title));
        const list = el("dl");
        flatten(data[key], "", [], 0).forEach((row) => {
          const item = el("div");
          const tone = typeof row.value === "boolean" ? (row.key === "paid_allowed" ? (row.value ? "warn" : "good") : row.value ? "good" : "bad") : "";
          item.append(el("dt", "", row.label), el("dd", tone, formatValue(row.key, row.value)));
          list.appendChild(item);
        });
        card.appendChild(list);
        grid.appendChild(card);
      });
      $("system-updated").textContent = `更新于 ${stamp(data.generated_at)} · 服务版本 ${data.service && data.service.version || "—"}`;
    } catch (error) {
      $("system-updated").textContent = error.message;
    }
  }

  $("system-refresh").addEventListener("click", loadSystem);

  /* ---------- Stats ---------- */

  function renderStats() {
    const members = state.members;
    const active = members.filter((member) => member.state === "active").length;
    const devices = members.reduce((total, member) => total + member.devices.length, 0);
    countUp($("stat-members"), members.length);
    $("stat-members-detail").textContent = `${active} 个激活码有效 · ${devices} 台设备已验证`;
    const jobs = members.reduce((total, member) => total + Number(member.jobs_today || 0), 0);
    countUp($("stat-jobs"), jobs);
    const busiest = members.filter((member) => member.jobs_today).sort((a, b) => b.jobs_today - a.jobs_today)[0];
    $("stat-jobs-detail").textContent = busiest ? `${busiest.label} 最活跃（${busiest.jobs_today} 次）` : "今天还没有任务";
    if (state.gate) {
      const summary = state.gate.summary;
      countUp($("stat-gate"), summary.denied_24h, " 次拦截");
      $("stat-gate-detail").textContent = `${summary.granted_24h} 次放行${summary.locked.length ? ` · ${summary.locked.length} 个地址被锁定` : ""}`;
    }
    if (state.bili) {
      const status = state.bili;
      $("stat-bili").textContent = status.state === "ok" ? status.uname || "已登录"
        : status.state === "expired" ? "已失效" : status.state === "none" ? "未登录" : "待确认";
      $("stat-bili-detail").textContent = status.state === "ok" ? "成员的 B站请求走这个账号" : "去「B站账号」扫码登录";
    }
  }

  /* ---------- Tabs ---------- */

  function moveInk() {
    const tab = $(`tab-${state.tab}`);
    const ink = $("tab-ink");
    ink.style.width = `${tab.offsetWidth}px`;
    ink.style.translate = `${tab.offsetLeft}px 0`;
  }

  function selectTab(name, focus) {
    if (!TABS.includes(name)) name = "members";
    state.tab = name;
    TABS.forEach((item) => {
      const active = item === name;
      const tab = $(`tab-${item}`);
      tab.setAttribute("aria-selected", String(active));
      tab.tabIndex = active ? 0 : -1;
      $(`panel-${item}`).hidden = !active;
    });
    moveInk();
    if (focus) $(`tab-${name}`).focus();
    if (window.location.hash !== `#${name}`) history.replaceState(null, "", `#${name}`);
    if (name === "bilibili") loadBili(false);
    if (name === "gate") loadGate();
    if (name === "system") loadSystem();
  }

  TABS.forEach((name, index) => {
    const tab = $(`tab-${name}`);
    tab.addEventListener("click", () => selectTab(name));
    tab.addEventListener("keydown", (event) => {
      if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
      event.preventDefault();
      const next = TABS[(index + (event.key === "ArrowRight" ? 1 : -1) + TABS.length) % TABS.length];
      selectTab(next, true);
    });
  });
  window.addEventListener("resize", moveInk);

  /* ---------- Start ---------- */

  $("theme-toggle").addEventListener("click", cycleTheme);
  applyTheme(storedTheme());

  if (window.FX && window.FX.palette && window.FX.palette.register) {
    window.FX.palette.register([
      { label: "发放激活码", hint: "给新朋友生成一个码", keys: "issue code new jihuoma fafang", icon: "plus",
        run: () => $("issue-open").click() },
      { label: "成员", hint: "激活码与设备", keys: "members chengyuan", icon: "list", run: () => selectTab("members") },
      { label: "B站账号", hint: "扫码登录与状态", keys: "bilibili bili zhanghao login saoma", icon: "shield",
        run: () => selectTab("bilibili") },
      { label: "扫码登录 B站", hint: "生成登录二维码", keys: "qr saoma login bilibili", icon: "play",
        run: () => { selectTab("bilibili"); startQr(); } },
      { label: "门卫日志", hint: "放行、拦截与锁定", keys: "gate log menwei rizhi", icon: "clock", run: () => selectTab("gate") },
      { label: "运行状态", hint: "队列、内存、磁盘", keys: "system status yunxing", icon: "code", run: () => selectTab("system") }
    ]);
  }

  async function start() {
    const initial = window.location.hash.replace("#", "");
    try {
      await loadMembers();
    } catch (error) {
      toast(error.message, true);
    }
    selectTab(TABS.includes(initial) ? initial : "members");
    if (state.tab !== "gate") loadGate();
    if (state.tab !== "bilibili") loadBili(false);
    requestAnimationFrame(() => document.body.classList.add("app-ready"));
  }

  start();
  setInterval(() => {
    if (document.hidden || document.querySelector(".dialog-backdrop:not([hidden])")) return;
    loadMembers().catch(() => {});
    loadGate();
  }, 30000);
})();
