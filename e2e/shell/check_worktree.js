/* E3-1/R5（T5）worktree 隔离运行 E2E：隔离开关（真实鼠标）→ 假引擎 run →
   Ready 卡（文件清单 + diff）→ 丢弃（确认对话框）/ 应用（回执 + 主检出生效）。
   用法：python e2e/shell/restart_fixture.py
        SHELL_URL=http://127.0.0.60:8833/next/ node e2e/shell/check_worktree.js
   前置：cd apps/shell && npm run deploy。
   夹具：任务文本「隔离演示」→ FakeEngine 在 workdir（隔离档=worktree）写 isolated-report.md。
   纪律：交互断言用真实鼠标事件（page.mouse）；丢弃走 window.confirm（自动接受）。 */
const fs = require("node:fs");
const path = require("node:path");
const puppeteer = require("puppeteer-core");

const EDGE = process.env.EDGE_PATH ||
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
const SHELL_URL = process.env.SHELL_URL || "http://127.0.0.60:8833/next/";
const WS = path.join(__dirname, "fake-ws");
const MAIN_FILE = path.join(WS, "isolated-report.md");
const WT_ROOT = path.join(WS, ".wuxing", "worktrees");

const results = [];
function check(name, pass, detail) {
  results.push({ name, pass });
  console.log(`${pass ? "PASS" : "FAIL"}  ${name}${detail ? "  :: " + detail : ""}`);
}
const wtRunDirs = () => {
  try {
    return fs.readdirSync(WT_ROOT).filter((n) =>
      fs.statSync(path.join(WT_ROOT, n)).isDirectory());
  } catch (_e) { return []; }
};
const wtHasFile = () =>
  wtRunDirs().some((d) => fs.existsSync(path.join(WT_ROOT, d, "isolated-report.md")));

/** 清理残留（Windows：rmSync 对部分文件可静默不删——文件走 unlink + 校验重试）。 */
function rmIfExists(target, recursive = false) {
  for (let i = 0; i < 10; i++) {
    try {
      if (recursive) {
        fs.rmSync(target, { recursive: true, force: true });
      } else {
        fs.unlinkSync(target);
      }
    } catch (_e) { /* 重试 */ }
    if (!fs.existsSync(target)) return true;
    const wait = new Int32Array(new SharedArrayBuffer(4));
    Atomics.wait(wait, 0, 0, 200);
  }
  return !fs.existsSync(target);
}

(async () => {
  if (!rmIfExists(MAIN_FILE) || !rmIfExists(WT_ROOT, true)) {
    console.error("FATAL 状态清理失败（主检出/Worktree 残留——请先手动清理）");
    process.exit(2);
  }

  const browser = await puppeteer.launch({
    executablePath: EDGE, headless: "new",
    args: ["--no-sandbox", "--disable-gpu"],
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 900, deviceScaleFactor: 1 });
  page.on("dialog", (d) => { void d.accept(); });   // 丢弃确认自动接受
  const pageErrors = [];
  page.on("pageerror", (e) => pageErrors.push(e.message));

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const waitFor = async (fn, timeoutMs = 15000, stepMs = 150) => {
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
      stack: document.elementsFromPoint(x, y).slice(0, 5).map((e) =>
        `${e.tagName}.${e.className && String(e.className).slice(0, 30)}|${e.getAttribute("data-st") || ""}`),
    };
  }, selector);
  const mouseClick = async (selector, timeoutMs = 6000) => {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      const box = await probeBox(selector);
      if (box && box.ok) {
        await page.mouse.move(box.x, box.y);
        await sleep(60);
        await page.mouse.click(box.x, box.y);
        return true;
      }
      await sleep(150);   // 布局未定/暂时被遮挡——重探（启动期常见）
    }
    const box = await probeBox(selector);
    console.log(`WARN mouseClick(${selector}) 未命中：${box ? box.hit : "element-gone"}` +
      (box && box.stack ? ` stack=${JSON.stringify(box.stack)}` : ""));
    return false;
  };
  const clickUntil = async (selector, predicate, attempts = 3, waitMs = 8000) => {
    for (let i = 0; i < attempts; i++) {
      await mouseClick(selector);
      if (await waitFor(predicate, waitMs)) return true;
      if (i < attempts - 1) console.log(`WARN clickUntil(${selector}) 未生效——重试 ${i + 1}`);
    }
    return false;
  };
  const submitTask = async (t) => {
    const sel = await page.evaluate(() => {
      const vis = (s) => { const el = document.querySelector(s); return !!(el && el.offsetParent !== null); };
      return vis(".hero-text") ? ".hero-text" : ".cbox textarea";
    });
    await page.click(sel);
    await page.type(sel, t);
    await page.keyboard.press("Enter");
    return waitFor(async () => await page.evaluate(() => {
      const cbox = document.querySelector(".cbox textarea");
      const hero = document.querySelector(".hero-text");
      const el = (cbox && cbox.offsetParent !== null) ? cbox : hero;
      return !el || el.value === "";
    }), 1500);
  };

  await page.goto(SHELL_URL, { waitUntil: "domcontentloaded" });
  await sleep(1800);
  let active = await page.evaluate(() =>
    document.querySelector(".rail-item.active .rail-name")?.textContent || "");
  if (active.trim() === "") {
    await mouseClick(".rail-item");
    await sleep(900);
    active = await page.evaluate(() =>
      document.querySelector(".rail-item.active .rail-name")?.textContent || "");
  }
  check("worktree 前置：激活工作区", active.trim() !== "", active || "(无)");

  // 1) 隔离开关（真实鼠标）→ 开启态（零态在 hero，已建会话在 composer）
  const toggleSel = await page.evaluate(() => {
    const vis = (s) => { const el = document.querySelector(s); return !!(el && el.offsetParent !== null); };
    return vis('[data-st="hero-isolate"]') ? '[data-st="hero-isolate"]'
      : '[data-st="composer-isolate"]';
  });
  const toggled = await mouseClick(toggleSel);
  const on = await waitFor(async () => await page.evaluate((sel) =>
    document.querySelector(sel)?.dataset.on === "1", toggleSel), 3000);
  check("隔离开关开启（data-on=1）", toggled && on, toggleSel);

  // 2) 隔离 run → Ready 卡（文件清单 + diff）
  const submitted1 = await submitTask("隔离演示");
  const cardSeen = await waitFor(async () =>
    await visible('[data-st="worktree-card"]'), 20000);
  const fileSeen = await waitFor(async () =>
    await visible('[data-st="worktree-file:isolated-report.md"]'), 10000);
  const diffSeen = await waitFor(async () =>
    await visible('[data-st="worktree-diff"]'), 10000);
  check("隔离 run 完成 → Ready 卡（含文件清单与 diff）",
    submitted1 && cardSeen && fileSeen && diffSeen,
    JSON.stringify({ submitted1, cardSeen, fileSeen, diffSeen }));
  const hist1 = await page.evaluate(async () => {
    const list = await (await fetch("/api/v1/workspaces")).json();
    const ws = list.workspaces[0];
    const h = await (await fetch(`/api/v1/workspaces/${ws.id}/tasks/history`)).json();
    const row = (h.history || []).find((r) => String(r.task_text).includes("隔离演示"));
    return row ? { isolated: row.isolated, wt: row.worktree_path } : null;
  });
  check("应用前：主检出不落交付物 + worktree 内有交付物",
    !fs.existsSync(MAIN_FILE) && wtHasFile(),
    JSON.stringify({ main: fs.existsSync(MAIN_FILE), wt: wtHasFile(),
                     hist: hist1,
                     mainMtime: fs.existsSync(MAIN_FILE)
                       ? fs.statSync(MAIN_FILE).mtime.toISOString() : null }));

  // 3) 丢弃（确认对话框自动接受）→ 卡收束 + worktree 移除 + 主检出仍干净
  const discarded = await clickUntil('[data-st="worktree-discard"]',
    async () => await page.evaluate(() =>
      document.querySelector('[data-st="worktree-card"]')?.hidden === true
      || !document.querySelector('[data-st="worktree-card"]')));
  check("丢弃：卡收束 + worktree 移除 + 主检出零改动",
    discarded && wtRunDirs().length === 0 && !fs.existsSync(MAIN_FILE),
    JSON.stringify({ discarded, runs: wtRunDirs().length,
                     main: fs.existsSync(MAIN_FILE) }));

  // 4) 再跑一次 → 应用 → 回执 + 主检出生效 + worktree 保留（仍可丢弃）
  const submitted2 = await submitTask("隔离演示");
  const card2 = await waitFor(async () =>
    await visible('[data-st="worktree-file:isolated-report.md"]'), 20000);
  const applied = await clickUntil('[data-st="worktree-apply"]',
    async () => await visible('[data-st="worktree-notice"]'));
  const notice = await page.evaluate(() =>
    document.querySelector('[data-st="worktree-notice"]')?.textContent || "");
  check("应用：回执可见 + 主检出生效 + worktree 保留",
    submitted2 && card2 && applied && fs.existsSync(MAIN_FILE)
    && wtHasFile() && notice.includes("已应用"),
    JSON.stringify({ submitted2, card2, applied, main: fs.existsSync(MAIN_FILE),
                     wt: wtHasFile(), notice }));

  check("无 pageerror", pageErrors.length === 0, pageErrors.join("; "));

  const failed = results.filter((r) => !r.pass);
  console.log(`\n== worktree 隔离链：${results.length - failed.length}/${results.length} PASS ==`);
  await browser.close();
  process.exit(failed.length === 0 ? 0 : 1);
})().catch((err) => { console.error("FATAL", err); process.exit(2); });
