const { test, before, after } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const path = require("node:path");
const http = require("node:http");
const { chromium, webkit } = require("playwright");

let browser, server, base;
const staticRoot = path.join(__dirname, "../app/static");
const captureRoot = process.env.UI_SCREENSHOT_DIR;
const config = {
  features: { local_processing: true, cloud_enhancement: true, uploads: true,
    media: true, embedded_subtitles: true, bilibili_login: true },
  platforms: { bilibili: true, douyin: true, upload: true },
  asr_modes: { auto: { available: true, processing: "local" } },
  uploads: { enabled: true, max_bytes: 536870912, allowed_extensions: [".mp4", ".mkv"] },
  media: { enabled: true }
};

before(async () => {
  const files = { "/": "index.html", "/static/app.css": "app.css", "/static/app.js": "app.js",
    "/static/theme.js": "theme.js", "/static/favicon.svg": "favicon.svg", "/static/fx.css": "fx.css",
    "/static/fx.js": "fx.js", "/login": "gate.html", "/static/gate.css": "gate.css", "/static/gate.js": "gate.js" };
  server = http.createServer(async (req, res) => {
    const name = files[new URL(req.url, "http://localhost").pathname];
    if (!name) { res.writeHead(404); res.end(); return; }
    const data = await fs.readFile(path.join(staticRoot, name));
    res.setHeader("Content-Type", name.endsWith(".css") ? "text/css" : name.endsWith(".js") ? "text/javascript"
      : name.endsWith(".svg") ? "image/svg+xml" : "text/html");
    res.end(data);
  });
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  base = `http://127.0.0.1:${server.address().port}`;
  browser = await (process.env.UI_BROWSER === "webkit" ? webkit : chromium).launch();
  if (captureRoot) await fs.mkdir(captureRoot, { recursive: true });
});

after(async () => {
  if (browser) await browser.close();
  if (server) await new Promise(resolve => server.close(resolve));
});

async function workspace(t, options = {}) {
  const context = await browser.newContext({ viewport: options.viewport || { width: 1440, height: 900 }, reducedMotion: "reduce" });
  context.setDefaultTimeout(7000);
  t.after(() => context.close());
  const page = await context.newPage();
  const errors = [], submissions = [];
  page.on("pageerror", error => errors.push(error.message));
  t.after(() => assert.deepEqual(errors.filter(error => !(options.ignoreErrors && options.ignoreErrors.test(error))), []));
  await page.route("**/api/**", async route => {
    const req = route.request();
    const endpoint = new URL(req.url()).pathname;
    if (options.route && await options.route(route, endpoint)) return;
    let status = 200, body = {};
    if (endpoint === "/api/auth/me") {
      body = { user: Object.assign({ id: 7, username: "preview", label: "preview", created_at: 1700000000 }, options.me || {}) };
    } else if (endpoint === "/api/health") body = { status: "ok" };
    else if (endpoint.endsWith("config")) body = options.config || config;
    else if (endpoint === "/api/jobs" && req.method() === "GET") body = {
      jobs: options.history || [], retention_seconds: 86400
    };
    else if (endpoint === "/api/bilibili/pages") body = {
      base_url: "https://www.bilibili.com/video/BV14jFvzbEvj", current_page: 1,
      pages: [{ page: 1, title: "Introduction" }, { page: 2, title: "Part two" }]
    };
    else if (req.method() === "DELETE" && endpoint.startsWith("/api/jobs/")) body = { id: "fixture-job", status: "cancelled" };
    else if (req.method() === "POST") {
      const payload = req.postDataJSON();
      submissions.push({ endpoint, payload, idempotencyKey: req.headers()["idempotency-key"] });
      if (options.failure) { status = 503; body = { detail: { reason: "download_failed" } }; }
      else if (options.waiting) body = { id: "fixture-job", status: "queued", progress: 3, queue_position: 2 };
      else if (options.running) body = { id: "fixture-job", status: "running", stage: "media_convert", progress: 58, message: "正在转换" };
      else body = { id: "fixture-job", status: "completed", expires_at: Date.now() / 1000 + 86400, result: {
        content: "第一段测试字幕。\n第二段介绍缓存与任务恢复。\n字幕结果保留原始语义。", raw_content: "原始识别结果。",
        format: "txt", filename: "fixture.txt",
        metadata: { title: "字幕工作台测试视频", platform: "bilibili", source: "asr_local", entry_count: 3,
          duration: 62, elapsed_seconds: 8.2, cache_hit: true }
      } };
    } else if (endpoint.startsWith("/api/jobs/")) {
      status = options.expired ? 410 : 200;
      body = options.expired ? { detail: { reason: "job_expired" } }
        : { id: "fixture-job", status: "running", stage: "media_convert", progress: 58, message: "正在转换" };
    } else { status = 404; }
    await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
  });
  if (options.expired) await page.addInitScript(() => {
    localStorage.setItem("caption-active-job-v1:7", JSON.stringify({ jobId: "old-job", savedAt: Date.now(),
      startedAt: Date.now(), payload: { kind: "media", media_type: "video", input: "BV14jFvzbEvj" } }));
  });
  if (options.beforeLoad) await options.beforeLoad(page);
  await page.goto(base);
  await page.locator("body.app-ready").waitFor();
  return { page, submissions };
}

async function screenshot(page, name) {
  if (captureRoot) await page.screenshot({ path: path.join(captureRoot, `${name}.png`), fullPage: true, animations: "disabled" });
}

function savedSubtitle(id = "saved-job") {
  const created = Math.floor(Date.now() / 1000) - 600;
  return { id, kind: "subtitle", status: "completed", stage: "completed", progress: 100,
    created_at: created, updated_at: created, expires_at: created + 86400,
    title: "城市漫步：用光影记录普通的一天", platform: "bilibili",
    result: { content: "傍晚的街道渐渐安静下来。\n我们沿着河边，记录这座城市的日常。",
      raw_content: "傍晚的街道渐渐安静下来。", filename: "城市漫步.txt", format: "txt",
      metadata: { title: "城市漫步：用光影记录普通的一天", platform: "bilibili",
        source: "official_no_cookie", entry_count: 2, duration: 86, elapsed_seconds: 1.2 } }
  };
}

for (const width of [1440, 390, 320]) {
  test(`saved results open without new extraction at ${width}px`, async t => {
    const job = savedSubtitle();
    const { result, ...summary } = job;
    const { page, submissions } = await workspace(t, { viewport: { width, height: 900 }, history: [summary],
      route: async (route, endpoint) => {
        if (endpoint !== "/api/jobs/saved-job") return false;
        await route.fulfill({ contentType: "application/json", body: JSON.stringify(job) });
        return true;
      }
    });
    const selector = "#history-list";
    await page.locator("#open-history").click();
    await screenshot(page, `history-${width}`);
    const box = await page.locator(".history-drawer").boundingBox();
    assert.ok(box.x >= 0 && box.x + box.width <= width);
    await page.locator(`${selector} .recent-item`).click();
    await page.locator("#output-shell").waitFor({ state: "visible" });
    assert.equal(await page.locator("#history-drawer").isVisible(), false);
    assert.match(await page.locator("#output").textContent(), /傍晚/);
    assert.match(await page.locator("#result-expiry").textContent(), /字幕结果保留至/);
    assert.equal(await page.locator("#retry-accurate").isVisible(), false);
    assert.equal(submissions.length, 0);
    const bounds = await page.evaluate(() => ({ width: innerWidth, scroll: document.documentElement.scrollWidth,
      controls: ["open-history", "health-trigger", "account-trigger"].map(id => {
        const r = document.getElementById(id).getBoundingClientRect();
        return { left: r.left, right: r.right, width: r.width };
      }) }));
    assert.equal(bounds.scroll <= width, true);
    for (const box of bounds.controls) if (box.width) assert.ok(box.left >= 0 && box.right <= width);
    const visibleControls = bounds.controls.filter(box => box.width).sort((a, b) => a.left - b.left);
    for (let i = 1; i < visibleControls.length; i += 1) assert.ok(visibleControls[i].left >= visibleControls[i - 1].right);
    if (width <= 1180) {
      assert.ok(await page.locator("#open-history").evaluate(el => {
        const range = document.createRange();
        range.selectNodeContents(el);
        return range.getBoundingClientRect().height;
      }) < 30);
    }
    await screenshot(page, `saved-result-${width}`);
    await page.reload();
    await page.locator("body.app-ready").waitFor();
    await page.locator("#open-history").click();
    await page.locator(`${selector} .recent-item`).waitFor();
    assert.equal(submissions.length, 0);
  });
}

test("an expired history entry does not replace an already opened result", async t => {
  const job = savedSubtitle();
  const { result, ...summary } = job;
  const { page, submissions } = await workspace(t, { history: [summary, { ...summary, id: "gone", title: "过期项" }],
    route: async (route, endpoint) => {
      if (endpoint === "/api/jobs/saved-job") {
        await route.fulfill({ contentType: "application/json", body: JSON.stringify(job) }); return true;
      }
      if (endpoint === "/api/jobs/gone") {
        await route.fulfill({ status: 410, contentType: "application/json", body: "{}" }); return true;
      }
      return false;
    }
  });
  await page.locator("#open-history").click();
  await page.locator("#history-list .recent-item").first().click();
  await page.locator("#output-shell").waitFor({ state: "visible" });
  await page.locator("#open-history").click();
  await page.getByRole("button", { name: /过期项/ }).click();
  await page.waitForFunction(() => document.querySelector("#toast").textContent.includes("过期"));
  assert.match(await page.locator("#output").textContent(), /傍晚/);
  assert.equal(submissions.length, 0);
});

test("an open subtitle and its history expire without keeping text in local storage", async t => {
  const job = savedSubtitle();
  const { result, ...summary } = job;
  const { page, submissions } = await workspace(t, { history: [summary],
    beforeLoad: async page => { await page.clock.install({ time: new Date() }); },
    route: async (route, endpoint) => {
      if (endpoint !== "/api/jobs/saved-job") return false;
      await route.fulfill({ contentType: "application/json", body: JSON.stringify(job) }); return true;
    }
  });
  await page.locator("#open-history").click();
  await page.locator("#history-list .recent-item").click();
  await page.locator("#output-shell").waitFor({ state: "visible" });
  await page.clock.fastForward(86400 * 1000);
  assert.equal(await page.locator("#output").textContent(), "");
  assert.equal(await page.locator("#status-title").textContent(), "结果已过期");
  assert.equal(await page.locator("#history-list .recent-item").count(), 0);
  assert.equal(await page.evaluate(() => JSON.stringify(localStorage).includes("傍晚")), false);
  assert.equal(submissions.length, 0);
});

test("history failure can be retried without creating tasks", async t => {
  let reads = 0;
  const { result, ...summary } = savedSubtitle();
  const { page, submissions } = await workspace(t, { route: async (route, endpoint) => {
    if (endpoint !== "/api/jobs" || route.request().method() !== "GET") return false;
    reads += 1;
    await route.fulfill({ status: reads === 1 ? 503 : 200, contentType: "application/json",
      body: JSON.stringify(reads === 1 ? {} : { jobs: [summary], retention_seconds: 86400 }) });
    return true;
  } });
  await page.waitForFunction(() => document.querySelector("#history-caption").textContent.includes("重试"));
  await page.locator("#open-history").click();
  await page.locator("#history-list .recent-item").waitFor();
  await page.locator("#refresh-history").click();
  await page.locator("#history-list .recent-item").waitFor();
  assert.equal(submissions.length, 0);
});

for (const action of ["copy", "download", "format"]) {
  test(`expired results reject ${action} before the cleanup timer runs`, async t => {
    const job = savedSubtitle();
    const { result, ...summary } = job;
    let exports = 0;
    const { page } = await workspace(t, { history: [summary], beforeLoad: page => page.clock.install(),
      route: async (route, endpoint) => {
        if (endpoint.endsWith("/result")) exports += 1;
        if (endpoint !== "/api/jobs/saved-job") return false;
        await route.fulfill({ json: job }); return true;
      }
    });
    await page.locator("#open-history").click();
    await page.locator("#history-list .recent-item").click();
    await page.locator("#output-shell").waitFor({ state: "visible" });
    await page.clock.setSystemTime(new Date((job.expires_at + 1) * 1000));
    if (action === "format") await page.locator("#result-format").selectOption("srt");
    else await page.locator(`#${action}-result`).click();
    assert.equal(await page.locator("#output").textContent(), "");
    assert.equal(await page.locator("#result-actions").isVisible(), false);
    assert.equal(exports, 0);
  });
}

test("a new task clears the previous result's expiry and selection", async t => {
  const { page } = await workspace(t);
  await page.locator("#video-input").fill("BV14jFvzbEvj");
  await page.locator("#extract-button").click();
  await page.locator("#result-expiry").waitFor({ state: "visible" });
  await page.locator("#new-task").click();
  assert.equal(await page.locator("#result-expiry").isVisible(), false);
  assert.equal(await page.locator("#output").textContent(), "");
  assert.equal(await page.locator('#history-list [aria-current="true"]').count(), 0);
});

for (const width of [1440, 1280, 1024, 820, 390, 320]) {
  test(`workspace fits ${width}px and sources remain a two-column control`, async t => {
    const { page } = await workspace(t, { viewport: { width, height: 900 } });
    assert.equal(await page.locator("#cloud-mode-zone").getAttribute("open"), null);
    const layout = await page.evaluate(() => ({
      overflow: document.documentElement.scrollWidth > innerWidth,
      sourceRows: [...document.querySelectorAll(".source-choice")].map(e => e.getBoundingClientRect().top),
      inputFont: parseFloat(getComputedStyle(document.querySelector("#video-input")).fontSize)
    }));
    assert.equal(layout.overflow, false);
    assert.equal(layout.sourceRows[0], layout.sourceRows[1]);
    if (width <= 560) assert.ok(layout.inputFont >= 16);
    await screenshot(page, `workspace-${width}`);
    await page.locator('input[name="input-mode"][value="upload"]').locator("..").click();
    await page.locator("#upload-input-panel").waitFor({ state: "visible" });
    await page.locator("#video-file").setInputFiles({ name: "test-file.mp4", mimeType: "video/mp4", buffer: Buffer.from("fixture") });
    assert.equal(await page.locator("#upload-file-title").textContent(), "test-file.mp4");
    assert.match(await page.locator("#quality-caption").textContent(), /音轨/);
    await screenshot(page, `upload-${width}`);
  });
}

test("media operations have their own empty state and no server metrics", async t => {
  const { page } = await workspace(t);
  await page.locator('input[name="operation"][value="video"]').locator("..").click();
  assert.equal(await page.locator("#idle-title").textContent(), "尚无视频");
  await page.locator('input[name="operation"][value="audio"]').locator("..").click();
  assert.equal(await page.locator("#idle-format").textContent(), "MP3");
  assert.equal(await page.locator("#idle-title").textContent(), "尚无音频");
  assert.equal(await page.locator("#input-mode-group").isVisible(), false);
  assert.equal(await page.locator("#cloud-mode-zone").isVisible(), false);
  await page.locator("#health-trigger").click();
  assert.doesNotMatch(await page.locator("#health-popover").textContent(), /RSS|CPU|内存|磁盘|\/opt\//);
  await screenshot(page, "media-audio");
});

test("cloud selection stays explicit, traps focus and never submits before consent", async t => {
  const { page, submissions } = await workspace(t);
  await page.locator("#video-input").fill("BV14jFvzbEvj");
  await page.locator("#cloud-mode-zone summary").click();
  await page.locator('input[name="asr-mode"][value="economy"]').locator("..").click();
  assert.match(await page.locator("#cloud-selection-label").textContent(), /Paraformer/);
  await page.locator("#extract-button").click();
  await page.locator("#cloud-confirm-dialog").waitFor({ state: "visible" });
  await page.waitForFunction(() => document.activeElement === document.querySelector("#cloud-confirm-check"));
  assert.equal(submissions.length, 0);
  assert.equal(await page.locator("#submit-cloud-confirm").isDisabled(), true);
  await page.locator("#cancel-cloud-confirm").focus();
  await page.keyboard.press("Tab");
  assert.equal(await page.locator("#close-cloud-confirm").evaluate(e => e === document.activeElement), true);
  await screenshot(page, "cloud-consent");
  await page.keyboard.press("Escape");
  assert.equal(await page.locator("#extract-button").evaluate(e => e === document.activeElement), true);
  await page.locator("#extract-button").click();
  await page.locator("#cloud-confirm-check").check();
  await page.locator("#submit-cloud-confirm").click();
  await page.locator("#output-shell").waitFor({ state: "visible" });
  assert.equal(submissions.length, 1);
  assert.equal(submissions[0].payload.cloud_consent, true);
});

test("official-only selection removes irrelevant cloud controls", async t => {
  const { page } = await workspace(t);
  await page.locator("#cloud-mode-zone summary").click();
  await page.locator('input[name="asr-mode"][value="high_accuracy"]').locator("..").click();
  await page.locator('input[name="source"][value="official"]').locator("..").click();
  assert.equal(await page.locator("#quality-field-group").isVisible(), false);
  assert.equal(await page.locator('input[name="asr-mode"][value="auto"]').isChecked(), true);
});

test("capability refresh preserves the user's collapsed cloud panel", async t => {
  const { page } = await workspace(t);
  await page.locator("#cloud-mode-zone summary").click();
  await page.locator('input[name="asr-mode"][value="economy"]').locator("..").click();
  await page.locator("#cloud-mode-zone summary").click();
  await page.locator('input[name="source"][value="auto"]').dispatchEvent("change");
  assert.equal(await page.locator("#cloud-mode-zone").getAttribute("open"), null);
});

test("completed result is readable and new task clears the old output", async t => {
  const { page } = await workspace(t);
  await page.locator("#video-input").fill("BV14jFvzbEvj");
  await page.locator("#extract-button").click();
  await page.locator("#output-shell").waitFor({ state: "visible" });
  await page.locator("#result-search").fill("字幕");
  await page.waitForFunction(() => document.querySelector("#search-count").textContent === "2 处");
  assert.match(await page.locator("#search-count").textContent(), /2 处/);
  await screenshot(page, "completed-desktop");
  await page.locator("#new-task").click();
  assert.equal(await page.locator("#output-shell").isVisible(), false);
  assert.equal(await page.locator("#output").textContent(), "");
  assert.equal(await page.locator("#idle-title").textContent(), "尚无字幕");
});

test("result formats convert without a second submission, including the raw version", async t => {
  const formats = [];
  const { page, submissions } = await workspace(t, { route: async (route, endpoint) => {
    if (!endpoint.endsWith("/result")) return false;
    const format = new URL(route.request().url()).searchParams.get("format");
    formats.push(format);
    await route.fulfill({ json: { format, filename: `fixture.${format}`, content_type: "text/plain",
      content: "1\n00:00:00,000 --> 00:00:01,000\n整理字幕", raw_content: "原始字幕" } });
    return true;
  } });
  await page.locator("#video-input").fill("BV14jFvzbEvj");
  await page.locator("#extract-button").click();
  await page.locator("#output-shell").waitFor({ state: "visible" });
  await page.locator("#advanced-options > summary").click();
  await page.locator("#format-select").selectOption("json");
  assert.equal(submissions.length, 1);
  await page.locator("#result-format").selectOption("srt");
  await page.waitForFunction(() => document.querySelector("#output").textContent.includes("00:00:01,000"));
  await page.locator("#toggle-raw").click();
  assert.equal(await page.locator("#output").textContent(), "原始字幕");
  assert.equal(submissions.length, 1);
  assert.deepEqual(formats, ["srt"]);
  await screenshot(page, "result-format-desktop");
  await page.setViewportSize({ width: 320, height: 844 });
  await page.locator("#mobile-tab-result").click();
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  const tools = await page.locator(".output-tools").evaluate(element => {
    const parent = element.getBoundingClientRect();
    return [...element.children].filter(child => !child.hidden).map(child => {
      const rect = child.getBoundingClientRect();
      return { inside: rect.left >= parent.left && rect.right <= parent.right + 1, height: rect.height };
    });
  });
  assert.ok(tools.every(tool => tool.inside && tool.height <= 35));
  await screenshot(page, "result-format-mobile");
});

test("expired export retains the existing result and never resubmits", async t => {
  const { page, submissions } = await workspace(t, { route: async (route, endpoint) => {
    if (!endpoint.endsWith("/result")) return false;
    await route.fulfill({ status: 410, json: { detail: { message: "该结果已过期" } } });
    return true;
  } });
  await page.locator("#video-input").fill("BV14jFvzbEvj");
  await page.locator("#extract-button").click();
  await page.locator("#output-shell").waitFor({ state: "visible" });
  const original = await page.locator("#output").textContent();
  await page.locator("#result-format").selectOption("json");
  await page.waitForFunction(() => document.querySelector("#result-format").value === "txt");
  assert.equal(await page.locator("#output").textContent(), original);
  assert.equal(await page.locator("#download-result").isEnabled(), true);
  assert.equal(submissions.length, 1);
});

test("temporary polling failure keeps the job and recovers without another POST", async t => {
  let polls = 0;
  const { page, submissions } = await workspace(t, { waiting: true, route: async (route, endpoint) => {
    if (!endpoint.startsWith("/api/jobs/") || route.request().method() !== "GET") return false;
    polls += 1;
    await route.fulfill(polls === 1 ? { status: 503, body: "temporarily unavailable" }
      : { json: { id: "fixture-job", status: "completed", result: { content: "恢复成功", format: "txt" } } });
    return true;
  } });
  await page.locator("#video-input").fill("BV14jFvzbEvj");
  await page.locator("#extract-button").click();
  await page.waitForFunction(() => document.querySelector("#status-title").textContent === "连接暂时中断");
  assert.equal(await page.evaluate(() => JSON.parse(localStorage.getItem("caption-active-job-v1:7")).jobId), "fixture-job");
  assert.equal(await page.locator("#extract-button").isDisabled(), true);
  await screenshot(page, "reconnecting-desktop");
  await page.locator("#output-shell").waitFor({ state: "visible" });
  assert.equal(await page.locator("#output").textContent(), "恢复成功");
  assert.equal(submissions.length, 1);
  assert.equal(polls, 2);
  assert.equal(await page.evaluate(() => localStorage.getItem("caption-active-job-v1:7")), null);
});

test("refresh restores a running job without creating a new one", async t => {
  const { page, submissions } = await workspace(t, { waiting: true });
  await page.locator("#video-input").fill("BV14jFvzbEvj");
  await page.locator("#extract-button").click();
  await page.waitForFunction(() => localStorage.getItem("caption-active-job-v1:7"));
  await page.reload();
  await page.locator("body.app-ready").waitFor();
  await page.waitForFunction(() => document.querySelector("#progress-track").getAttribute("aria-valuenow") === "58");
  assert.equal(submissions.length, 1);
  assert.equal(await page.locator("#video-input").inputValue(), "BV14jFvzbEvj");
  assert.equal(await page.locator("#extract-button").isDisabled(), true);
});

test("an uncertain submission keeps its idempotency key for a manual retry", async t => {
  const keys = [];
  const { page } = await workspace(t, { route: async (route, endpoint) => {
    if (endpoint !== "/api/jobs" || route.request().method() !== "POST") return false;
    keys.push(route.request().headers()["idempotency-key"]);
    if (keys.length !== 1) return false;
    await route.fulfill({ status: 502, body: "gateway error" });
    return true;
  } });
  await page.locator("#video-input").fill("BV14jFvzbEvj");
  await page.locator("#extract-button").click();
  await page.locator("#retry-task").waitFor({ state: "visible" });
  await page.locator("#extract-button").click();
  await page.locator("#output-shell").waitFor({ state: "visible" });
  assert.equal(keys.length, 2);
  assert.ok(keys[0]);
  assert.equal(keys[0], keys[1]);
});

test("a temporary health failure does not change the active media operation", async t => {
  let checks = 0;
  const { page } = await workspace(t, { running: true, beforeLoad: page => page.clock.install(),
    route: async (route, endpoint) => {
      if (endpoint !== "/api/health" || ++checks === 1) return false;
      await route.fulfill({ status: 503, json: {} });
      return true;
    }
  });
  await page.locator('input[name="operation"][value="audio"]').locator("..").click();
  await page.locator("#video-input").fill("BV14jFvzbEvj");
  await page.locator("#extract-button").click();
  await page.clock.fastForward(31000);
  await page.waitForFunction(() => document.querySelector("#service-label").textContent === "服务异常");
  assert.equal(await page.locator('input[name="operation"][value="audio"]').isChecked(), true);
  assert.equal(await page.locator("#extract-button").isDisabled(), true);
});

test("repeated invalid polling responses pause and manual reconnect only performs GET", async t => {
  let polls = 0, recovered = false;
  const { page, submissions } = await workspace(t, { waiting: true,
    beforeLoad: page => page.clock.install(),
    route: async (route, endpoint) => {
      if (!endpoint.startsWith("/api/jobs/") || route.request().method() !== "GET") return false;
      polls += 1;
      await route.fulfill({ json: recovered
        ? { id: "fixture-job", status: "completed", result: { content: "重连完成", format: "txt" } }
        : {} });
      return true;
    }
  });
  await page.locator("#video-input").fill("BV14jFvzbEvj");
  await page.locator("#extract-button").click();
  for (let index = 0; index < 6; index += 1) {
    const response = page.waitForResponse(resp => new URL(resp.url()).pathname === "/api/jobs/fixture-job");
    await page.clock.fastForward(31000);
    await response;
    await page.waitForFunction(() => document.querySelector("#status-title").textContent === "连接暂时中断");
  }
  await page.locator("#retry-task").waitFor({ state: "visible" });
  assert.equal(await page.locator("#retry-task").textContent(), "重新连接");
  assert.equal(polls, 6);
  await page.clock.fastForward(120000);
  assert.equal(polls, 6);
  recovered = true;
  await page.locator("#retry-task").click();
  await page.locator("#output-shell").waitFor({ state: "visible" });
  assert.equal(await page.locator("#output").textContent(), "重连完成");
  assert.equal(submissions.length, 1);
});

test("an ended session sends the browser back to the gate and forgets the saved job", async t => {
  // Leaving the page cancels requests still in flight; WebKit reports those as page errors.
  const { page } = await workspace(t, { waiting: true, ignoreErrors: /access control checks|Load failed/, route: async (route, endpoint) => {
    if (!endpoint.startsWith("/api/jobs/")) return false;
    await route.fulfill({ status: 401, json: { detail: { reason: "authentication_required" } } });
    return true;
  } });
  await page.locator("#video-input").fill("BV14jFvzbEvj");
  await page.locator("#extract-button").click();
  await page.waitForURL(url => url.pathname === "/login");
  assert.equal(await page.evaluate(() => Object.keys(localStorage).some(key => key.startsWith("caption-active-job-"))), false);
});

test("the account menu shows today's quota, devices and only the code's last characters", async t => {
  const { page } = await workspace(t, { me: { label: "小王", max_devices: 3, active_sessions: 2, code_hint: "K7Q2",
    code_expires_at: null, quota: { used: 27, limit: 30, remaining: 3, resets_in: 7200 } } });
  await page.locator("#account-trigger").click();
  assert.equal(await page.locator("#account-name").textContent(), "小王");
  assert.match(await page.locator("#account-quota-label").textContent(), /今日 27 \/ 30 次 · 2 小时后重置/);
  assert.equal(await page.locator("#account-quota").evaluate(element => element.classList.contains("low")), true);
  assert.match(await page.locator("#account-session-summary").textContent(), /2 \/ 3 台设备/);
  assert.match(await page.locator("#account-code").textContent(), /···K7Q2 · 长期有效/);
  assert.equal(await page.locator("#admin-link").isVisible(), false);
});

test("an older part lookup cannot erase the current video's parts", async t => {
  let firstRoute;
  const { page } = await workspace(t, { route: async (route, endpoint) => {
    if (endpoint === "/api/bilibili/pages" && new URL(route.request().url()).searchParams.get("input") === "BV1xx411c7mD") {
      firstRoute = route;
      return true;
    }
    return false;
  } });
  await page.locator("#video-input").fill("BV1xx411c7mD");
  await page.waitForRequest(req => req.url().includes("/api/bilibili/pages"));
  await page.locator("#video-input").fill("BV14jFvzbEvj");
  await page.locator("#page-selector-row").waitFor({ state: "visible" });
  await firstRoute.fulfill({ json: { pages: [], base_url: "", current_page: 1 } });
  await page.waitForLoadState("networkidle");
  assert.equal(await page.locator("#page-selector-row").isVisible(), true);
  assert.equal(await page.locator("#page-select option").count(), 2);
});

test("mobile failure returns to editable input without auto retrying", async t => {
  const { page, submissions } = await workspace(t, { failure: true, viewport: { width: 390, height: 844 } });
  await page.locator("#video-input").fill("BV14jFvzbEvj");
  await page.locator("#extract-button").click();
  await page.locator("#retry-task").waitFor({ state: "visible" });
  await screenshot(page, "mobile-error");
  await page.locator("#retry-task").click();
  assert.equal(await page.locator("#video-input").inputValue(), "BV14jFvzbEvj");
  assert.equal(submissions.length, 1);
});

test("media progress uses conversion labels and disables mutable inputs", async t => {
  const { page } = await workspace(t, { running: true, viewport: { width: 390, height: 844 } });
  await page.locator('input[name="operation"][value="video"]').locator("..").click();
  await page.locator("#video-input").fill("BV14jFvzbEvj");
  await page.locator("#extract-button").click();
  await page.waitForFunction(() => document.querySelector("#progress-track").getAttribute("aria-valuenow") === "58");
  assert.equal(await page.locator('#stage-track [data-stage="recognize"] span').textContent(), "转换");
  assert.equal(await page.locator("#stage-track li.active").getAttribute("data-stage"), "recognize");
  assert.equal(await page.locator("#result-title").textContent(), "正在提取视频");
  assert.equal(await page.locator("#video-input").isDisabled(), true);
  await screenshot(page, "mobile-progress");
});

test("expired saved job clears local state and offers recovery", async t => {
  const { page } = await workspace(t, { expired: true });
  await page.locator("#retry-task").waitFor({ state: "visible" });
  assert.equal(await page.evaluate(() => localStorage.getItem("caption-active-job-v1:7")), null);
});

test("queued and cancelled tasks show their current state", async t => {
  const { page } = await workspace(t, { waiting: true });
  await page.locator("#video-input").fill("BV14jFvzbEvj");
  await page.locator("#extract-button").click();
  await page.locator("#cancel-job").waitFor({ state: "visible" });
  assert.equal(await page.locator("#result-title").textContent(), "任务排队中");
  assert.match(await page.locator("#queue-badge").textContent(), /前方 1 个任务/);
  await page.locator("#cancel-job").click();
  await page.waitForFunction(() => document.querySelector("#result-title").textContent === "任务已取消");
  assert.equal(await page.locator("#video-input").isDisabled(), false);
  assert.equal(await page.locator("#idle-title").textContent(), "任务已取消");
});

test("desktop settings remain reachable above the sticky submit bar", async t => {
  const { page } = await workspace(t, { viewport: { width: 1280, height: 720 } });
  await page.locator("#advanced-options summary").click();
  await page.locator("#force-refresh").check();
  assert.equal(await page.locator("#force-refresh").isChecked(), true);
  await page.locator("#lang-select").selectOption("en");
  assert.equal(await page.locator("#lang-select").inputValue(), "en");
});

test("mobile cloud consent fits and dismisses without a submission", async t => {
  const { page, submissions } = await workspace(t, { viewport: { width: 320, height: 568 } });
  await page.locator("#video-input").fill("BV14jFvzbEvj");
  await page.locator("#cloud-mode-zone summary").click();
  await page.locator('input[name="asr-mode"][value="high_accuracy"]').locator("..").click();
  await page.locator("#extract-button").click();
  await page.locator("#cloud-confirm-dialog").waitFor({ state: "visible" });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  await screenshot(page, "mobile-cloud-consent");
  await page.locator("#cancel-cloud-confirm").click();
  assert.equal(submissions.length, 0);
  assert.equal(await page.locator('input[name="asr-mode"][value="auto"]').isChecked(), true);
});

test("theme toggle cycles system, light and dark and survives a reload", async t => {
  const { page } = await workspace(t);
  const theme = () => page.evaluate(() => document.documentElement.dataset.theme || "system");
  assert.equal(await theme(), "system");
  await page.locator("#theme-toggle").click();
  assert.equal(await theme(), "light");
  await page.locator("#theme-toggle").click();
  assert.equal(await theme(), "dark");
  await screenshot(page, "workspace-dark");
  await page.reload();
  await page.locator("body.app-ready").waitFor();
  assert.equal(await theme(), "dark");
  assert.equal(await page.locator("#theme-toggle").getAttribute("data-mode"), "dark");
  await page.locator("#theme-toggle").click();
  assert.equal(await theme(), "system");
  assert.equal(await page.evaluate(() => localStorage.getItem("video-workspace-theme")), null);
});

test("timed segments render as a reading view with search and per-line copy", async t => {
  const segments = [
    { start: 0, end: 2.5, text: "第一段测试字幕。" },
    { start: 65, end: 68, text: "第二段介绍缓存与任务恢复。" },
    { start: 3725, end: 3727, text: "字幕结果保留原始语义。" }
  ];
  const { page, submissions } = await workspace(t, { route: async (route, endpoint) => {
    if (endpoint !== "/api/jobs" || route.request().method() !== "POST") return false;
    submissions.push({ endpoint });
    await route.fulfill({ json: { id: "fixture-job", status: "completed", expires_at: Date.now() / 1000 + 86400,
      result: { content: segments.map(item => item.text).join("\n"), format: "txt", filename: "f.txt", segments,
        raw_content: "原始。", raw_segments: [{ start: 0, end: 1, text: "原始。" }],
        metadata: { title: "逐句测试", platform: "bilibili", source: "official_no_cookie" } } } });
    return true;
  } });
  await page.context().grantPermissions(["clipboard-read", "clipboard-write"]).catch(() => {});
  await page.locator("#video-input").fill("BV14jFvzbEvj");
  await page.locator("#extract-button").click();
  await page.locator("#segment-list").waitFor({ state: "visible" });
  assert.equal(await page.locator("#segment-list .segment").count(), 3);
  assert.deepEqual(await page.locator("#segment-list .segment-time").allTextContents(), ["00:00", "01:05", "1:02:05"]);
  assert.equal(await page.locator("#output").isVisible(), false);
  assert.match(await page.locator("#output-stats-label").textContent(), /3 句/);
  await page.locator("#result-search").fill("字幕");
  await page.waitForFunction(() => document.querySelector("#search-count").textContent === "2 处");
  assert.equal(await page.locator("#segment-list .segment.match").count(), 2);
  await screenshot(page, "segments-desktop");
  await page.locator("#segment-list .segment-time").nth(1).click();
  await page.waitForFunction(() => document.querySelector("#toast").textContent.includes("01:05"));
  await page.locator("#toggle-raw").click();
  assert.equal(await page.locator("#segment-list .segment").count(), 1);
  await page.locator("#view-source").click();
  assert.equal(await page.locator("#output").isVisible(), true);
  assert.equal(await page.locator("#segment-list").isVisible(), false);
  assert.equal(await page.locator("#output").textContent(), "原始。");
  await page.reload();
  await page.locator("body.app-ready").waitFor();
  assert.equal(await page.evaluate(() => JSON.parse(localStorage.getItem("video-workspace-preferences-v1:7")).resultView), "source");
  assert.equal(submissions.length, 1);
});

test("a Bilibili refusal is explained before submission and offers the upload path", async t => {
  const limited = { ...config, platform_status: { bilibili: { state: "limited", message: "B站当前拒绝了服务器的访问" } } };
  const { page, submissions } = await workspace(t, { config: limited });
  assert.equal(await page.locator("#platform-notice").isVisible(), false);
  assert.match(await page.locator("#bilibili-chip").getAttribute("class"), /limited/);
  assert.equal(await page.locator("#service-label").textContent(), "部分受限");
  await page.locator("#video-input").fill("https://www.bilibili.com/video/BV14jFvzbEvj");
  await page.locator("#platform-notice").waitFor({ state: "visible" });
  await screenshot(page, "bilibili-limited");
  await page.locator("#video-input").fill("https://v.douyin.com/abc/");
  assert.equal(await page.locator("#platform-notice").isVisible(), false);
  await page.locator("#video-input").fill("BV14jFvzbEvj");
  await page.locator("#platform-notice-action").click();
  await page.locator("#upload-input-panel").waitFor({ state: "visible" });
  assert.equal(submissions.length, 0);
});

test("a platform refusal during a task marks Bilibili as limited", async t => {
  let refused = false;
  const { page } = await workspace(t, { route: async (route, endpoint) => {
    if (endpoint.endsWith("config") && refused) {
      // The server's access guard reports the refusal from now on.
      await route.fulfill({ json: { ...config, platform_status: { bilibili: { state: "limited" } } } });
      return true;
    }
    if (endpoint !== "/api/jobs" || route.request().method() !== "POST") return false;
    refused = true;
    await route.fulfill({ status: 503, json: { detail: { code: "platform_blocked", reason: "platform_risk_control",
      message: "B站当前拒绝了服务器的访问", retryable: false } } });
    return true;
  } });
  await page.locator("#video-input").fill("BV14jFvzbEvj");
  await page.locator("#extract-button").click();
  await page.locator("#retry-task").waitFor({ state: "visible" });
  assert.match(await page.locator("#status-detail").textContent(), /平台风控/);
  await page.locator("#retry-task").click();
  await page.locator("#platform-notice").waitFor({ state: "visible" });
});

test("history drawer closes with Escape and returns focus to its trigger", async t => {
  const { result, ...summary } = savedSubtitle();
  const { page } = await workspace(t, { history: [summary] });
  assert.equal(await page.locator("#history-count").textContent(), "1");
  await page.locator("#open-history").click();
  await page.locator("#history-drawer").waitFor({ state: "visible" });
  assert.equal(await page.locator("#close-history").evaluate(e => e === document.activeElement), true);
  await page.keyboard.press("Escape");
  assert.equal(await page.locator("#history-drawer").isVisible(), false);
  assert.equal(await page.locator("#open-history").evaluate(e => e === document.activeElement), true);
});

test("the gate formats codes, explains failures, waits out a lock and enters on success", async t => {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, reducedMotion: "reduce" });
  t.after(() => context.close());
  const page = await context.newPage();
  const errors = [], attempts = [];
  page.on("pageerror", error => errors.push(error.message));
  t.after(() => assert.deepEqual(errors, []));
  const replies = [
    { status: 401, json: { detail: { reason: "invalid_code", message: "激活码不正确。", attempts_left: 2 } } },
    { status: 429, json: { detail: { reason: "gate_locked", message: "locked", retry_after: 2 } } },
    { status: 200, json: { ok: true, user: { label: "小王", role: "member" } } }
  ];
  await page.route("**/api/auth/activate", async route => {
    attempts.push(route.request().postDataJSON());
    await route.fulfill(replies.shift());
  });
  await page.route(url => new URL(url).pathname === "/", route => route.fulfill({ body: "<p>workspace</p>", contentType: "text/html" }));
  await page.goto(`${base}/login`);
  const input = page.locator("#code");
  await input.pressSequentially("abcde fghjk-mnpqr");
  assert.equal(await input.inputValue(), "ABCDE-FGHJK-MNPQR");
  assert.equal(await page.locator("#unlock").isDisabled(), true);
  await input.pressSequentially("stvwo");
  assert.equal(await input.inputValue(), "ABCDE-FGHJK-MNPQR-STVW0");
  await page.locator("#unlock").click();
  await page.waitForFunction(() => document.querySelector("#gate-message").textContent.includes("还可以再试 2 次"));
  await page.locator("#unlock").click();
  await page.waitForFunction(() => document.querySelector("#code").disabled);
  assert.match(await page.locator("#gate-message").textContent(), /暂时锁定/);
  await page.waitForFunction(() => !document.querySelector("#code").disabled, null, { timeout: 5000 });
  await page.locator("#unlock").click();
  await page.waitForURL(url => url.pathname === "/");
  assert.deepEqual(attempts.map(item => item.code), Array(3).fill("ABCDE-FGHJK-MNPQR-STVW0"));
});
