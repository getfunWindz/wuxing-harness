/* G1 对话分支 E2E（夹具模式默认；真实鼠标点击——hit-test 纪律）。
   用法：python e2e/shell/restart_fixture.py
        SHELL_URL=http://127.0.0.60:8833/next/ node e2e/shell/g1_branch_check.js
   可选 env：WS_PATH（默认夹具 fake-ws）/ SESSION（默认 conversation-1710000100.jsonl，
   含 round 行的种子会话）/ WS_ID（缺省经 API 查询）。 */
const puppeteer = require("puppeteer-core");
const fs = require("node:fs");
const path = require("node:path");

const EDGE = process.env.EDGE_PATH ||
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
const SHELL_URL = process.env.SHELL_URL || "http://127.0.0.60:8833/next/";
const HOST = new URL(SHELL_URL).origin;
let WS_ID = process.env.WS_ID || "";
const WS_PATH = process.env.WS_PATH || path.join(__dirname, "fake-ws");
const SESSION = process.env.SESSION || "conversation-1710000100.jsonl";
const OUT = process.env.OUT_DIR || path.join(__dirname, "visual", "g1-branch");
fs.mkdirSync(OUT, { recursive: true });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function clickSt(page, st, { optional = false, timeout = 15000 } = {}) {
  const sel = `[data-st="${st}"]`;
  try {
    await page.waitForSelector(sel, { timeout });
  } catch (e) {
    if (optional) return false;
    throw e;
  }
  const el = await page.$(sel);
  const box = await el.boundingBox();
  await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
  return true;
}

(async () => {
  const results = [];
  const ok = (name, cond) => {
    results.push([name, !!cond]);
    console.log(`${cond ? "PASS" : "FAIL"} ${name}`);
  };
  const before = fs.readdirSync(path.join(WS_PATH, ".wuxing"))
    .filter((f) => /^conversation-.*\.jsonl$/.test(f)).length;

  if (!WS_ID) {
    const list = await fetch(`${HOST}/api/v1/workspaces`).then((r) => r.json());
    const ws = (list.workspaces || []).find((w) =>
      String(w.path || "").replace(/\\/g, "/").endsWith("/fake-ws"));
    WS_ID = ws ? ws.id : "";
  }
  if (!WS_ID) {
    console.error("找不到夹具工作区（WS_ID 未解析）——先运行 restart_fixture.py");
    process.exit(2);
  }

  const browser = await puppeteer.launch({
    executablePath: EDGE, headless: "new",
  });
  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 1440, height: 900 });
    await page.goto(SHELL_URL, { waitUntil: "networkidle2" });
    await sleep(1000);

    ok("工作区行可见", await clickSt(page, `rail:${WS_ID}`));
    await sleep(1200);

    ok("会话行可见", await clickSt(page, `rail-session:${SESSION}`));
    await sleep(1200);

    ok("历史用户消息含「分支」动作",
       await clickSt(page, "chat-branch", { timeout: 8000 }));
    await sleep(400);
    ok("分支弹层出现",
       await page.$('[data-st="branch-dialog"]') !== null);
    await page.screenshot({ path: path.join(OUT, "dialog.png") });

    ok("默认选项存在（重做/机械）",
       await page.$eval('input[name="branch-mode"][value="redo"][checked]',
                        () => true).catch(() => false) &&
       await page.$eval('input[name="branch-summary"][value="mech"][checked]',
                        () => true).catch(() => false));
    ok("创建按钮可见", await clickSt(page, "branch-ok"));
    // 等待弹层关闭 + 新会话徽标出现
    await page.waitForFunction(
      () => document.querySelector('[data-st="branch-dialog"]') === null,
      { timeout: 15000 });
    await sleep(1500);
    const badge = await page.$('[data-st^="rail-branch:"]');
    ok("新会话血缘徽标出现", badge !== null);
    await page.screenshot({ path: path.join(OUT, "after.png") });

    const files = fs.readdirSync(path.join(WS_PATH, ".wuxing"))
      .filter((f) => /^conversation-.*\.jsonl$/.test(f));
    ok("新会话文件落盘（fs 双证）", files.length === before + 1);
    let branchRow = null;
    for (const f of files) {
      for (const line of fs.readFileSync(path.join(WS_PATH, ".wuxing", f),
                                         "utf-8").split("\n")) {
        if (!line.trim()) continue;
        try {
          const row = JSON.parse(line);
          if (row.type === "branch" && row.mode === "redo") {
            branchRow = { file: f, ...row };
          }
        } catch { /* 破损行 */ }
      }
    }
    ok("承接行落盘（redo/mech）",
       branchRow !== null && branchRow.summary_mode === "mech");
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
