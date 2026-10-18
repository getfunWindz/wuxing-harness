/* E2-5（A10）提问工具 E2E：提问挂起（fail-closed）→ 选项/自由文本答复 →
   回执与落盘双证 → 单元续跑完成。
   用法：python e2e/shell/restart_fixture.py
        SHELL_URL=http://127.0.0.60:8833/next/ node e2e/shell/check_ask.js
   前置：cd apps/shell && npm run deploy。
   夹具：任务文本「提问演示」→ UnitNeedsAnswer（2 题）；answer_unit 回执落盘 ask_log.json。
   纪律：交互断言用真实鼠标事件（page.mouse）——合成 click 绕过命中测试。 */
const fs = require("node:fs");
const path = require("node:path");
const puppeteer = require("puppeteer-core");

const EDGE = process.env.EDGE_PATH ||
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
const SHELL_URL = process.env.SHELL_URL || "http://127.0.0.60:8833/next/";
const ASK_LOG = path.join(__dirname, "fake-ws", "ask_log.json");
const QID = "ask-A-1-1";

const results = [];
function check(name, pass, detail) {
  results.push({ name, pass });
  console.log(`${pass ? "PASS" : "FAIL"}  ${name}${detail ? "  :: " + detail : ""}`);
}

(async () => {
  fs.rmSync(ASK_LOG, { force: true });   // 每次运行从零取证
  const browser = await puppeteer.launch({
    executablePath: EDGE, headless: "new",
    args: ["--no-sandbox", "--disable-gpu"],
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 900, deviceScaleFactor: 1 });
  const pageErrors = [];
  page.on("pageerror", (e) => pageErrors.push(e.message));

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const waitFor = async (fn, timeoutMs = 10000, stepMs = 150) => {
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
  const clickUntil = async (selector, predicate, attempts = 3, waitMs = 5000) => {
    for (let i = 0; i < attempts; i++) {
      await mouseClick(selector);
      if (await waitFor(predicate, waitMs)) return true;
      if (i < attempts - 1) console.log(`WARN clickUntil(${selector}) 未生效——重试 ${i + 1}`);
    }
    return false;
  };
  const api = (p) => page.evaluate(async (path) => {
    const res = await fetch(path);
    let data = null;
    try { data = await res.json(); } catch (_e) { data = null; }
    return { status: res.status, data };
  }, p);
  const submitTask = async (t) => {
    for (let attempt = 0; attempt < 2; attempt++) {
      const sel = await page.evaluate(() => {
        const vis = (s) => { const el = document.querySelector(s); return !!(el && el.offsetParent !== null); };
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
      console.log(`WARN submitTask("${t}") 未被受理——重试 ${attempt + 1}`);
    }
    return false;
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
  check("A10 前置：激活工作区", active.trim() !== "", active || "(无)");

  const submitted = await submitTask("提问演示");
  const cardSeen = await waitFor(async () =>
    await visible(`[data-st="answer:${QID}"]`), 15000);
  check("A10 问题卡出现（含选项与自由文本）", submitted && cardSeen, JSON.stringify({ submitted, cardSeen }));

  // fail-closed：无答复不自动推进（等待窗口后卡片仍在、无已答回执）
  await sleep(1200);
  const failClosed = await page.evaluate((qid) => ({
    card: document.querySelector(`[data-st="answer:${qid}"]`) !== null,
    resolved: document.querySelector(`[data-st="answer-resolved:${qid}"]`) !== null,
  }), QID);
  const snapPending = await api("/api/v1/workspaces").then(async (r) => {
    const list = r.data?.workspaces || [];
    const ws = list.find((w) => w.name === active.trim()) || list[0];
    const snap = await api(`/api/v1/workspaces/${ws.id}/snapshot`);
    return snap.data?.result?.status ?? null;
  });
  check("A10 fail-closed（无答复：卡片保留 + 任务挂起，不自动推进）",
    failClosed.card && !failClosed.resolved && snapPending === "pending",
    JSON.stringify({ ...failClosed, snapPending }));

  // 第 1 题：真实鼠标点选项；第 2 题：自由文本
  const optClicked = await mouseClick(`[data-st="answer-option:${QID}:0:0"]`);
  await page.click(`[data-st="answer-text:${QID}:1"]`);
  await page.type(`[data-st="answer-text:${QID}:1"]`, "需要");
  check("A10 选项 + 自由文本输入", optClicked && await page.evaluate((qid) =>
    document.querySelector(`[data-st="answer-text:${qid}:1"]`)?.value === "需要", QID));

  const submittedAnswer = await clickUntil(`[data-st="answer-submit:${QID}"]`,
    async () => await visible(`[data-st="answer-resolved:${QID}"]`));
  check("A10 提交答复（已答反馈可见）", submittedAnswer);

  const done = await waitFor(async () => {
    const r = await api("/api/v1/workspaces");
    const list = r.data?.workspaces || [];
    const ws = list.find((w) => w.name === active.trim()) || list[0];
    const snap = await api(`/api/v1/workspaces/${ws.id}/snapshot`);
    return snap.data?.result?.status === "done";
  }, 10000);
  const log = fs.existsSync(ASK_LOG)
    ? JSON.parse(fs.readFileSync(ASK_LOG, "utf8")) : [];
  const last = log.at(-1) || {};
  check("A10 服务端双证（answer_unit 收到答案 + 任务 done）",
    done && String(last.answer || "").includes("Markdown")
    && String(last.answer || "").includes("需要")
    && last.question_id === QID,
    JSON.stringify({ done, last }));

  check("无 pageerror", pageErrors.length === 0, pageErrors.join("; "));

  const failed = results.filter((r) => !r.pass);
  console.log(`\n== A10 提问链：${results.length - failed.length}/${results.length} PASS ==`);
  await browser.close();
  process.exit(failed.length === 0 ? 0 : 1);
})().catch((err) => { console.error("FATAL", err); process.exit(2); });
