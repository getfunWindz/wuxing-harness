/* UI-1~4 回归断言（2026-09-27 前端全角落审查修复的 E2E 补录 · U14 2026-09-30）。
   覆盖：
     UI-1 会话列表先上屏（标题延迟 1500ms 不得阻塞；随后后台补齐）
     UI-2 tickets.jsonl 幽灵会话排除（列表不含 tickets；普通会话行控制）
     UI-3 搜索结果点击打开目标会话（中栏渲染 + 网络请求双证）
     UI-4 跨工作区陈旧上下文防护（新工作区请求不得携带旧会话名）
   用法：node e2e/shell/ui_fixes_check.js
   自管理夹具：spawn serve_fake.py 8834（FAKE_TITLE_DELAY_MS=1500；零态自动重建）。
   前置：cd apps/shell && npm run deploy。
   全过退出 0；任一失败退出 1。交互断言用真实鼠标事件（page.mouse）——合成 click
   绕过命中测试（2026-09-15 教训，不得作为可用性证据）。 */
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");
const puppeteer = require("puppeteer-core");

const EDGE = process.env.EDGE_PATH ||
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
const PORT = Number(process.env.PORT || 8834);
const SHELL_URL = process.env.SHELL_URL || `http://127.0.0.60:${PORT}/next/`;
const HOST = new URL(SHELL_URL).origin;
const PY = process.env.PYTHON || "python";
const SERVE = path.join(__dirname, "serve_fake.py");
const WS = path.join(__dirname, "fake-ws");
const TITLE_DELAY_MS = Number(process.env.FAKE_TITLE_DELAY_MS || 1500);

const FAKE_WS_SESSIONS = [
  "conversation-1710000000.jsonl",
  "conversation-1710000100.jsonl",
  "conversation-1710000300.jsonl",
];

const results = [];
function check(name, pass, detail) {
  results.push({ name, pass: !!pass });
  console.log(`${pass ? "PASS" : "FAIL"}  ${name}${detail ? "  :: " + detail : ""}`);
}

function startFixture() {
  const proc = spawn(PY, [SERVE, String(PORT)], {
    cwd: __dirname,
    env: { ...process.env, FAKE_TITLE_DELAY_MS: String(TITLE_DELAY_MS) },
    stdio: ["ignore", "pipe", "pipe"],
  });
  const started = new Promise((resolve, reject) => {
    const timer = setTimeout(
      () => reject(new Error("fixture start timeout")), 20000);
    proc.stdout.on("data", (chunk) => {
      if (String(chunk).includes("URL ")) { clearTimeout(timer); resolve(proc); }
    });
    proc.stderr.on("data", (c) => process.stderr.write(String(c)));
    proc.on("exit", () => clearTimeout(timer));
  });
  return { proc, started };
}

(async () => {
  const { proc, started } = startFixture();
  try {
    await started;
  } catch (e) {
    console.error("夹具启动失败：", e.message);
    proc.kill();
    process.exit(2);
  }

  const browser = await puppeteer.launch({
    executablePath: EDGE, headless: "new",
    args: ["--no-sandbox", "--disable-gpu"],
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 900, deviceScaleFactor: 1 });
  const requests = [];
  page.on("request", (r) => requests.push({ url: r.url(), ts: Date.now() }));
  page.on("pageerror", (e) => console.log("PAGEERROR:", e.message));

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const waitFor = async (fn, timeoutMs = 10000, stepMs = 120) => {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      if (await fn()) return true;
      await sleep(stepMs);
    }
    return false;
  };
  const visible = (sel) => page.evaluate((s) => {
    const el = document.querySelector(s);
    if (!el || !el.isConnected) return false;
    const cs = getComputedStyle(el);
    if (cs.display === "none" || cs.visibility === "hidden") return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  }, sel);
  const probeBox = (selector) => page.evaluate((sel) => {
    const el = document.querySelector(sel);
    if (!el) return null;
    el.scrollIntoView({ block: "center" });
    const r = el.getBoundingClientRect();
    const x = Math.round(r.x + r.width / 2), y = Math.round(r.y + r.height / 2);
    const hit = document.elementFromPoint(x, y);
    return {
      x, y,
      ok: !!hit && (hit === el || el.contains(hit)),
      hit: hit ? `${hit.tagName}|${hit.getAttribute("data-st") || ""}` : "null",
    };
  }, selector);
  const mouseClick = async (selector) => {
    const box = await probeBox(selector);
    if (!box || !box.ok) {
      console.log(`WARN mouseClick(${selector}) 未命中：${box ? box.hit : "element-gone"}`);
      return false;
    }
    await page.mouse.move(box.x, box.y);
    await sleep(60);
    await page.mouse.click(box.x, box.y);
    return true;
  };
  const clickByText = async (selector, text) => {
    const box = await page.evaluate((sel, want) => {
      const el = [...document.querySelectorAll(sel)].find((e) =>
        (e.textContent || "").includes(want));
      if (!el) return null;
      el.scrollIntoView({ block: "center" });
      const r = el.getBoundingClientRect();
      return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2),
               hit: (() => {
                 const t = document.elementFromPoint(
                   Math.round(r.x + r.width / 2), Math.round(r.y + r.height / 2));
                 return !!t && (t === el || el.contains(t));
               })() };
    }, selector, text);
    if (!box || !box.hit) {
      console.log(`WARN clickByText(${selector}, ${text}) 未命中`);
      return false;
    }
    await page.mouse.move(box.x, box.y);
    await sleep(60);
    await page.mouse.click(box.x, box.y);
    return true;
  };
  const railRows = () => page.evaluate(() =>
    [...document.querySelectorAll('[data-st^="rail-session:"]')]
      .map((e) => e.textContent || ""));
  const wsApi = () => fetch(`${HOST}/api/v1/workspaces`).then((r) => r.json());

  try {
    // ============ UI-1 会话列表先上屏（标题延迟不阻塞） ============
    await page.goto(SHELL_URL, { waitUntil: "domcontentloaded" });
    const ready = await waitFor(() => page.evaluate(
      () => document.body.dataset.state === "ready"), 15000, 50);
    const tReady = Date.now();
    const rowsUp = await waitFor(async () => (await railRows()).length >= 1, 1200, 50);
    const rowsMs = Date.now() - tReady;
    const titlesAtRows = (await railRows())
      .some((t) => t.includes("变更摘要会话") || t.includes("并行示例会话"));
    check("壳就绪（data-state=ready）", ready);
    check(`UI-1 列表先上屏（≤1200ms；标题延迟 ${TITLE_DELAY_MS}ms）`,
      rowsUp && rowsMs <= 1200, `rowsMs=${rowsMs}`);
    check("UI-1 行就位时标题仍未到达（未被标题生成阻塞）", rowsUp && !titlesAtRows,
      `titlesAtRows=${titlesAtRows}`);
    const backfilled = await waitFor(async () => (await railRows())
      .some((t) => t.includes("变更摘要会话")), 8000, 200);
    check("UI-1 标题后台补齐（控制）", backfilled);

    // ============ UI-2 tickets.jsonl 幽灵会话排除 ============
    fs.writeFileSync(path.join(WS, ".wuxing", "tickets.jsonl"),
      JSON.stringify({ id: "T-1", title: "幽灵票据", status: "ready" }) + "\n",
      "utf-8");
    await page.goto(SHELL_URL, { waitUntil: "domcontentloaded" });
    await waitFor(() => page.evaluate(
      () => document.body.dataset.state === "ready"), 15000, 50);
    await waitFor(async () => (await railRows()).length >= 3, 8000, 150);
    const rows2 = await railRows();
    check("UI-2 列表不含 tickets（内部文件排除）",
      !rows2.some((t) => t.includes("tickets")), rows2.join(" | ").slice(0, 200));
    check("UI-2 普通会话行在场（控制）",
      rows2.some((t) => t.includes("conversation-")), `rows=${rows2.length}`);

    // ============ UI-3 搜索结果点击打开目标会话 ============
    const before3 = requests.length;
    check("UI-3 打开搜索浮层", await mouseClick('[data-st="rail-search"]'));
    await waitFor(() => visible('[data-st="search-input"]'), 5000);
    await mouseClick('[data-st="search-input"]');
    await page.type('[data-st="search-input"]', "并行", { delay: 30 });
    const hasItems = await waitFor(() => page.evaluate(
      () => document.querySelectorAll('[data-st^="search-item:"]').length > 0), 8000);
    check("UI-3 搜索出结果", hasItems);
    const idx = await page.evaluate(() => {
      const items = [...document.querySelectorAll('[data-st^="search-item:"]')];
      return items.findIndex((e) => (e.textContent || "").includes(".jsonl"));
    });
    check("UI-3 结果含会话行", idx >= 0, `idx=${idx}`);
    if (idx >= 0) {
      await mouseClick(`[data-st="search-item:${idx}"]`);
      const opened = await waitFor(() => page.evaluate(() =>
        (() => {
          const el = document.querySelector('[data-st="chat"]');
          const hero = document.querySelector(".hero");
          const chatVisible = !!(el && el.getBoundingClientRect().height > 0);
          const heroVisible = !!(hero && hero.offsetParent !== null);
          return chatVisible && !heroVisible;
        })()), 8000);
      const sessReq = requests.slice(before3)
        .some((r) => r.url.includes("/sessions/conversation-1710000100.jsonl"));
      check("UI-3 点击结果打开目标会话（渲染 + 网络双证）",
        opened && sessReq, `opened=${opened} sessReq=${sessReq}`);
    }

    // ============ UI-4 跨工作区陈旧上下文防护 ============
    const list = await wsApi();
    const id1 = (list.workspaces || []).find((w) => w.name === "fake-ws")?.id || "";
    const id2 = (list.workspaces || []).find((w) => w.name === "fake-ws2")?.id || "";
    check("UI-4 双工作区可寻（控制）", !!id1 && !!id2, `${id1} | ${id2}`);
    // 激活 dock 会话视图（上下文预览面板）——确保刷新链路被真实触发
    await mouseClick('[data-st="dock-tab:sessions"]');
    const preSwitch = await waitFor(() => requests.some(
      (r) => r.url.includes(`/workspaces/${id1}/context-previews`)), 8000);
    check("UI-4 dock 会话视图激活（切前预览请求在途·控制）", preSwitch);
    const mark = Date.now();
    check("UI-4 切换工作区（fake-ws → fake-ws2）",
      await clickByText(".rail-item", "fake-ws2"));
    const refreshed = await waitFor(() => requests.some(
      (r) => r.ts >= mark && r.url.includes(`/workspaces/${id2}/context-previews`)),
      8000, 150);
    check("UI-4 切换后新工作区上下文刷新（控制）", refreshed);
    const stale = requests.filter((r) => r.ts >= mark
      && r.url.includes(`/workspaces/${id2}/context-preview`)
      && FAKE_WS_SESSIONS.some((s) => r.url.includes(`session=${s}`)));
    check("UI-4 无跨工作区陈旧会话请求", stale.length === 0,
      stale.map((r) => r.url).join(" | ").slice(0, 200));
  } finally {
    await browser.close();
    proc.kill();
  }

  const failed = results.filter((r) => !r.pass).length;
  console.log(`\n结果：${results.length - failed}/${results.length}`);
  if (failed > 0) {
    console.log("失败：", results.filter((r) => !r.pass).map((r) => r.name).join(", "));
  }
  process.exit(failed === 0 ? 0 : 1);
})().catch((e) => {
  console.error("E2E 异常：", e);
  process.exit(2);
});
