const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const test = require("node:test");

const source = fs.readFileSync(path.join(__dirname, "../app/static/admin.js"), "utf8");

async function render(overrides = {}) {
  const nodes = new Map();
  const element = () => ({
    textContent: "", className: "", hidden: false,
    classList: { add() {}, toggle() {} },
    addEventListener() {}, replaceChildren() {}, append() {}, appendChild() {}, setAttribute() {},
  });
  const document = {
    getElementById(id) {
      if (!nodes.has(id)) nodes.set(id, element());
      return nodes.get(id);
    },
    createElement: element,
  };
  const data = {
    status: "ok", generated_at: 1_700_000_000,
    service: { version: "test", active_users: 1 },
    queue: { worker_alive: true, workers_alive: 1, worker_count: 1, queued: 0, running: 0, max_pending: 4 },
    asr_worker: { alive: false, persistent_enabled: true, exit_on_idle: true },
    memory: { system_available_mb: 2048, process_rss_mb: 100 },
    disk: { available: true, free_ratio: 0.5, free_bytes: 1024, total_bytes: 2048 },
    cloud_asr: { enabled: false, usage: {}, failures: { total: 0 } },
    platforms: { bilibili: { enabled: true } },
    tools: { ffmpeg: true, ffprobe: true },
    ...overrides,
  };
  vm.runInNewContext(source, {
    document,
    fetch: async () => ({ ok: true, json: async () => data }),
  });
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(nodes.get("freshness-text").textContent, "数据已更新");
  return nodes;
}

test("an idle ASR child is normal on-demand operation", async () => {
  const nodes = await render();
  assert.equal(nodes.get("asr-state").textContent, "按需启动");
  assert.equal(nodes.get("asr-state").className, "section-state neutral");
});

test("a warm ASR child is displayed as ready", async () => {
  const nodes = await render({ asr_worker: { alive: true, warm: true } });
  assert.equal(nodes.get("asr-state").textContent, "已预热");
});

test("unavailable failure statistics are never displayed as zero failures", async () => {
  for (const failures of [{ total: 0, available: false }, {}]) {
    const nodes = await render({ cloud_asr: { enabled: true, usage: {}, failures } });
    assert.equal(nodes.get("failure-state").textContent, "暂不可用");
    assert.equal(nodes.get("failure-state").className, "section-state warn");
  }
});

test("known zero and nonzero failure totals retain their distinct states", async () => {
  const empty = await render();
  assert.equal(empty.get("failure-state").textContent, "无失败");
  const failed = await render({ cloud_asr: { usage: {}, failures: { total: 3 } } });
  assert.equal(failed.get("failure-state").textContent, "3 条");
});
