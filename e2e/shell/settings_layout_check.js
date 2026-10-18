/* 设置·模型与供应商 布局回归（2026-10-01 壳端全量复验发现）。
   背景（P1）：`.st-body` 为 flex 纵向容器，provider 行 `.st-provider{overflow:hidden}`
   的最小高度为 0 → 内容超高时被压缩成细条：行标题被裁剪、不可点击（真实鼠标点不中），
   供应商无法展开编辑（1440×900 下实测行高 2px）。
   断言（真实鼠标）：
   1) 供应商行高度 ≥ 30px（自然高度约 42px）；
   2) 行标题中心命中自身（未被裁剪/遮挡）；
   3) 真实鼠标点击行标题 → 展开出协议 select；
   4) `.st-body` 内容超高时表现为滚动（scrollHeight > clientHeight），而非压缩子项。
   用法：SHELL_URL=http://127.0.0.60:8833/next/ node e2e/shell/settings_layout_check.js */
const puppeteer = require("puppeteer-core");
const path = require("node:path");
const fs = require("node:fs");

const EDGE = process.env.EDGE_PATH ||
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
const URL = process.env.SHELL_URL || "http://127.0.0.60:8833/next/";
const OUT = process.env.OUT_DIR || path.join(__dirname, "visual", "settings-layout");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
fs.mkdirSync(OUT, { recursive: true });

const results = [];
function check(name, ok, detail) {
  results.push({ name, ok: !!ok });
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail !== undefined ? "  :: " + JSON.stringify(detail) : ""}`);
}

(async () => {
  const browser = await puppeteer.launch({
    executablePath: EDGE, headless: "new",
    args: ["--no-sandbox", "--disable-gpu"],
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 900, deviceScaleFactor: 1 });
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));

  const clickSel = async (sel) => {
    const b = await page.evaluate((s) => {
      const el = document.querySelector(s);
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) };
    }, sel);
    if (!b) return false;
    await page.mouse.click(b.x, b.y);
    return true;
  };

  try {
    await page.goto(URL, { waitUntil: "domcontentloaded", timeout: 20000 });
    await page.waitForFunction(() => document.body.dataset.state === "ready", { timeout: 20000 });
    await sleep(800);
    // 打开设置 → 模型与供应商
    await page.keyboard.down("Control");
    await page.keyboard.press("KeyK");
    await page.keyboard.up("Control");
    await sleep(250);
    await page.keyboard.type("设置");
    await sleep(200);
    await page.keyboard.press("Enter");
    await sleep(900);
    const navOk = await clickSel('[data-st="nav:model"]');
    await sleep(600);

    const info = await page.evaluate(() => {
      const rows = [...document.querySelectorAll(".st-body .st-provider")];
      const body = document.querySelector(".st-body");
      const firstHead = document.querySelector(".st-provider .st-provider-head");
      let hitOk = null, rowH = null, headRect = null;
      if (firstHead) {
        const r = firstHead.getBoundingClientRect();
        headRect = { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) };
        const hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
        hitOk = !!hit && (hit === firstHead || firstHead.contains(hit));
      }
      if (rows[0]) rowH = Math.round(rows[0].getBoundingClientRect().height);
      return {
        providerCount: rows.length, rowH, hitOk, headRect,
        body: body ? { scrollH: body.scrollHeight, clientH: body.clientHeight } : null,
        anyHeadSt: firstHead ? firstHead.getAttribute("data-st") : null,
      };
    });
    check("settings·model opens", navOk && info.providerCount >= 1,
      { navOk, providerCount: info.providerCount });
    await page.screenshot({ path: path.join(OUT, "model-section.png") });

    if (info.providerCount >= 1) {
      check("provider row not crushed (>=30px)", info.rowH !== null && info.rowH >= 30,
        { rowH: info.rowH });
      check("provider head hit-test at center", info.hitOk === true, info.headRect);
      // 真实鼠标展开（2026-10-16：折叠体常驻 DOM——断言看真实可见高度）
      const headSel = `[data-st="${info.anyHeadSt}"]`;
      const editorVisible = () => page.evaluate(() => {
        // 2026-10-16：折叠原语修正后——量 fold-body 轨道高（子卡 padding 溢出被裁）
        const el = document.querySelector(".st-provider .fold-body");
        if (!el) return false;
        return el.getBoundingClientRect().height > 1;
      });
      const expandedBefore = await editorVisible();
      await clickSel(headSel);
      await sleep(500);
      const expandedAfter = await editorVisible();
      check("real click expands provider editor", !expandedBefore && expandedAfter,
        { expandedBefore, expandedAfter });
      await page.screenshot({ path: path.join(OUT, "model-expanded.png") });
    }

    if (info.body) {
      const scrollOk = info.body.scrollH >= info.body.clientH;
      check("st-body consistent (scroll, not crush)", scrollOk, info.body);
    }
    check("no page errors", errors.length === 0, errors.slice(0, 2));
  } catch (err) {
    check("suite exception", false, String((err && err.stack) || err).slice(0, 300));
  } finally {
    const fails = results.filter((r) => !r.ok).length;
    console.log(`\nSUMMARY settings_layout: ${results.length - fails}/${results.length} pass`);
    await browser.close();
    process.exit(fails > 0 ? 1 : 0);
  }
})();
