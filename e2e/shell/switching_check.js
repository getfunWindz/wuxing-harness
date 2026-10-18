/* Wave-2 T5：切换回归 E2E 套件（假引擎夹具 · 真实鼠标 · 超时断言）。
 *
 * 用例（用户裁决 2026-10-01——切换修复 T1-T4 的回归护栏）：
 *  1) 新建会话→点已有会话→显示会话流（hero 隐藏、rail-session active）——Bug#1
 *  2) 点空白会话→不弹 hero；输入区可用——Bug#3
 *  3) 提交建会话→不闪初始页（hero 保持隐藏）——Bug#2
 *  4) hero 隐藏→切工作区→回新建：placeholder 可达（几何断言 height≥44）——Bug#4
 *  5) 快速连点 A/B/A：最终显示 A、无旧内容串台——在途响应丢弃
 *  6) 刷新页面→重选工作区→历史渲染正常——smoke
 *
 * 用法：python e2e/shell/restart_fixture.py
 *      SHELL_URL=http://127.0.0.60:8833/next/ node e2e/shell/switching_check.js
 */
const puppeteer = require("puppeteer-core");
const fs = require("node:fs");
const path = require("node:path");

const EDGE = process.env.EDGE_PATH ||
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
const SHELL_URL = process.env.SHELL_URL || "http://127.0.0.60:8833/next/";
const HOST = new URL(SHELL_URL).origin;
const WS_PATH = process.env.WS_PATH || path.join(__dirname, "fake-ws");
const WS2_PATH = process.env.WS2_PATH || path.join(__dirname, "fake-ws2");
const OUT = process.env.OUT_DIR || path.join(__dirname, "visual", "switching");
fs.mkdirSync(OUT, { recursive: true });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const SESSION_A = "conversation-1710000100.jsonl";   // 「线性示例任务」
const SESSION_B = "conversation-1710000300.jsonl";   // 「长文档演示内容…」
const SESSION_EMPTY = "conversation-e2e-empty.jsonl"; // 运行期生成（空会话）

async function heroVisible(page) {
  return page.evaluate(() => {
    const el = document.querySelector(".hero");
    return !!(el && el.offsetParent !== null);
  });
}

(async () => {
  const results = [];
  const ok = (name, cond) => {
    results.push([name, !!cond]);
    console.log(`${cond ? "PASS" : "FAIL"} ${name}`);
  };

  // 运行期生成空会话（零轮次文件——夹具自管目录，非用户工作区）
  fs.mkdirSync(path.join(WS_PATH, ".wuxing"), { recursive: true });
  fs.writeFileSync(path.join(WS_PATH, ".wuxing", SESSION_EMPTY), "");

  // 解析两个工作区 id
  const list = await fetch(`${HOST}/api/v1/workspaces`).then((r) => r.json());
  const wsOf = (suffix) => ((list.workspaces || []).find((w) =>
    String(w.path || "").replace(/\\/g, "/").endsWith(suffix)) || {}).id || "";
  const WS_ID = process.env.WS_ID || wsOf("/fake-ws");
  const WS2_ID = process.env.WS2_ID || wsOf("/fake-ws2");
  if (!WS_ID) {
    console.error("找不到夹具工作区——先运行 restart_fixture.py");
    process.exit(2);
  }

  const browser = await puppeteer.launch({
    executablePath: EDGE, headless: "new",
  });
  const failedSel = async (page, st) => {
    // 真实鼠标点击（hit-test 纪律）；boot 竞态：等 app ready 后再断言
    await page.waitForFunction(() => document.body.dataset.state === "ready",
      { timeout: 10000 }).catch(() => { /* 已就绪/超时交由下方选择器等待 */ });
    await page.waitForSelector(`[data-st="${st}"]`, { timeout: 20000 });
    const el = await page.$(`[data-st="${st}"]`);
    const box = await el.boundingBox();
    if (!box) return false;
    await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
    return true;
  };
  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 1440, height: 900 });
    await page.goto(SHELL_URL, { waitUntil: "networkidle2" });
    // boot 就绪（全量连跑偶发：rail 行超时——先等 app ready 再操作）
    await page.waitForFunction(() => document.body.dataset.state === "ready",
      { timeout: 20000 }).catch(() => { /* 回退固定等待 */ });
    await sleep(1200);

    // —— 用例 1：点已有会话 → 会话流显示（hero 隐藏） ——
    await failedSel(page, `rail:${WS_ID}`);
    await sleep(1300);
    await failedSel(page, `rail-session:${SESSION_A}`);
    await sleep(1600);
    const s1 = await page.evaluate(() => ({
      hero: (() => { const el = document.querySelector(".hero");
        return !!(el && el.offsetParent !== null); })(),
      active: document.querySelector(".rail-session.active")?.getAttribute("data-st") || "",
      users: [...document.querySelectorAll(".chat-user .chat-text")]
        .map((e) => e.textContent || "").join("|"),
    }));
    ok("1a 选中会话不弹 hero（Bug#1）", !s1.hero);
    ok("1b 会话行 active 正确", s1.active === `rail-session:${SESSION_A}`);
    ok("1c 会话流历史渲染", s1.users.includes("线性示例任务"));

    // —— 用例 2：点空白会话 → 不弹 hero；输入区可用 ——
    await failedSel(page, `rail-session:${SESSION_EMPTY}`);
    await sleep(1600);
    const s2 = await page.evaluate(() => ({
      hero: (() => { const el = document.querySelector(".hero");
        return !!(el && el.offsetParent !== null); })(),
      composer: (() => { const el = document.querySelector(".cbox textarea");
        return !!(el && el.offsetParent !== null); })(),
      skeleton: (document.querySelector('[data-st="session-loading"]')
        ?.textContent || "").trim(),
    }));
    ok("2a 空会话不弹 hero（Bug#3）", !s2.hero);
    ok("2b 输入区可用", s2.composer);
    ok("2c 空会话骨架提示", s2.skeleton.includes("空会话"));
    await page.screenshot({ path: path.join(OUT, "empty-session.png") });

    // —— 用例 3：提交建会话 → 不闪初始页 ——
    await failedSel(page, "rail-new-session");
    await sleep(700);
    ok("3a 新建会话回到 hero", await heroVisible(page));
    await page.click(".hero-text");
    await page.type(".hero-text", "T5 切换回归任务（夹具）", { delay: 2 });
    await page.keyboard.press("Enter");
    let flashed = false;
    for (let i = 0; i < 8; i += 1) {
      await sleep(160);
      if (await heroVisible(page)) { flashed = true; break; }
    }
    ok("3b 提交后不闪初始页（Bug#2）", !flashed);
    // 等假引擎任务收口（避免与后续用例的会话切换互踩）
    await page.waitForFunction(() => {
      const meta = document.querySelector(".stream-meta");
      return !!meta && /· 完成|· 失败|· 已取消/.test(meta.textContent || "");
    }, { timeout: 90000 }).catch(() => { /* 超时不判失败（用例 3 只关心不闪）*/ });

    // —— 用例 4：切工作区 → 回新建：placeholder 几何可达 ——
    if (WS2_ID) {
      await failedSel(page, `rail:${WS2_ID}`);
      await sleep(1500);
    }
    await failedSel(page, `rail:${WS_ID}`);
    await sleep(1500);
    await failedSel(page, "rail-new-session");
    await sleep(900);
    const s4 = await page.evaluate(() => {
      const ta = document.querySelector(".hero-text");
      const r = ta?.getBoundingClientRect();
      return { h: r ? Math.round(r.height) : 0,
               placeholder: ta?.getAttribute("placeholder") || "" };
    });
    ok("4a hero 高度 ≥44（Bug#4）", s4.h >= 44);
    ok("4b placeholder 存在", s4.placeholder.length > 0);

    // —— 用例 5：快速连点 A/B/A ——
    await failedSel(page, `rail-session:${SESSION_A}`);
    await sleep(50);
    await failedSel(page, `rail-session:${SESSION_B}`);
    await sleep(50);
    await failedSel(page, `rail-session:${SESSION_A}`);
    await sleep(2200);
    const s5 = await page.evaluate(() => ({
      active: document.querySelector(".rail-session.active")?.getAttribute("data-st") || "",
      users: [...document.querySelectorAll(".chat-user .chat-text")]
        .map((e) => e.textContent || "").join("|"),
    }));
    ok("5a 连点后最终选中 A", s5.active === `rail-session:${SESSION_A}`);
    ok("5b 无旧会话内容串台", !s5.users.includes("长文档演示内容")
       && s5.users.includes("线性示例任务"));

    // —— 用例 6：刷新 → 重选工作区 → 历史渲染 ——
    await page.reload({ waitUntil: "networkidle2" });
    await sleep(1600);
    await failedSel(page, `rail:${WS_ID}`);
    await sleep(1500);
    await failedSel(page, `rail-session:${SESSION_A}`);
    await sleep(1600);
    const s6 = await page.evaluate(() =>
      [...document.querySelectorAll(".chat-user .chat-text")]
        .map((e) => e.textContent || "").join("|"));
    ok("6 刷新后历史渲染正常", s6.includes("线性示例任务"));
    await page.screenshot({ path: path.join(OUT, "after-reload.png") });
  } finally {
    await browser.close();
  }
  const failed = results.filter(([, c]) => !c).length;
  console.log(`\n结果：${results.length - failed}/${results.length}`);
  process.exit(failed === 0 ? 0 : 1);
})().catch((e) => {
  console.error("E2E 异常：", e);
  process.exit(2);
});
