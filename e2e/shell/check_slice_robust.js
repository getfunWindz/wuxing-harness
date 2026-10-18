/* A 套件：功能连接 + 健壮性（UI 表现 + 服务器事实双证）。本地资产。
   原则（用户裁决）：函数通 ≠ 无错；UI 齐 ≠ 交互对——每条断言必须端到端对账，
   失败路径必须可感知。任务窗口内不做高频轮询（CDP 伪影）——固定等待后读取。

   用法：node e2e/shell/check_slice_robust.js
   自管理服务：按场景 spawn/kill serve_fake_modes.py（fresh state 每场景）。 */
const { spawn } = require("node:child_process");
const os = require("node:os");
const path = require("node:path");
const puppeteer = require("puppeteer-core");

const EDGE = process.env.EDGE_PATH ||
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
const PORT = Number(process.env.PORT || 8835);
const BASE = `http://127.0.0.60:${PORT}`;
const SLICE = `${BASE}/next/`;
const PY = process.env.PYTHON || "python";
const SERVICE = path.join(__dirname, "serve_fake_modes.py");

const results = [];
function check(name, pass, detail) {
  results.push({ name, pass });
  console.log(`${pass ? "PASS" : "FAIL"}  ${name}${detail ? "  :: " + detail : ""}`);
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function fetchJson(url, init) {
  const res = await fetch(url, init);
  return res.json();
}

// E0-1（2026-10-02）：条件等待（固定采样窗口在负载下会错过首 run 注册）
const waitFor = async (fn, timeoutMs = 4000) => {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await fn()) return true;
    await sleep(120);
  }
  return false;
};

function freshStateDir(tag) {
  return path.join(os.tmpdir(), `wuxing-a-${tag}-${Date.now()}`);
}

function startService(mode, stateDir) {
  const proc = spawn(PY, [SERVICE, String(PORT), mode, stateDir],
    { stdio: ["ignore", "pipe", "pipe"] });
  const started = new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("service start timeout")), 15000);
    proc.stdout.on("data", (chunk) => {
      if (String(chunk).includes("URL ")) { clearTimeout(timer); resolve(proc); }
    });
    proc.stderr.on("data", (chunk) => process.stderr.write(String(chunk)));
    proc.on("exit", () => clearTimeout(timer));
  });
  return started;
}

async function stopService(proc) {
  if (!proc) return;
  proc.kill();
  for (let i = 0; i < 30; i += 1) {
    try { await fetch(`${BASE}/health`); await sleep(100); } catch { return; }
  }
}

async function openSlice(browser) {
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 900, deviceScaleFactor: 1 });
  page.on("pageerror", (e) => console.log("PAGEERROR:", e.message));
  await page.goto(SLICE, { waitUntil: "domcontentloaded" });
  for (let i = 0; i < 200; i += 1) {
    const state = await page.evaluate(() => document.body.dataset.state);
    if (state === "ready") break;
    await sleep(50);
  }
  return page;
}

async function submit(page, text) {
  const sel = await page.evaluate(() => {
    const vis = (s) => { const el = document.querySelector(s); return !!(el && el.offsetParent !== null); };
    return vis(".hero-text") ? ".hero-text" : ".cbox textarea";
  });
  await page.click(sel);
  await page.type(sel, text);
  await page.keyboard.press("Enter");
}

async function wsId(name) {
  const list = await fetchJson(`${BASE}/api/v1/workspaces`);
  return list.workspaces.find((w) => w.name === name)?.id;
}

async function snapshotOf(name) {
  return fetchJson(`${BASE}/api/v1/workspaces/${await wsId(name)}/snapshot`);
}

async function historyOf(name) {
  const data = await fetchJson(`${BASE}/api/v1/workspaces/${await wsId(name)}/tasks/history`);
  return data.history ?? [];
}

// ---- S1 提交闭环 ----
async function s1(browser) {
  const proc = await startService("done", freshStateDir("s1"));
  const page = await openSlice(browser);
  try {
    await submit(page, "A-S1 提交闭环");
    await sleep(2500);
    const rows = await page.evaluate(() =>
      [...document.querySelectorAll(".unit-card")].map((el) => el.textContent));
    const meta = await page.evaluate(() =>
      document.querySelector(".stream-meta")?.textContent ?? "");
    const report = await page.evaluate(() =>
      document.querySelector(".stream-report")?.textContent ?? "");
    check("S1 UI：单元行出现", rows.some((r) => r.includes("F-1")), rows.join("|"));
    check("S1 UI：状态完成", meta.includes("完成"), meta);
    check("S1 UI：报告可见", report.includes("mock 报告"), report.slice(0, 30));

    const snap = await snapshotOf("fake-ws");
    check("S1 事实：snapshot.result=done", snap.result?.status === "done",
      JSON.stringify(snap.result?.status ?? null));
    const hist = await historyOf("fake-ws");
    check("S1 事实：history[0].run_id 与快照一致",
      hist[0]?.run_id === snap.run_id && hist.length === 1,
      `${hist[0]?.run_id} vs ${snap.run_id} (n=${hist.length})`);
  } finally {
    await page.close();
    await stopService(proc);
  }
}

// ---- S2 确认门 ----
async function s2(browser) {
  const proc = await startService("confirm", freshStateDir("s2"));
  const page = await openSlice(browser);
  try {
    await submit(page, "A-S2 确认门");
    // E0-1 同口径：冷启动（首进程/首工作区/首 run）在机器负载下可能 >1.8s——
    // 固定窗口会错过事件；改为条件下等待卡片（断言语义不变：卡片必须出现）。
    await waitFor(async () => await page.evaluate(() =>
      document.querySelectorAll(".stream-confirm-row").length >= 1), 8000);
    const pending = await page.evaluate(() =>
      document.querySelector(".stream-meta")?.textContent ?? "");
    const cards = await page.evaluate(() =>
      document.querySelectorAll(".stream-confirm-row").length);
    check("S2 UI：待确认区出现", cards >= 1, `${cards} 卡 · ${pending}`);
    check("S2 UI：状态待确认", pending.includes("待确认"), pending);

    if (cards >= 1) await page.click('[data-st="confirm-approve:F-1"]');
    await sleep(2200);
    const after = await page.evaluate(() =>
      document.querySelector(".stream-meta")?.textContent ?? "");
    const cardsAfter = await page.evaluate(() =>
      document.querySelectorAll(".stream-confirm-row").length);
    const resolved = await page.evaluate(() =>
      document.querySelector('[data-st="confirm-resolved:F-1"]')?.textContent ?? "");
    check("S2 UI：批准后完成", after.includes("完成"), after);
    check("S2 UI：确认区消失 + 已决反馈", cardsAfter === 0 && resolved.includes("已批准"),
      `cards=${cardsAfter} resolved=${resolved}`);

    const meta = await fetchJson(`${BASE}/fake/meta`);
    check("S2 事实：假引擎收到 confirm ≥1", meta.confirms >= 1, JSON.stringify(meta));
    const snap = await snapshotOf("fake-ws");
    check("S2 事实：snapshot.result=done", snap.result?.status === "done",
      JSON.stringify(snap.result?.status ?? snap.active_run?.status ?? null));
  } finally {
    await page.close();
    await stopService(proc);
  }
}

// ---- S3a 引擎失败可见 ----
async function s3a(browser) {
  const proc = await startService("error", freshStateDir("s3a"));
  const page = await openSlice(browser);
  try {
    await submit(page, "A-S3a 引擎失败");
    await sleep(2200);
    const errorText = await page.evaluate(() =>
      document.querySelector(".error-card .card-body p")?.textContent ?? "");
    check("S3a UI：错误可见且含原因", errorText.includes("模拟引擎失败"), errorText.slice(0, 60));
    const hist = await historyOf("fake-ws");
    check("S3a 事实：history 记录 error", hist[0]?.status === "error",
      JSON.stringify(hist[0]?.status ?? null));
    const snap = await snapshotOf("fake-ws");
    check("S3a 事实：快照无结果（未伪成功）", !snap.result, JSON.stringify(snap.result ?? null));
  } finally {
    await page.close();
    await stopService(proc);
  }
}

// ---- S3b + S4 断线：杀服务→失败可见；重启→自动重连+数据恢复 ----
async function s3b_s4(browser) {
  const proc = await startService("done", freshStateDir("s4"));
  const page = await openSlice(browser);
  let proc2 = null;
  try {
    const epochBefore = (await fetchJson(`${BASE}/health`)).epoch;
    await stopService(proc);
    await sleep(2500);
    // 断线反馈：旧壳无连接状态文案（A6 对齐后顶栏只留品牌+使用信息）——
    // 改为「事实型」断言：断线期间页面不崩溃、可交互（后续提交失败全局可见）
    const aliveDown = await page.evaluate(() =>
      !!document.querySelector(".app-shell") && !!document.querySelector(".rail"));
    check("S4 UI：断线期间页面不崩溃（可交互）", aliveDown === true, String(aliveDown));

    await submit(page, "A-S3b 断线提交");
    await sleep(2500);
    // 2026-09-19 口径迁移（批次 G）：运行时错误改瞬时气泡 [data-st=toast]；仅启动失败保留常驻 .app-error
    const errVisible = await page.evaluate(() => {
      const toast = document.querySelector('[data-st="toast"]');
      if (toast && !toast.hasAttribute("hidden")) {
        const t = (toast.textContent || "").trim();
        if (t.length > 0) return t;
      }
      const el = document.querySelector(".app-error");
      return el && !el.hasAttribute("hidden") ? el.textContent : "";
    });
    check("S3b UI：失败全局可见（瞬时气泡，≤5.5s 自动消隐）",
      typeof errVisible === "string" && errVisible.length > 0,
      String(errVisible).slice(0, 80));

    proc2 = await startService("done", path.join(os.tmpdir(), "wuxing-a-s4-restart"));
    // 重连（事实型）：等左栏工作区列表恢复（数据面自动重拉即重连完成的证据）
    const deadline = Date.now() + 12000;
    let namesUp = [];
    while (Date.now() < deadline) {
      namesUp = await page.evaluate(() =>
        [...document.querySelectorAll(".rail-item .rail-name")].map((el) => el.textContent || ""));
      if (namesUp.includes("fake-ws")) break;
      await sleep(500);
    }
    check("S4 UI：重启后自动重连（工作区列表恢复）", namesUp.includes("fake-ws"), namesUp.join(","));
    const epochAfter = (await fetchJson(`${BASE}/health`)).epoch;
    check("S4 事实：服务新实例（epoch 变化）", epochBefore !== epochAfter,
      `${epochBefore} -> ${epochAfter}`);
    const names = await page.evaluate(() =>
      [...document.querySelectorAll(".rail-item .rail-name")].map((el) => el.textContent || ""));
    check("S4 UI：重连后数据恢复（工作区可见）", names.includes("fake-ws"), names.join(","));
  } finally {
    await page.close();
    await stopService(proc2 || proc);
  }
}

// ---- S5 边界：空提交不发起 / 运行中禁用 / 重复提交忽略 ----
async function s5(browser) {
  const proc = await startService("slow", freshStateDir("s5"));
  const page = await openSlice(browser);
  try {
    const before = await fetchJson(`${BASE}/fake/meta`);
    const s5sel = await page.evaluate(() => {
      const vis = (s) => { const el = document.querySelector(s); return !!(el && el.offsetParent !== null); };
      return vis(".hero-text") ? ".hero-text" : ".cbox textarea";
    });
    await page.click(s5sel);
    await page.keyboard.press("Enter");
    await sleep(800);
    const afterEmpty = await fetchJson(`${BASE}/fake/meta`);
    check("S5 事实：空提交不发起 run", afterEmpty.runs === before.runs,
      `${before.runs} -> ${afterEmpty.runs}`);

    await page.type(s5sel, "A-S5 慢任务");
    await page.keyboard.press("Enter");
    const firstStarted = await waitFor(async () =>
      (await fetchJson(`${BASE}/fake/meta`)).runs === afterEmpty.runs + 1, 4000);
    const afterFirst = await fetchJson(`${BASE}/fake/meta`);
    check("S5 事实：首个提交产生 run", firstStarted,
      `${afterEmpty.runs} -> ${afterFirst.runs}`);
    const disabled = await page.evaluate(() => ({
      ta: document.querySelector(".cbox textarea")?.disabled ?? null,
      // 2026-09-22 脚本适配：v20 起 hero 发送键与 composer 共用 .btn-send 类
      // （ef3100d），未限定作用域会命中隐藏的 hero 按钮——限定 .cbox。
      btn: document.querySelector(".cbox .btn-send")?.disabled ?? null,
    }));
    check("S5 UI：运行中输入区与按钮禁用",
      disabled.ta === true && disabled.btn === true, JSON.stringify(disabled));

    await page.keyboard.press("Enter");
    await sleep(400);
    const during = await fetchJson(`${BASE}/fake/meta`);
    check("S5 事实：重复提交被忽略", during.runs === afterFirst.runs,
      `${afterFirst.runs} -> ${during.runs}`);

    await sleep(2600);
    const done = await fetchJson(`${BASE}/fake/meta`);
    check("S5 事实：最终恰好一次 run", done.runs === afterFirst.runs,
      JSON.stringify(done));
  } finally {
    await page.close();
    await stopService(proc);
  }
}

// ---- S6 工作区切换：状态独立 + 切回恢复 ----
async function s6(browser) {
  const proc = await startService("done", freshStateDir("s6"));
  const page = await openSlice(browser);
  try {
    await submit(page, "A-S6 一");
    await sleep(2500);
    await page.evaluate(() => {
      [...document.querySelectorAll(".rail-item")]
        .find((el) => (el.textContent || "").includes("fake-ws2"))?.click();
    });
    await sleep(1500);
    const active = await page.evaluate(() =>
      document.querySelector(".rail-item.active .rail-name")?.textContent ?? "");
    const meta2 = await page.evaluate(() =>
      document.querySelector(".stream-meta")?.textContent ?? "");
    check("S6 UI：切换到 fake-ws2（激活标记）", active === "fake-ws2", active);
    check("S6 UI：ws2 状态独立（就绪、无残留行）",
      meta2.includes("就绪") &&
      (await page.evaluate(() => document.querySelectorAll(".unit-card").length)) === 0,
      meta2);

    const snap1 = await snapshotOf("fake-ws");
    const snap2 = await snapshotOf("fake-ws2");
    check("S6 事实：ws1 有结果", snap1.result?.status === "done",
      JSON.stringify(snap1.result?.status ?? null));
    check("S6 事实：ws2 无结果", !snap2.result, JSON.stringify(snap2.result ?? null));

    await page.evaluate(() => {
      [...document.querySelectorAll(".rail-item")]
        .find((el) => (el.textContent || "").trim().startsWith("fake-ws") && !(el.textContent || "").includes("fake-ws2"))?.click();
    });
    await sleep(1500);
    const report = await page.evaluate(() =>
      document.querySelector(".stream-report")?.textContent ?? "");
    check("S6 UI：切回 ws1 结果恢复", report.includes("mock 报告"), report.slice(0, 30));
  } finally {
    await page.close();
    await stopService(proc);
  }
}

(async () => {
  const browser = await puppeteer.launch({
    executablePath: EDGE, headless: "new",
    args: ["--no-sandbox", "--disable-gpu"],
  });
  try {
    await s1(browser);
    await s2(browser);
    await s3a(browser);
    await s3b_s4(browser);
    await s5(browser);
    await s6(browser);
      } catch (error) {
    console.error("SUITE ERROR:", error);
    results.push({ name: "套件异常终止", pass: false });
  } finally {
    await browser.close();
  }
  const failed = results.filter((r) => !r.pass);
  console.log(`\n${results.length - failed.length}/${results.length} passed`);
  process.exit(failed.length === 0 ? 0 : 1);
})();
