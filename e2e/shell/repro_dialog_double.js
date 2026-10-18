/* Issue-B 复现：快速双击「新建工作区（资源管理器选文件夹）」→ 统计 dialog/pick 请求数。
   生产含义：未守卫时每次点击 = 一个系统文件夹对话框（第一个常被窗口挡住 →
   用户再点 → 两个对话框；第一个取消时又触发手输回退弹窗 =「选择无效」体感）。

   用法：python e2e/shell/serve_fake.py 8836
        SHELL_URL=http://127.0.0.60:8836/next/ node e2e/shell/repro_dialog_double.js
   期望：修复后 picks=1；未修复 picks>=2。 */
const puppeteer = require("puppeteer-core");

const EDGE = process.env.EDGE_PATH ||
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
const URL = process.env.SHELL_URL || "http://127.0.0.60:8836/next/";

(async () => {
  const browser = await puppeteer.launch({
    executablePath: EDGE, headless: "new",
    args: ["--no-sandbox", "--disable-gpu"],
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 900, deviceScaleFactor: 1 });
  let picks = 0;
  page.on("request", (req) => {
    if (req.url().includes("/api/v1/dialog/pick")) picks += 1;
  });
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  const probeBox = (selector) => page.evaluate((sel) => {
    const el = document.querySelector(sel);
    if (!el) return null;
    el.scrollIntoView({ block: "center" });
    const r = el.getBoundingClientRect();
    const x = Math.round(r.x + r.width / 2);
    const y = Math.round(r.y + r.height / 2);
    const hit = document.elementFromPoint(x, y);
    return { x, y, ok: !!hit && (hit === el || el.contains(hit)) };
  }, selector);

  const mouseClick = async (selector) => {
    const box = await probeBox(selector);
    if (!box || !box.ok) return false;
    await page.mouse.move(box.x, box.y);
    await sleep(40);
    await page.mouse.click(box.x, box.y);
    return true;
  };

  await page.goto(URL, { waitUntil: "networkidle2" });
  await sleep(900);

  // 第一次点击路径
  await mouseClick('[data-st="rail-add"]');
  await sleep(150);
  await mouseClick('[data-st="menu-new-ws"]');
  // 用户以为没反应 → 立刻再点一次（生产：第一个对话框可能被窗口挡住）
  await sleep(120);
  await mouseClick('[data-st="rail-add"]');
  await sleep(100);
  await mouseClick('[data-st="menu-new-ws"]');
  await sleep(2600);

  const typedOpen = await page.evaluate(() =>
    document.querySelector('.topbar-dialog [data-st="new-ws-path"]') !== null);
  console.log(`dialog/pick 请求数 = ${picks}`);
  console.log(`手输回退弹窗出现 = ${typedOpen}`);
  await browser.close();
  process.exit(0);
})();
