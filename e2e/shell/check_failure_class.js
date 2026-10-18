/* S1-C 失败分类呈现 E2E（真实鼠标/键盘）：
   F-1 provider 失败→自动重试→成功（自动重试痕迹）；F-2 预算耗尽失败（分类标签；无「建议重跑」）。
   用法：python e2e/shell/run_all.py --only failure_class（前置：cd apps/shell && npm run deploy）
   纪律：交互真实键鼠事件；断言锚定最终卡文案（中间轮事件仅供过程可见）。 */
const puppeteer = require("puppeteer-core");

const EDGE = process.env.EDGE_PATH ||
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
const SHELL_URL = process.env.SHELL_URL || "http://127.0.0.60:8833/next/";

const results = [];
function check(name, pass, detail) {
  results.push({ name, pass });
  console.log(`${pass ? "PASS" : "FAIL"}  ${name}${detail ? "  :: " + detail : ""}`);
}

(async () => {
  const browser = await puppeteer.launch({
    executablePath: EDGE, headless: "new",
    args: ["--no-sandbox", "--disable-gpu"],
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 900, deviceScaleFactor: 1 });
  const pageErrors = [];
  page.on("pageerror", (e) => pageErrors.push(e.message));
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const waitFor = async (fn, timeoutMs = 15000, stepMs = 150) => {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) { if (await fn()) return true; await sleep(stepMs); }
    return false;
  };

  await page.goto(SHELL_URL, { waitUntil: "domcontentloaded" });
  await sleep(1800);
  // 引导条：若显示先关闭（避免遮挡点击）
  const dismiss = await page.$('[data-st="onboard-dismiss"]');
  if (dismiss !== null) { await dismiss.click(); await sleep(200); }

  const submitTask = async (t) => {
    for (let attempt = 0; attempt < 2; attempt++) {
      const sel = await page.evaluate(() => {
        const vis = (s) => {
          const el = document.querySelector(s);
          return !!(el && el.offsetParent !== null);
        };
        return vis(".hero-text") ? ".hero-text" : ".cbox textarea";
      });
      await page.click(sel);
      await page.type(sel, t);
      await page.keyboard.press("Enter");
      const accepted = await waitFor(async () => await page.evaluate(() => {
        const cbox = document.querySelector(".cbox textarea");
        const hero = document.querySelector(".hero-text");
        const el = (cbox && cbox.offsetParent !== null) ? cbox : hero;
        return !el || el.value === "";
      }), 1500);
      if (accepted) return true;
    }
    return false;
  };

  const unitStatus = async (unit) => await page.evaluate((u) => {
    const card = document.querySelector(`[data-st="unit:${u}"]`);
    return card ? (card.dataset.status || "") : "";
  }, unit);
  const stateText = async (unit) => await page.evaluate((u) => {
    const card = document.querySelector(`[data-st="unit:${u}"]`);
    if (!card) return "";
    const el = card.querySelector(".frag-state");
    return el ? (el.textContent || "") : "";
  }, unit);

  const submitted = await submitTask("失败分类演示");
  check("任务提交（失败分类演示）", submitted, "");

  const done = await waitFor(async () =>
    (await unitStatus("F-1")) === "ok" && (await unitStatus("F-2")) === "failed");
  check("F-1 重试后成功 / F-2 终态失败（行状态到达）", done,
    `F-1=${await unitStatus("F-1")} F-2=${await unitStatus("F-2")}`);

  const t1 = await stateText("F-1");
  check("F-1 显示自动重试痕迹（已自动重试 1 次）",
    t1.includes("已自动重试 1 次"), t1);
  check("F-1 成功终态不残留「基础设施失败」", !t1.includes("基础设施失败"), t1);

  const t2 = await stateText("F-2");
  check("F-2 显示预算耗尽分类（未完成·预算耗尽）",
    t2.includes("预算耗尽"), t2);
  check("F-2 非 provider 类 → 无「建议重跑」提示",
    !t2.includes("建议重跑"), t2);

  check("无 pageerror", pageErrors.length === 0, pageErrors.join("; "));

  const failed = results.filter((r) => !r.pass);
  console.log(`\n== S1-C 失败分类：${results.length - failed.length}/${results.length} PASS ==`);
  await browser.close();
  process.exit(failed.length === 0 ? 0 : 1);
})().catch((err) => { console.error("FATAL", err); process.exit(2); });
