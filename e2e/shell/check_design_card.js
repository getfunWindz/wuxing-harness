/* 设计卡限定面积/开合入口 断言（2026-10-16 用户真机反馈回归）。
   真实鼠标；1440×900；假引擎 8833（run_all 前 restart 零态）。
   断言：长票据封顶（不挤压消息区/输入框）+ 显式开合按钮（真实鼠标）。
   压测手法：DOM 克隆票据行 15×（真实多轮设计会自然产生长列表；克隆只测布局约束）。 */
const puppeteer = require("puppeteer-core");
const path = require("node:path");
const fs = require("node:fs");

const EDGE = process.env.EDGE_PATH ||
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
const URL = process.env.SHELL_URL || "http://127.0.0.60:8833/next/";
const OUT = process.env.OUT_DIR || path.join(__dirname, "visual", "design_card");
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
  await page.setViewport({ width: 1440, height: 900, deviceScaleFactor: 1 });
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(URL, { waitUntil: "networkidle2", timeout: 25000 });
  await sleep(1500);

  // 打开 fake-ws 工作区 → 新会话 → 循迹 → 设计任务
  await page.evaluate(async () => {
    const list = await (await fetch("/api/v1/workspaces")).json();
    const ws = list.workspaces.find((w) => w.name === "fake-ws") ?? list.workspaces[0];
    const el = document.querySelector(`[data-st="rail:${ws.id}"]`);
    if (el) el.click();
  });
  await sleep(800);
  await page.click('[data-st="rail-new-session"]');
  await sleep(800);
  await page.click('[data-st="mode-chip"]');
  await sleep(300);
  await page.click('[data-st="mode-pick:theroad"]');
  await sleep(800);
  await page.click(".hero-text");
  await page.type(".hero-text", "设计一个发布工具");
  await page.click('[data-st="hero-send"]');
  for (let i = 0; i < 80; i++) {
    const ok = await page.evaluate(() => {
      const el = document.querySelector('[data-st="design-card"]');
      return !!el && !el.hidden && getComputedStyle(el).display !== "none";
    });
    if (ok) break;
    await sleep(250);
  }
  await sleep(800);

  const measure = () => page.evaluate(() => {
    const q = (s) => document.querySelector(s);
    const rect = (el) => (el ? el.getBoundingClientRect().toJSON() : null);
    const card = q('[data-st="design-card"]');
    const composer = q(".app-composer-slot");
    const stream = q(".app-stream-slot");
    const cr = rect(composer);
    return {
      card: rect(card),
      open: card ? card.classList.contains("open") : null,
      stream: rect(stream), composer: cr, vh: window.innerHeight,
      composerInViewport: !!cr && cr.bottom <= window.innerHeight + 0.5 && cr.top >= 0,
      badge: q('[data-st="design-pending-count"]')?.textContent || "",
      tickets: document.querySelectorAll('[data-st^="design-ticket:"]').length,
    };
  });

  const before = await measure();
  check("1 设计卡在场 + 待答徽标",
        before.card !== null && before.badge.includes("待答"), before.badge);

  // 布局压测：票据行克隆 15×（模拟真实长列表）
  await page.evaluate(() => {
    const holder = document.querySelector(".design-questions");
    if (!holder) return;
    const rows = Array.from(holder.querySelectorAll(".design-q"));
    for (let i = 0; i < 15; i++) rows.forEach((r) => holder.appendChild(r.cloneNode(true)));
  });
  await sleep(300);
  const stress = await measure();
  await page.screenshot({ path: path.join(OUT, "design-card-stress.png") });
  check("2 长票据：卡片封顶 ≤ 420",
        !!stress.card && stress.card.height <= 422, stress.card && stress.card.height);
  check("3 长票据：输入框仍在视口内", stress.composerInViewport === true, stress.composer);
  check("4 长票据：消息区 ≥ 200px",
        !!stress.stream && stress.stream.height >= 200, stress.stream && stress.stream.height);

  // 真实鼠标：显式开合按钮 → 收起
  const clickToggle = async () => {
    const box = await page.evaluate(() => {
      const el = document.querySelector('[data-st="design-fold-toggle"]');
      if (!el) return null;
      el.scrollIntoView({ block: "center" });
      const r = el.getBoundingClientRect();
      return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) };
    });
    if (!box) return false;
    await page.mouse.click(box.x, box.y);
    return true;
  };
  check("5 开合按钮在场", await page.evaluate(() =>
    !!document.querySelector('[data-st="design-fold-toggle"]')), "");
  await clickToggle();
  await sleep(400);
  const folded = await measure();
  await page.screenshot({ path: path.join(OUT, "design-card-folded.png") });
  check("6 收起后：卡片 ≤ 90px",
        !!folded.card && folded.card.height <= 90, folded.card && folded.card.height);
  check("7 收起后：输入框可见", folded.composerInViewport === true, folded.composer);

  check("8 无 pageerror", errors.length === 0, errors.slice(0, 2));

  const failed = results.filter((r) => !r.ok);
  console.log(`\n${failed.length === 0 ? "✔" : "✘"} design_card 断言 ` +
    `${results.length - failed.length}/${results.length}` +
    (failed.length ? "；失败：" + failed.map((f) => f.name).join("；") : ""));
  await browser.close();
  process.exit(failed.length === 0 && errors.length === 0 ? 0 : 1);
})().catch((e) => { console.error(e); process.exit(1); });
