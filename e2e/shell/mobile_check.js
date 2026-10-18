/* 移动端适配断言（O5 T4-A · 2026-10-17）。
   真实触控（hasTouch）+ 390×844；假引擎 8833（run_all 前 restart 零态）。
   断言：无水平溢出 / composer 在视口内 / viewport-fit=cover / 触控目标 ≥44px /
   安全区（--safe-top/bottom 注入 47/34 后内容不被遮挡）/ 无页面脚本错误。 */
const puppeteer = require("puppeteer-core");
const path = require("node:path");
const fs = require("node:fs");

const EDGE = process.env.EDGE_PATH ||
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
const URL = process.env.SHELL_URL || "http://127.0.0.60:8833/next/";
const OUT = process.env.OUT_DIR || path.join(__dirname, "visual", "mobile");
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
  await page.setCacheEnabled(false);
  await page.setViewport({ width: 390, height: 844, deviceScaleFactor: 2,
                           isMobile: true, hasTouch: true });
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(URL, { waitUntil: "networkidle2", timeout: 25000 });
  await sleep(1200);

  // 准备态（导航用合成点击——非被测交互）：进工作区 → 新会话
  await page.evaluate(async () => {
    const list = await (await fetch("/api/v1/workspaces")).json();
    const ws = list.workspaces.find((w) => w.name === "fake-ws")
      ?? list.workspaces[0];
    document.querySelector(`[data-st="rail:${ws.id}"]`)?.click();
  });
  await sleep(700);
  await page.evaluate(() => {
    document.querySelector('[data-st="rail-new-session"]')?.click();
  });
  await sleep(700);

  // 触控目标（发送前测：hero 在场）
  const targets = await page.evaluate(() => {
    const sels = ['[data-st="rail-new-session"]', '[data-st="hero-send"]'];
    const out = {};
    for (const s of sels) {
      const el = document.querySelector(s);
      if (el) {
        const r = el.getBoundingClientRect();
        out[s] = { w: Math.round(r.width), h: Math.round(r.height) };
      }
    }
    return out;
  });
  const small = Object.entries(targets)
    .filter(([, v]) => v.h < 44).map(([k, v]) => `${k}=${v.h}px`);
  check("5 触控目标 ≥44px（抽样）", small.length === 0, small);

  // 真实触控：输入 + 发送
  await page.tap(".hero-text");
  await page.type(".hero-text", "移动端适配冒烟");
  await page.tap('[data-st="hero-send"]');
  await sleep(1800);

  const layout = await page.evaluate(() => {
    const rect = (s) => {
      const el = document.querySelector(s);
      return el ? el.getBoundingClientRect().toJSON() : null;
    };
    return {
      docW: document.documentElement.scrollWidth,
      innerW: window.innerWidth, innerH: window.innerHeight,
      meta: document.querySelector('meta[name="viewport"]')?.content || "",
      composer: rect(".app-composer-slot"),
      center: rect(".app-center"),
      dock: rect(".app-dock-slot"),
    };
  });
  check("1 无水平溢出", layout.docW <= layout.innerW + 1,
        { docW: layout.docW, innerW: layout.innerW });
  check("2 主内容列宽 ≥300px（390 视口）",
        !!layout.center && layout.center.width >= 300, layout.center);
  check("3 composer 在视口内（宽 ≥240）",
        !!layout.composer && layout.composer.width >= 240
          && layout.composer.bottom <= layout.innerH + 0.5
          && layout.composer.top >= 0, layout.composer);
  check("4 viewport-fit=cover", /viewport-fit=cover/.test(layout.meta),
        layout.meta);
  check("8 dock 默认不压主内容",
        !!layout.dock && layout.dock.left >= layout.innerW - 60, layout.dock);

  // （触控目标已在发送前测——单一测量点）


  // 安全区接缝：--safe-* 注入（生产由 env(safe-area-inset-*) 供给）
  const sa = await page.evaluate(() => {
    document.documentElement.style.setProperty("--safe-top", "47px");
    document.documentElement.style.setProperty("--safe-bottom", "34px");
    const rect = (s) => {
      const el = document.querySelector(s);
      return el ? el.getBoundingClientRect().toJSON() : null;
    };
    return { topbar: rect(".app-topbar"),
             composer: rect(".app-composer-slot"),
             innerH: window.innerHeight };
  });
  check("6 safe-area：顶栏不压刘海",
        !!sa.topbar && sa.topbar.top >= 46.5, sa.topbar);
  check("7 safe-area：composer 不压手势条（宽 ≥240）",
        !!sa.composer && sa.composer.width >= 240
          && sa.composer.bottom <= sa.innerH - 33.5, sa.composer);

  await page.screenshot({ path: path.join(OUT, "mobile-390x844.png") });
  check("9 无页面脚本错误", errors.length === 0, errors.slice(0, 3));

  await browser.close();
  const failed = results.filter((r) => !r.ok);
  console.log(`\n结果：${results.length - failed.length}/${results.length}`);
  process.exit(failed.length === 0 ? 0 : 1);
})().catch((err) => {
  console.error("E2E 异常：", err);
  process.exit(1);
});
