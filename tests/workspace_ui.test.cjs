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
    media: true, guest_media: true, embedded_subtitles: true },
  platforms: { bilibili: true, douyin: true, upload: true },
  asr_modes: { auto: { available: true, processing: "local" } },
  uploads: { enabled: true, max_bytes: 536870912, allowed_extensions: [".mp4", ".mkv"] },
  media: { enabled: true },
  guest_media: { enabled: true, max_duration_seconds: 1800 }
};

before(async () => {
  const files = { "/": "index.html", "/static/app.css": "app.css", "/static/app.js": "app.js" };
  server = http.createServer(async (req, res) => {
    const name = files[new URL(req.url, "http://localhost").pathname];
    if (!name) { res.writeHead(404); res.end(); return; }
    const data = await fs.readFile(path.join(staticRoot, name));
    res.setHeader("Content-Type", name.endsWith(".css") ? "text/css" : name.endsWith(".js") ? "text/javascript" : "text/html");
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
  t.after(() => assert.deepEqual(errors, []));
  await page.route("**/api/**", async route => {
    const req = route.request();
    const endpoint = new URL(req.url()).pathname;
    let status = 200, body = {};
    if (endpoint === "/api/auth/me") {
      status = options.guest ? 401 : 200;
      body = options.guest ? {} : { user: { id: 7, username: "preview", created_at: 1700000000 } };
    } else if (endpoint === "/api/health") body = { status: "ok" };
    else if (endpoint.endsWith("config")) body = config;
    else if (endpoint === "/api/bilibili/pages") body = {
      base_url: "https://www.bilibili.com/video/BV14jFvzbEvj", current_page: 1,
      pages: [{ page: 1, title: "Introduction" }, { page: 2, title: "Part two" }]
    };
    else if (req.method() === "DELETE" && endpoint.startsWith("/api/jobs/")) body = { id: "fixture-job", status: "cancelled" };
    else if (req.method() === "POST") {
      const payload = req.postDataJSON();
      submissions.push({ endpoint, payload });
      if (options.failure) { status = 503; body = { detail: { reason: "download_failed" } }; }
      else if (options.waiting) body = { id: "fixture-job", status: "queued", progress: 3, queue_position: 2 };
      else if (options.running) body = { id: "fixture-job", status: "running", stage: "media_convert", progress: 58, message: "正在转换" };
      else body = { id: "fixture-job", status: "completed", result: {
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
  await page.goto(base);
  await page.locator("body.app-ready").waitFor();
  return { page, submissions };
}

async function screenshot(page, name) {
  if (captureRoot) await page.screenshot({ path: path.join(captureRoot, `${name}.png`), fullPage: true, animations: "disabled" });
}

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

test("guest media has operation-specific empty state and no server metrics", async t => {
  const { page } = await workspace(t, { guest: true });
  assert.equal(await page.locator("#idle-title").textContent(), "尚无视频");
  await page.locator("#rail-audio").click();
  assert.equal(await page.locator("#idle-format").textContent(), "MP3");
  assert.equal(await page.locator("#idle-title").textContent(), "尚无音频");
  assert.equal(await page.locator("#input-mode-group").isVisible(), false);
  assert.equal(await page.locator("#cloud-mode-zone").isVisible(), false);
  await page.locator("#health-trigger").click();
  assert.doesNotMatch(await page.locator("#health-popover").textContent(), /RSS|CPU|内存|磁盘|\/opt\//);
  await screenshot(page, "guest-audio");
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
  assert.match(await page.locator("#search-count").textContent(), /2 处/);
  await screenshot(page, "completed-desktop");
  await page.locator("#rail-new-task").click();
  assert.equal(await page.locator("#output-shell").isVisible(), false);
  assert.equal(await page.locator("#output").textContent(), "");
  assert.equal(await page.locator("#idle-title").textContent(), "尚无字幕");
});

test("mobile failure returns to editable input without auto retrying", async t => {
  const { page, submissions } = await workspace(t, { guest: true, failure: true, viewport: { width: 390, height: 844 } });
  await page.locator("#video-input").fill("BV14jFvzbEvj");
  await page.locator("#extract-button").click();
  await page.locator("#retry-task").waitFor({ state: "visible" });
  await screenshot(page, "mobile-error");
  await page.locator("#retry-task").click();
  assert.equal(await page.locator("#video-input").inputValue(), "BV14jFvzbEvj");
  assert.equal(submissions.length, 1);
});

test("media progress uses conversion labels and disables mutable inputs", async t => {
  const { page } = await workspace(t, { guest: true, running: true, viewport: { width: 390, height: 844 } });
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
