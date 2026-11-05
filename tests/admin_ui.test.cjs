const { test, before, after } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const path = require("node:path");
const http = require("node:http");
const { chromium, webkit } = require("playwright");

let browser, server, base;
const staticRoot = path.join(__dirname, "../app/static");
const now = () => Math.floor(Date.now() / 1000);

before(async () => {
  const files = { "/admin": "admin.html" };
  server = http.createServer(async (req, res) => {
    const pathname = new URL(req.url, "http://localhost").pathname;
    const name = files[pathname] || (pathname.startsWith("/static/") ? pathname.slice(8) : null);
    try {
      const data = await fs.readFile(path.join(staticRoot, name));
      res.setHeader("Content-Type", name.endsWith(".css") ? "text/css" : name.endsWith(".js") ? "text/javascript"
        : name.endsWith(".svg") ? "image/svg+xml" : "text/html");
      res.end(data);
    } catch (_) {
      res.writeHead(404);
      res.end();
    }
  });
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  base = `http://127.0.0.1:${server.address().port}`;
  browser = await (process.env.UI_BROWSER === "webkit" ? webkit : chromium).launch();
});

after(async () => {
  if (browser) await browser.close();
  if (server) await new Promise(resolve => server.close(resolve));
});

function members() {
  return [
    { id: 4, label: "站长", role: "owner", state: "active", created_at: now() - 86400 * 90, last_login_at: now(),
      code: { hint: "TK77", created_at: now(), expires_at: null, last_used_at: now(), use_count: 3 },
      max_devices: 10, max_devices_override: null, daily_job_limit: null, daily_job_limit_override: null,
      jobs_today: 5, devices: [{ id: 11, created_at: now(), last_seen_at: now(), device: "Mac · Chrome", ip: "45.78.7.1" }] },
    { id: 9, label: "<img src=x onerror=window.__xss=1>", role: "member", state: "active", created_at: now() - 3600,
      last_login_at: null, code: { hint: "1XEF", created_at: now(), expires_at: now() + 86400 * 30, last_used_at: null,
        use_count: 0 }, max_devices: 3, max_devices_override: null, daily_job_limit: 30, daily_job_limit_override: null,
      jobs_today: 30, devices: [] }
  ];
}

async function console_(t, options = {}) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 }, reducedMotion: "reduce" });
  context.setDefaultTimeout(9000);
  t.after(() => context.close());
  const page = await context.newPage();
  const errors = [], calls = [];
  page.on("pageerror", error => errors.push(error.message));
  t.after(() => assert.deepEqual(errors, []));
  let polls = 0;
  await page.route("**/api/**", async route => {
    const req = route.request();
    const endpoint = new URL(req.url()).pathname;
    calls.push(`${req.method()} ${endpoint}`);
    let body = {};
    if (endpoint === "/api/admin/members" && req.method() === "GET") {
      body = { members: options.members || members(), defaults: { max_devices: 3, daily_job_limit: 30, max_active_jobs: 2 } };
    } else if (endpoint === "/api/admin/members" && req.method() === "POST") {
      calls.push(JSON.stringify(req.postDataJSON()));
      body = { ok: true, code: "ABCDE-FGHJK-MNPQR-STVWX", member_id: 12 };
    } else if (endpoint === "/api/admin/gate") {
      body = { summary: { granted_24h: 4, denied_24h: 6, locked: [{ ip: "203.0.113.9", retry_after: 600, failures: 5 }] },
        events: [{ at: now(), kind: "denied", ip: "203.0.113.9", detail: "unknown", member: null },
          { at: now() - 60, kind: "granted", ip: "45.78.7.1", detail: null, member: "站长" }] };
    } else if (endpoint === "/api/admin/gate/unlock") {
      calls.push(JSON.stringify(req.postDataJSON()));
      body = { ok: true, cleared: 5 };
    } else if (endpoint === "/api/admin/bilibili" && req.method() === "GET") {
      body = { state: "none", logged_in: false };
    } else if (endpoint === "/api/admin/bilibili/qrcode") {
      body = { ok: true, qrcode_key: "fixture-qr-key", expires_in: 180,
        qr_svg_data_url: "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciLz4=" };
    } else if (endpoint.startsWith("/api/admin/bilibili/qrcode/")) {
      polls += 1;
      body = polls === 1 ? { ok: true, status: "waiting_confirm" }
        : { ok: true, status: "success", account: { state: "ok", logged_in: true, uname: "大号", mid: 42, level: 6,
          vip: true, vip_label: "年度大会员", saved_at: now(), checked_at: now() } };
    } else if (endpoint === "/api/admin/diagnostics") {
      body = { status: "ok", generated_at: now(), service: { version: "1.2.0", active_users: 2 },
        queue: { worker_alive: true, queued: 0, running: 0 }, tools: { ffmpeg: true, ffprobe: false } };
    }
    await route.fulfill({ json: body });
  });
  await page.goto(`${base}/admin`);
  await page.locator(".member").first().waitFor();
  return { page, calls };
}

test("members render as text with limits, devices and owner protections", async t => {
  const { page } = await console_(t);
  const cards = page.locator(".member");
  assert.equal(await cards.count(), 2);
  assert.equal(await page.evaluate(() => window.__xss), undefined);
  assert.equal(await cards.nth(1).locator(".member-head strong").textContent(), "<img src=x onerror=window.__xss=1>");
  assert.match(await cards.nth(1).locator(".member-code").textContent(), /1XEF.*30 天后到期/);
  assert.equal(await cards.nth(1).locator(".meter").evaluate(element => element.classList.contains("full")), true);
  assert.equal(await cards.nth(0).locator('[data-action="delete"], [data-action="toggle"]').count(), 0);
  assert.equal(await cards.nth(1).locator('[data-action="delete"]').count(), 1);
  assert.equal(await page.locator("#stat-members").textContent(), "2");
  assert.equal(await page.locator("#stat-jobs").textContent(), "35");
  assert.match(await page.locator("#stat-gate").textContent(), /6 次拦截/);
});

test("a new code is shown once and leaves the page when the dialog closes", async t => {
  const { page, calls } = await console_(t);
  await page.locator("#issue-open").click();
  await page.locator("#issue-label").fill("小王");
  await page.locator("#issue-days").selectOption("7");
  await page.locator("#issue-jobs").selectOption("0");
  await page.locator("#issue-submit").click();
  await page.locator("#code-dialog").waitFor({ state: "visible" });
  assert.equal(await page.locator("#code-value").textContent(), "ABCDE-FGHJK-MNPQR-STVWX");
  assert.equal(await page.locator("#code-member").textContent(), "小王");
  assert.ok(calls.includes(JSON.stringify({ label: "小王", expires_in_days: 7, daily_job_limit: 0 })));
  await page.locator("#code-dialog .code-done").click();
  assert.equal(await page.locator("#code-dialog").isHidden(), true);
  assert.equal(await page.evaluate(() => document.body.innerText.includes("ABCDE-FGHJK")), false);
});

test("the Bilibili QR login walks from scan to a confirmed account", async t => {
  const { page } = await console_(t);
  await page.locator("#tab-bilibili").click();
  assert.equal(await page.locator("#bili-title").textContent(), "还没有登录 B站");
  await page.locator("#bili-login").click();
  await page.waitForFunction(() => document.querySelector("#qr-image").src.startsWith("data:image/svg+xml"));
  await page.waitForFunction(() => document.querySelector("#qr-card").classList.contains("scanned"));
  await page.waitForFunction(() => document.querySelector("#qr-card").classList.contains("success"));
  assert.equal(await page.locator("#bili-title").textContent(), "大号");
  assert.match(await page.locator("#bili-sub").textContent(), /UID 42 · Lv6 · 年度大会员/);
  assert.equal(await page.locator("#bili-state").textContent(), "已登录");
  assert.equal(await page.locator("#stat-bili").textContent(), "大号");
});

test("the gate log lists attempts and unlocks a locked address", async t => {
  const { page, calls } = await console_(t);
  await page.locator("#tab-gate").click();
  await page.locator(".event").first().waitFor();
  assert.match(await page.locator(".event.denied").textContent(), /拦截 · 未知激活码/);
  assert.match(await page.locator(".event.granted").textContent(), /放行 · 站长/);
  await page.locator('.lock-chip button[data-ip="203.0.113.9"]').click();
  await page.waitForFunction(() => document.querySelector("#toast").textContent.includes("已解锁"));
  assert.ok(calls.includes(JSON.stringify({ ip: "203.0.113.9" })));
  await page.locator("#tab-system").click();
  await page.locator(".system-card").first().waitFor();
  assert.match(await page.locator("#system-updated").textContent(), /服务版本 1\.2\.0/);
  assert.equal(await page.locator(".system-card dd.bad").first().textContent(), "否");
});
