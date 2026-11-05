/* 字幕工作台 · effects.
   Pure decoration and shortcuts: it listens for the workspace:* events that
   app.js dispatches and never changes what a task does. With reduced motion
   every animation is skipped; the command palette still works. */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const motionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
  const calm = () => motionQuery.matches;
  const CONFETTI = ["#7c5cff", "#e255ff", "#38e1ff", "#ff6b9d", "#ffd36e"];
  let glow = [124, 92, 255];

  function readGlow() {
    const value = getComputedStyle(document.body).getPropertyValue("--glow");
    const parts = value.split(",").map((item) => Number(item.trim()));
    glow = parts.length === 3 && parts.every(Number.isFinite) ? parts : [124, 92, 255];
  }

  function rgba(alpha, color) {
    const [r, g, b] = color || glow;
    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
  }

  function visible(id) {
    const element = $(id);
    return Boolean(element && !element.hidden && element.getClientRects().length);
  }

  function formatTime(seconds) {
    const value = Math.max(0, Math.floor(seconds));
    const hours = Math.floor(value / 3600);
    const minutes = Math.floor((value % 3600) / 60);
    const secs = String(value % 60).padStart(2, "0");
    return hours ? `${hours}:${String(minutes).padStart(2, "0")}:${secs}` : `${String(minutes).padStart(2, "0")}:${secs}`;
  }

  /* ---------- Spotlight and magnetic button ---------- */

  let pointerFrame = 0;
  let pointerEvent = null;
  let litPanel = null;

  function magnet(event) {
    const button = $("extract-button");
    if (!button) return;
    if (calm() || button.disabled || !event) {
      button.style.setProperty("--tx", "0px");
      button.style.setProperty("--ty", "0px");
      return;
    }
    const rect = button.getBoundingClientRect();
    const reachX = rect.width / 2 + 80;
    const reachY = rect.height / 2 + 60;
    const dx = event.clientX - (rect.left + rect.width / 2);
    const dy = event.clientY - (rect.top + rect.height / 2);
    const inside = Math.abs(dx) < reachX && Math.abs(dy) < reachY;
    button.style.setProperty("--tx", inside ? `${((dx / reachX) * 7).toFixed(2)}px` : "0px");
    button.style.setProperty("--ty", inside ? `${((dy / reachY) * 5).toFixed(2)}px` : "0px");
  }

  document.addEventListener("pointermove", (event) => {
    if (event.pointerType === "touch") return;
    pointerEvent = event;
    if (pointerFrame) return;
    pointerFrame = requestAnimationFrame(() => {
      pointerFrame = 0;
      const target = pointerEvent.target instanceof Element ? pointerEvent.target.closest(".panel") : null;
      if (litPanel && litPanel !== target) litPanel.classList.remove("lit");
      litPanel = target;
      if (target && !calm()) {
        const rect = target.getBoundingClientRect();
        target.style.setProperty("--mx", `${Math.round(pointerEvent.clientX - rect.left)}px`);
        target.style.setProperty("--my", `${Math.round(pointerEvent.clientY - rect.top)}px`);
        target.classList.add("lit");
      }
      magnet(pointerEvent);
    });
  }, { passive: true });

  document.documentElement.addEventListener("mouseleave", () => {
    if (litPanel) litPanel.classList.remove("lit");
    litPanel = null;
    magnet(null);
  });

  document.addEventListener("pointerdown", (event) => {
    if (calm() || !(event.target instanceof Element)) return;
    const host = event.target.closest(".primary-button, .ghost-button");
    if (!host || host.disabled) return;
    const rect = host.getBoundingClientRect();
    const dot = document.createElement("span");
    dot.className = "ripple";
    dot.setAttribute("aria-hidden", "true");
    dot.style.left = `${event.clientX - rect.left}px`;
    dot.style.top = `${event.clientY - rect.top}px`;
    host.appendChild(dot);
    dot.addEventListener("animationend", () => dot.remove(), { once: true });
  });

  /* ---------- Signal visualizer (status panel) ---------- */

  const signal = {
    canvas: null,
    context: null,
    frame: 0,
    running: false,
    started: 0,
    last: 0,
    stage: "prepare",
    progress: 0,
    width: 0,
    height: 0,
    ratio: 1,
    bars: new Float32Array(48),
    particles: []
  };

  function signalReady() {
    if (signal.context) return true;
    signal.canvas = $("signal-canvas");
    signal.context = signal.canvas ? signal.canvas.getContext("2d") : null;
    if (!signal.context) return false;
    new ResizeObserver(signalResize).observe(signal.canvas);
    for (let index = 0; index < 34; index += 1) {
      signal.particles.push({ x: Math.random(), y: Math.random(), speed: 0.08 + Math.random() * 0.22, size: 0.6 + Math.random() * 1.6 });
    }
    return true;
  }

  function signalResize() {
    const rect = signal.canvas.getBoundingClientRect();
    signal.ratio = Math.min(2, window.devicePixelRatio || 1);
    signal.width = rect.width;
    signal.height = rect.height;
    signal.canvas.width = Math.max(1, Math.round(rect.width * signal.ratio));
    signal.canvas.height = Math.max(1, Math.round(rect.height * signal.ratio));
  }

  function signalStart() {
    if (signal.running || calm() || !signalReady()) return;
    readGlow();
    signal.running = true;
    signal.started = performance.now();
    signal.last = signal.started;
    signal.frame = requestAnimationFrame(signalDraw);
  }

  function signalStop() {
    signal.running = false;
    cancelAnimationFrame(signal.frame);
    if (signal.context) signal.context.clearRect(0, 0, signal.canvas.width, signal.canvas.height);
  }

  function signalDraw(now) {
    if (!signal.running) return;
    signal.frame = requestAnimationFrame(signalDraw);
    if (document.hidden || !signal.width || !signal.height) return;
    const ctx = signal.context;
    const w = signal.width;
    const h = signal.height;
    const t = (now - signal.started) / 1000;
    const dt = Math.min(0.05, (now - signal.last) / 1000);
    signal.last = now;
    const energy = { prepare: 0.3, fetch: 0.55, recognize: 1, render: 0.45 }[signal.stage] || 0.4;
    ctx.setTransform(signal.ratio, 0, 0, signal.ratio, 0, 0);
    ctx.clearRect(0, 0, w, h);

    for (let layer = 0; layer < 3; layer += 1) {
      const amplitude = h * (0.07 + 0.11 * energy) * (1 - layer * 0.24);
      const frequency = 1.3 + layer * 0.65;
      const speed = 0.7 + layer * 0.3 + energy * 1.4;
      ctx.beginPath();
      for (let x = 0; x <= w; x += 5) {
        const p = x / w;
        const envelope = Math.sin(Math.PI * p);
        const y = h * 0.66
          + Math.sin(p * Math.PI * 2 * frequency + t * speed + layer * 1.7) * amplitude * envelope
          + Math.sin(p * 11 + t * 2.6) * amplitude * 0.22 * energy * envelope;
        if (x === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      const stroke = ctx.createLinearGradient(0, 0, w, 0);
      stroke.addColorStop(0, rgba(0));
      stroke.addColorStop(0.3, rgba(0.5 - layer * 0.12));
      stroke.addColorStop(0.72, `rgba(56, 225, 255, ${0.42 - layer * 0.1})`);
      stroke.addColorStop(1, "rgba(56, 225, 255, 0)");
      ctx.strokeStyle = stroke;
      ctx.lineWidth = 2 - layer * 0.45;
      ctx.stroke();
    }

    if (signal.stage === "recognize") {
      const count = signal.bars.length;
      const slot = w / count;
      for (let index = 0; index < count; index += 1) {
        const wobble = 0.5 + 0.5 * Math.sin(index * 12.9898 + t * 5.1) * Math.sin(index * 3.7 + t * 2.3);
        const envelope = Math.sin(Math.PI * (index + 0.5) / count);
        signal.bars[index] += (wobble * envelope - signal.bars[index]) * 0.16;
        const barHeight = Math.max(1.5, signal.bars[index] * h * 0.36);
        const fill = ctx.createLinearGradient(0, h - barHeight, 0, h);
        fill.addColorStop(0, rgba(0.38));
        fill.addColorStop(1, rgba(0.02));
        ctx.fillStyle = fill;
        ctx.fillRect(index * slot + slot * 0.22, h - barHeight, slot * 0.56, barHeight);
      }
    } else {
      ctx.fillStyle = rgba(0.7);
      signal.particles.forEach((particle) => {
        particle.x += particle.speed * dt * (0.6 + energy);
        if (particle.x > 1.05) {
          particle.x = -0.05;
          particle.y = Math.random();
        }
        const x = particle.x * w;
        const y = h * (0.2 + particle.y * 0.7);
        ctx.globalAlpha = Math.sin(Math.PI * Math.min(1, Math.max(0, particle.x))) * 0.8;
        ctx.fillRect(x - 14 * particle.speed * 4, y, 14 * particle.speed * 4, particle.size * 0.6);
        ctx.beginPath();
        ctx.arc(x, y + particle.size * 0.3, particle.size, 0, Math.PI * 2);
        ctx.fill();
      });
      ctx.globalAlpha = 1;
    }

    const sweep = (Math.min(100, Math.max(0, signal.progress)) / 100) * w;
    const beam = ctx.createLinearGradient(sweep - 70, 0, sweep, 0);
    beam.addColorStop(0, rgba(0));
    beam.addColorStop(1, rgba(0.16));
    ctx.fillStyle = beam;
    ctx.fillRect(Math.max(0, sweep - 70), 0, Math.min(70, sweep), h);
  }

  /* ---------- Celebration ---------- */

  function burst(x, y) {
    if (calm()) return;
    const canvas = document.createElement("canvas");
    canvas.className = "fx-confetti";
    canvas.setAttribute("aria-hidden", "true");
    const ratio = Math.min(2, window.devicePixelRatio || 1);
    canvas.width = Math.round(window.innerWidth * ratio);
    canvas.height = Math.round(window.innerHeight * ratio);
    document.body.appendChild(canvas);
    const ctx = canvas.getContext("2d");
    if (!ctx) {
      canvas.remove();
      return;
    }
    ctx.scale(ratio, ratio);
    const pieces = Array.from({ length: 96 }, (_, index) => {
      const angle = -Math.PI / 2 + (Math.random() - 0.5) * Math.PI * 1.1;
      const speed = 5 + Math.random() * 9;
      return {
        x,
        y,
        vx: Math.cos(angle) * speed,
        vy: Math.sin(angle) * speed,
        size: 4 + Math.random() * 6,
        rotation: Math.random() * Math.PI * 2,
        spin: (Math.random() - 0.5) * 0.4,
        color: CONFETTI[index % CONFETTI.length],
        round: Math.random() < 0.3
      };
    });
    const started = performance.now();
    let last = started;
    function frame(now) {
      const step = Math.min(32, now - last) / 16.67;
      last = now;
      const age = (now - started) / 1900;
      ctx.clearRect(0, 0, window.innerWidth, window.innerHeight);
      pieces.forEach((piece) => {
        piece.vy += 0.3 * step;
        piece.vx *= 0.986;
        piece.vy *= 0.986;
        piece.x += piece.vx * step;
        piece.y += piece.vy * step;
        piece.rotation += piece.spin * step;
        ctx.save();
        ctx.globalAlpha = Math.max(0, 1 - age);
        ctx.translate(piece.x, piece.y);
        ctx.rotate(piece.rotation);
        ctx.fillStyle = piece.color;
        if (piece.round) {
          ctx.beginPath();
          ctx.arc(0, 0, piece.size / 2.4, 0, Math.PI * 2);
          ctx.fill();
        } else {
          ctx.fillRect(-piece.size / 2, -piece.size / 4, piece.size, piece.size / 2);
        }
        ctx.restore();
      });
      if (age < 1) requestAnimationFrame(frame);
      else canvas.remove();
    }
    requestAnimationFrame(frame);
  }

  function celebrate(detail) {
    const title = $("result-title");
    const rect = title && title.getClientRects().length ? title.getBoundingClientRect() : null;
    const x = rect ? Math.min(window.innerWidth - 40, rect.left + Math.min(rect.width, 240) / 2) : window.innerWidth / 2;
    const y = rect ? rect.bottom : window.innerHeight / 3;
    burst(x, y);
    const list = $("segment-list");
    if (detail.kind === "subtitle" && list && !calm()) {
      Array.from(list.children).slice(0, 36).forEach((item, index) => item.style.setProperty("--i", String(index)));
      list.classList.add("reveal");
      setTimeout(() => list.classList.remove("reveal"), 2200);
    }
  }

  /* ---------- Subtitle timeline strip ---------- */

  const timeline = { host: null, canvas: null, tip: null, list: null, segments: [], needle: "", duration: 0 };

  function timelineSetup(host) {
    if (timeline.canvas && timeline.host === host) return;
    timeline.host = host;
    timeline.canvas = document.createElement("canvas");
    timeline.tip = document.createElement("span");
    timeline.tip.className = "timeline-tip";
    timeline.tip.hidden = true;
    host.append(timeline.canvas, timeline.tip);
    new ResizeObserver(drawTimeline).observe(host);
    host.addEventListener("pointermove", (event) => {
      if (!timeline.duration) return;
      const rect = host.getBoundingClientRect();
      const ratio = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width));
      timeline.tip.textContent = formatTime(ratio * timeline.duration);
      timeline.tip.style.left = `${Math.min(94, Math.max(6, ratio * 100))}%`;
      timeline.tip.hidden = false;
    });
    host.addEventListener("pointerleave", () => { timeline.tip.hidden = true; });
    host.addEventListener("click", (event) => {
      if (!timeline.duration || !timeline.list) return;
      const rect = host.getBoundingClientRect();
      const time = ((event.clientX - rect.left) / rect.width) * timeline.duration;
      let best = 0;
      timeline.segments.forEach((segment, index) => {
        if (segment.start <= time) best = index;
      });
      const item = timeline.list.children[best];
      if (!item) return;
      item.scrollIntoView({ block: "center", behavior: calm() ? "auto" : "smooth" });
      item.classList.remove("flash");
      void item.offsetWidth;
      item.classList.add("flash");
    });
  }

  function drawTimeline() {
    const { host, canvas, segments } = timeline;
    if (!host || !canvas) return;
    const rect = host.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    const ratio = Math.min(2, window.devicePixelRatio || 1);
    canvas.width = Math.round(rect.width * ratio);
    canvas.height = Math.round(rect.height * ratio);
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, rect.width, rect.height);
    const duration = segments.reduce((longest, segment) => Math.max(longest, segment.end || segment.start), 0);
    timeline.duration = duration;
    if (!duration) return;
    const bins = Math.max(24, Math.floor(rect.width / 4));
    const density = new Float32Array(bins);
    const hits = new Uint8Array(bins);
    segments.forEach((segment) => {
      const first = Math.min(bins - 1, Math.floor((segment.start / duration) * bins));
      const last = Math.min(bins - 1, Math.max(first, Math.floor(((segment.end || segment.start) / duration) * bins)));
      const share = segment.text.length / (last - first + 1);
      const hit = timeline.needle && segment.text.toLocaleLowerCase().includes(timeline.needle);
      for (let index = first; index <= last; index += 1) {
        density[index] += share;
        if (hit) hits[index] = 1;
      }
    });
    const peak = Math.max(1, ...density);
    const slot = rect.width / bins;
    readGlow();
    for (let index = 0; index < bins; index += 1) {
      if (!density[index]) continue;
      const level = Math.sqrt(density[index] / peak);
      const barHeight = Math.max(2, level * (rect.height - 10));
      ctx.fillStyle = hits[index] ? "rgba(255, 196, 0, 0.95)" : rgba(0.3 + level * 0.6);
      ctx.fillRect(index * slot + slot * 0.18, rect.height - 5 - barHeight, Math.max(1, slot * 0.64), barHeight);
    }
  }

  /* ---------- Command palette ---------- */

  const ICONS = {
    plus: '<path d="M12 5v14M5 12h14"/>',
    clip: '<rect width="8" height="4" x="8" y="2" rx="1"/><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/>',
    play: '<path d="M6 4.5v15l13-7.5-13-7.5Z"/>',
    clock: '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5M12 7v5l3 2"/>',
    copy: '<rect width="13" height="13" x="9" y="9" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
    download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5M12 15V3"/>',
    file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z"/><path d="M14 2v6h6"/>',
    list: '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
    code: '<path d="m16 18 6-6-6-6M8 6l-6 6 6 6"/>',
    moon: '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>',
    shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z"/><path d="m9 12 2 2 4-4"/>',
    exit: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="m16 17 5-5-5-5M21 12H9"/>'
  };

  function enabled(id) {
    const element = $(id);
    return Boolean(element && !element.disabled);
  }

  function click(id) {
    const element = $(id);
    if (element && !element.disabled) element.click();
  }

  function resultReady() {
    return visible("output-shell");
  }

  function setFormat(format) {
    const select = $("result-format");
    if (!select || select.disabled) return;
    select.value = format;
    select.dispatchEvent(new Event("change", { bubbles: true }));
  }

  const ACTIONS = [
    { label: "新建任务", hint: "清空输入，从头开始", keys: "new xinjian renwu", icon: "plus", run: () => click("new-task"),
      when: () => enabled("new-task") },
    { label: "粘贴链接", hint: "从剪贴板读取视频链接", keys: "paste zhantie lianjie", icon: "clip", run: () => click("paste-input"),
      when: () => visible("paste-input") },
    { label: "开始提取", hint: "提交当前任务", keys: "start run go kaishi tiqu", icon: "play", run: () => click("extract-button"),
      when: () => enabled("extract-button") },
    { label: "最近记录", hint: "最近 24 小时的任务", keys: "history recent jilu lishi", icon: "clock",
      run: () => click("open-history"), when: () => Boolean($("open-history") && !$("open-history").hidden) },
    { label: "复制全部字幕", hint: "复制当前结果", keys: "copy fuzhi", icon: "copy", run: () => click("copy-result"),
      when: () => visible("copy-result") },
    { label: "下载结果", hint: "保存为当前格式", keys: "download save xiazai", icon: "download",
      run: () => click("download-result"), when: () => visible("download-result") },
    ...[["srt", "SRT 字幕"], ["vtt", "WebVTT"], ["txt", "纯文本"], ["markdown", "Markdown"], ["json", "JSON"]].map(
      ([format, name]) => ({
        label: `导出格式：${name}`,
        hint: "切换后可直接下载",
        keys: `format geshi ${format}`,
        icon: "file",
        run: () => setFormat(format),
        when: resultReady
      })
    ),
    { label: "逐句视图", hint: "带时间轴阅读", keys: "segments zhuju view", icon: "list", run: () => click("view-segments"),
      when: resultReady },
    { label: "文件视图", hint: "按导出格式预览", keys: "source file wenjian view", icon: "code", run: () => click("view-source"),
      when: resultReady },
    { label: "切换外观", hint: "跟随系统 · 浅色 · 深色", keys: "theme dark light waiguan zhuti", icon: "moon",
      run: () => click("theme-toggle"), when: () => enabled("theme-toggle") },
    { label: "返回工作台", hint: "回到字幕提取", keys: "home workspace gongzuotai back", icon: "play",
      run: () => window.location.assign("/"), when: () => !$("extract-button") },
    { label: "站长控制台", hint: "激活码 · B站账号 · 门卫日志", keys: "admin owner kongzhitai guanli",
      icon: "shield", run: () => window.location.assign("/admin"),
      when: () => document.body.classList.contains("is-owner") && Boolean($("extract-button")) },
    { label: "退出当前设备", hint: "之后需要重新输入激活码", keys: "logout exit tuichu", icon: "exit",
      run: () => click("logout-account"), when: () => enabled("logout-account") }
  ];

  const palette = { root: null, input: null, list: null, items: [], selected: 0, returnFocus: null };

  function paletteBuild() {
    if (palette.root) return;
    const root = document.createElement("div");
    root.className = "palette-backdrop";
    root.hidden = true;
    root.innerHTML = `
      <div class="palette" role="dialog" aria-modal="true" aria-label="命令面板">
        <div class="palette-search">
          <svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"></circle><path d="m20 20-3.5-3.5"></path></svg>
          <input type="text" autocomplete="off" spellcheck="false" placeholder="输入命令，例如 新任务、SRT、深色" aria-label="搜索命令" aria-controls="palette-list">
          <kbd>Esc</kbd>
        </div>
        <ul class="palette-list" id="palette-list" role="listbox" aria-label="命令"></ul>
        <footer><span>↑↓ 选择</span><span>↵ 执行</span><span>Esc 关闭</span></footer>
      </div>`;
    document.body.appendChild(root);
    palette.root = root;
    palette.input = root.querySelector("input");
    palette.list = root.querySelector(".palette-list");
    palette.input.addEventListener("input", () => paletteRender(true));
    palette.input.addEventListener("keydown", paletteKeys);
    root.addEventListener("click", (event) => {
      if (event.target === root) paletteClose();
    });
    palette.list.addEventListener("pointermove", (event) => {
      const item = event.target instanceof Element ? event.target.closest("li[data-index]") : null;
      if (item && Number(item.dataset.index) !== palette.selected) {
        palette.selected = Number(item.dataset.index);
        paletteHighlight();
      }
    });
    palette.list.addEventListener("click", (event) => {
      const item = event.target instanceof Element ? event.target.closest("li[data-index]") : null;
      if (item) paletteRun(Number(item.dataset.index));
    });
  }

  function paletteRender(resetSelection) {
    const query = palette.input.value.trim().toLocaleLowerCase();
    palette.items = ACTIONS.filter((action) => (!action.when || action.when())
      && (!query || `${action.label} ${action.hint} ${action.keys}`.toLocaleLowerCase().includes(query)));
    if (resetSelection) palette.selected = 0;
    palette.list.textContent = "";
    if (!palette.items.length) {
      const empty = document.createElement("li");
      empty.className = "palette-empty";
      empty.textContent = "没有匹配的命令";
      palette.list.appendChild(empty);
      return;
    }
    palette.items.forEach((action, index) => {
      const item = document.createElement("li");
      item.id = `palette-option-${index}`;
      item.setAttribute("role", "option");
      item.dataset.index = String(index);
      const icon = document.createElement("span");
      icon.className = "palette-icon";
      icon.innerHTML = `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">${ICONS[action.icon] || ""}</svg>`;
      const text = document.createElement("span");
      const label = document.createElement("strong");
      label.textContent = action.label;
      const hint = document.createElement("small");
      hint.textContent = action.hint;
      text.append(label, hint);
      item.append(icon, text);
      palette.list.appendChild(item);
    });
    paletteHighlight();
  }

  function paletteHighlight() {
    palette.list.querySelectorAll("li[data-index]").forEach((item) => {
      const active = Number(item.dataset.index) === palette.selected;
      item.setAttribute("aria-selected", String(active));
      if (active) {
        palette.input.setAttribute("aria-activedescendant", item.id);
        item.scrollIntoView({ block: "nearest" });
      }
    });
  }

  function paletteKeys(event) {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (!palette.items.length) return;
      const step = event.key === "ArrowDown" ? 1 : -1;
      palette.selected = (palette.selected + step + palette.items.length) % palette.items.length;
      paletteHighlight();
    } else if (event.key === "Enter") {
      event.preventDefault();
      if (!event.isComposing) paletteRun(palette.selected);
    } else if (event.key === "Escape") {
      event.preventDefault();
      paletteClose();
    } else if (event.key === "Tab") {
      event.preventDefault();
    }
  }

  function paletteOpen() {
    paletteBuild();
    if (!palette.root.hidden) return;
    palette.returnFocus = document.activeElement;
    palette.input.value = "";
    paletteRender(true);
    palette.root.hidden = false;
    document.body.classList.add("dialog-open");
    requestAnimationFrame(() => palette.input.focus());
  }

  function paletteClose() {
    if (!palette.root || palette.root.hidden) return;
    palette.root.hidden = true;
    document.body.classList.remove("dialog-open");
    const target = palette.returnFocus;
    palette.returnFocus = null;
    if (target && target.isConnected && typeof target.focus === "function") target.focus();
  }

  function paletteRun(index) {
    const action = palette.items[index];
    if (!action) return;
    paletteClose();
    requestAnimationFrame(() => action.run());
  }

  document.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && !event.altKey && event.key.toLowerCase() === "k") {
      event.preventDefault();
      if (palette.root && !palette.root.hidden) paletteClose();
      else paletteOpen();
    }
  });

  /* ---------- Theme reveal ---------- */

  function themeTransition(apply, origin) {
    if (calm() || typeof document.startViewTransition !== "function") {
      apply();
      return;
    }
    const rect = origin ? origin.getBoundingClientRect() : null;
    const x = rect ? rect.left + rect.width / 2 : window.innerWidth / 2;
    const y = rect ? rect.top + rect.height / 2 : 0;
    const radius = Math.hypot(Math.max(x, window.innerWidth - x), Math.max(y, window.innerHeight - y));
    const transition = document.startViewTransition(apply);
    transition.ready.then(() => {
      document.documentElement.animate(
        { clipPath: [`circle(0px at ${x}px ${y}px)`, `circle(${radius}px at ${x}px ${y}px)`] },
        { duration: 640, easing: "cubic-bezier(0.2, 0.8, 0.2, 1)", pseudoElement: "::view-transition-new(root)" }
      );
    }).catch(() => {});
  }

  /* ---------- Workspace events ---------- */

  document.addEventListener("workspace:busy", (event) => {
    const busy = Boolean(event.detail.busy);
    document.body.classList.toggle("is-busy", busy);
    if (busy) signalStart();
    else signalStop();
  });

  document.addEventListener("workspace:stage", (event) => {
    signal.stage = event.detail.stage || "prepare";
    signal.progress = Number(event.detail.progress) || 0;
    if (document.body.classList.contains("is-busy")) signalStart();
  });

  document.addEventListener("workspace:complete", (event) => {
    signalStop();
    requestAnimationFrame(() => celebrate(event.detail || {}));
  });

  document.addEventListener("workspace:failed", () => {
    signalStop();
    const panel = $("status-panel");
    if (!panel || calm()) return;
    panel.classList.remove("fx-shake");
    void panel.offsetWidth;
    panel.classList.add("fx-shake");
  });

  document.addEventListener("workspace:segments", (event) => {
    const detail = event.detail || {};
    if (!detail.timeline) return;
    timelineSetup(detail.timeline);
    timeline.list = detail.list;
    timeline.segments = Array.isArray(detail.segments) ? detail.segments : [];
    timeline.needle = detail.needle || "";
    requestAnimationFrame(drawTimeline);
  });

  document.addEventListener("workspace:platform", () => {
    requestAnimationFrame(() => {
      readGlow();
      drawTimeline();
    });
  });

  const commandButton = $("open-command");
  if (commandButton) commandButton.addEventListener("click", paletteOpen);
  const commandKey = $("command-key");
  const platform = (navigator.userAgentData && navigator.userAgentData.platform) || navigator.platform || "";
  if (commandKey && !/mac|iphone|ipad/i.test(platform)) commandKey.textContent = "Ctrl K";

  function paletteRegister(actions) {
    (Array.isArray(actions) ? actions : []).forEach((action) => {
      if (action && action.label && typeof action.run === "function") ACTIONS.push(action);
    });
  }

  window.FX = { themeTransition, burst, palette: { open: paletteOpen, close: paletteClose, register: paletteRegister } };
})();
