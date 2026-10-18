/* 上下文投影断言（B 期 · 2026-09-22）——顶栏 ~NN% + 右侧栏会话视图（DSH 形态）+ pi 式裁剪。
   用法：SHELL_URL=http://127.0.0.60:8833/next/ node e2e/shell/context_check.js
   前置：serve_fake 8833 零态（夹具每轮重启；context-edits.jsonl 已重置）。 */
const puppeteer = require("puppeteer-core");
const path = require("node:path");
const fs = require("node:fs");

const EDGE = process.env.EDGE_PATH ||
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
const URL = process.env.SHELL_URL || "http://127.0.0.60:8833/next/";
const OUT = process.env.OUT_DIR || path.join(__dirname, "visual", "context");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
fs.mkdirSync(OUT, { recursive: true });

const WS = path.join(__dirname, "fake-ws", ".wuxing");
const CONV = path.join(WS, "conversation-1710000100.jsonl");

const results = [];
function check(name, ok, detail) {
  results.push({ name, ok: !!ok });
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail !== undefined ? "  :: " + detail : ""}`);
}

async function previewApi(page, session) {
  return page.evaluate(async (name) => {
    const list = await (await fetch("/api/v1/workspaces")).json();
    const ws = list.workspaces.find((w) => w.name === "fake-ws")?.id
      ?? list.workspaces[0].id;
    const r = await fetch(`/api/v1/workspaces/${ws}/context-preview?session=${name}`);
    return r.json();
  }, session);
}

async function unitPreviewApi(page, unit) {
  return page.evaluate(async (uid) => {
    const list = await (await fetch("/api/v1/workspaces")).json();
    const ws = list.workspaces.find((w) => w.name === "fake-ws")?.id
      ?? list.workspaces[0].id;
    const r = await fetch(`/api/v1/workspaces/${ws}/context-preview?unit=${uid}`);
    return r.json();
  }, unit);
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
  await page.goto(URL, { waitUntil: "networkidle2", timeout: 25000 });
  await sleep(1500);

  const convBefore = fs.readFileSync(CONV, "utf8");

  // —— 选中会话 → 顶栏 ctx = ~NN%（诚实标记） ——
  await page.click('[data-st="rail-session:conversation-1710000100.jsonl"]');
  await sleep(1500);
  const topbar = await page.evaluate(() =>
    document.querySelector('.usage-bar .u-item[data-attr="ctx"]')?.textContent || "");
  check("顶栏 ctx = ~NN%（活动会话投影；批 2 档位徽标后缀可存在）",
    /^上下文~\d+%(黄金期|正常|严管)?$/.test(topbar) || /^~\d+%(黄金期|正常|严管)?$/.test(topbar),
    JSON.stringify(topbar));

  // —— dock 会话视图主面板（DSH 形态） ——
  await page.click('[data-st="dock-tab:sessions"]');
  await sleep(1800);
  const panel = await page.evaluate(() => ({
    panel: !!document.querySelector('[data-st="ctx-panel"]'),
    percent: document.querySelector('[data-st="ctx-percent"]')?.textContent || "",
    segs: [...document.querySelectorAll('[data-st^="ctx-seg:"]')].map((e) => e.dataset.st),
    rounds: document.querySelectorAll('[data-st^="ctx-round:"]').length,
    anchor: !!document.querySelector('[data-st="ctx-anchor"]'),
    rows: [...document.querySelectorAll('[data-st^="ctx-row:"]')].map((e) => e.textContent || ""),
  }));
  check("dock 会话视图主面板（环 + 拆段 + 轮次 + 锚点 + 行 %）",
    panel.panel && /^~\d+%$/.test(panel.percent)
    && panel.segs.includes("ctx-seg:fixed") && panel.segs.includes("ctx-seg:history")
    && panel.rounds >= 2 && panel.anchor && panel.rows.length >= 1,
    JSON.stringify(panel));
  // —— 精化（2026-09-23）：面板说明（防看不懂）+ 选中态深度 ——
  const explain = await page.evaluate(() => {
    const intro = document.querySelector('[data-st="ctx-intro"]');
    const help = document.querySelector('[data-st="ctx-help"]');
    return { intro: intro?.textContent || "",
             help: help?.textContent || "" };
  });
  check("会话面板说明 = 最基础口径（是什么/有什么用/推荐查看）",
    explain.intro.length > 0 && explain.help.includes("这是什么")
    && explain.help.includes("推荐查看"),
    JSON.stringify(explain).slice(0, 300));
  const pressed = await page.evaluate(() =>
    [...document.querySelectorAll(".ctx-src")].map((el) => ({
      key: el.dataset.st, on: el.classList.contains("on"),
      aria: el.getAttribute("aria-pressed") })));
  check("来源按钮 aria-pressed 与选中态同步",
    pressed.length > 0 && pressed.every((p) => p.aria === String(p.on)),
    JSON.stringify(pressed));
  // —— 精化（2026-09-23）：dock 滚动条隐形，鼠标移入才显形（真实鼠标 + 伪元素计算样式） ——
  const sbProbe = () => page.evaluate(() => {
    const el = document.querySelector(".dock-body");
    return { width: getComputedStyle(el, "::-webkit-scrollbar").width,
             bg: getComputedStyle(el, "::-webkit-scrollbar-thumb").backgroundColor };
  });
  const sbBefore = await sbProbe();
  const dockMid = await page.evaluate(() => {
    const r = document.querySelector(".dock-body").getBoundingClientRect();
    return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) };
  });
  await page.mouse.move(dockMid.x, dockMid.y);
  await sleep(300);
  const sbHover = await sbProbe();
  await page.mouse.move(120, 500);
  await sleep(300);
  const sbAfter = await sbProbe();
  const isClear = (c) => /rgba\(0,\s*0,\s*0,\s*0\)|transparent/.test(c);
  check("dock 滚动条：默认隐形、鼠标移入才显形",
    sbBefore.width === "8px" && isClear(sbBefore.bg)
    && !isClear(sbHover.bg) && isClear(sbAfter.bg),
    JSON.stringify({ sbBefore, sbHover, sbAfter }));
  await page.screenshot({ path: path.join(OUT, "ctx-panel.png") });

  // —— pi 式裁剪：省略第二轮 → 投影下降 + 文件零改写 ——
  const p0 = await previewApi(page, "conversation-1710000100.jsonl");
  const hist0 = (p0.segments || []).find((s) => s.key === "history")?.chars ?? -1;
  await page.click('[data-st="ctx-omit:2"]');
  await sleep(1500);
  const afterOmit = await page.evaluate(() => ({
    round2: document.querySelector('[data-st="ctx-round:2"]')?.textContent || "",
  }));
  const p1 = await previewApi(page, "conversation-1710000100.jsonl");
  const hist1 = (p1.segments || []).find((s) => s.key === "history")?.chars ?? -1;
  check("省略一轮 → 轮次标记「已省略」+ 投影字符下降",
    afterOmit.round2.includes("已省略") && hist1 < hist0,
    JSON.stringify({ round2: afterOmit.round2, hist0, hist1 }));
  check("会话日志零改写（fs 字节一致）",
    fs.readFileSync(CONV, "utf8") === convBefore, "");
  check("编辑 sidecar 落盘（append-only）",
    fs.existsSync(path.join(WS, "context-edits.jsonl")), "");

  // —— 替换第一轮（对话框） ——
  await page.click('[data-st="ctx-replace:1"]');
  await sleep(500);
  await page.click('[data-st="prompt-input"]');
  await page.type('[data-st="prompt-input"]', "替换后的第一轮文本");
  await page.click('[data-st="prompt-ok"]');
  await sleep(1500);
  const afterReplace = await page.evaluate(() => ({
    round1: document.querySelector('[data-st="ctx-round:1"]')?.textContent || "",
    percent: document.querySelector('[data-st="ctx-percent"]')?.textContent || "",
  }));
  const p2 = await previewApi(page, "conversation-1710000100.jsonl");
  const hist2 = (p2.segments || []).find((s) => s.key === "history")?.chars ?? -1;
  check("替换一轮 → 状态「已替换」+ 投影变化 + 顶栏仍为 ~NN%",
    afterReplace.round1.includes("已替换") && hist2 !== hist1
    && /^~\d+%$/.test(afterReplace.percent),
    JSON.stringify({ round1: afterReplace.round1, hist1, hist2 }));
  check("替换后日志仍零改写",
    fs.readFileSync(CONV, "utf8") === convBefore, "");
  await page.screenshot({ path: path.join(OUT, "ctx-edited.png") });

  // —— 碎片会话区（unit 投影切换）+ A2 三键裁剪 ——
  const unitCount = await page.evaluate(() =>
    document.querySelectorAll('[data-st^="ctx-unit:"]').length);
  if (unitCount > 0) {
    await page.click('[data-st="ctx-unit:P-a"]');
    await sleep(1200);
    const frag = await page.evaluate(() => ({
      title: document.querySelector('[data-st="ctx-title"]')?.textContent || "",
      msgs: document.querySelectorAll('[data-st^="ctx-msg:"]').length,
    }));
    check("碎片会话区点击 → 面板切换 unit 投影（含消息明细）",
      frag.title === "P-a" && frag.msgs > 0, JSON.stringify(frag));
    // A2：省略一条消息 → 前缀字符降 + 行标已省略 + sidecar 三键
    const u0 = await unitPreviewApi(page, "P-a");
    const pre0 = (u0.segments || []).find((s) => s.key === "fsc_prefix")?.chars ?? -1;
    const targetIdx = (u0.messages || []).find((m) =>
      (m.text || "").includes("并行分支A"))?.index;
    if (targetIdx !== undefined) {
      await page.click(`[data-st="ctx-msg-omit:${targetIdx}"]`);
      await sleep(1500);
      const u1 = await unitPreviewApi(page, "P-a");
      const pre1 = (u1.segments || []).find((s) => s.key === "fsc_prefix")?.chars ?? -1;
      const rowOmitted = await page.evaluate((i) =>
        document.querySelector(`[data-st="ctx-msg:${i}"]`)?.textContent?.includes("已省略") ?? false,
        targetIdx);
      const sideLines = fs.readFileSync(path.join(WS, "context-edits.jsonl"), "utf8")
        .split("\n").filter((s) => s.trim()).map((s) => JSON.parse(s));
      const rec = sideLines.find((r) => r.kind === "unit" && r.unit === "P-a");
      check("A2 碎片消息省略（前缀降 + 行标 + 三键 sidecar）",
        pre1 >= 0 && pre0 > pre1 && rowOmitted && rec !== undefined
        && typeof rec.fp_in === "string" && rec.fp_in !== ""
        && typeof rec.fp_out === "string",
        JSON.stringify({ pre0, pre1, rowOmitted, rec }));
      await page.screenshot({ path: path.join(OUT, "a2-msg-omit.png") });
    } else {
      check("A2 碎片消息省略（前缀降 + 行标 + 三键 sidecar）", false, "no target msg");
    }
  } else {
    check("碎片会话区点击 → 面板切换 unit 投影（含消息明细）", false, "no units");
  }

  // ============ G3（2026-09-26）：投影编辑恢复（回到原文） ============
  await page.click('[data-st="rail-session:conversation-1710000100.jsonl"]');
  await sleep(1200);
  await page.click('[data-st="dock-tab:sessions"]');
  await sleep(1500);
  const pR0 = await previewApi(page, "conversation-1710000100.jsonl");
  const histR0 = (pR0.segments || []).find((s) => s.key === "history")?.chars ?? -1;
  await page.click('[data-st="ctx-restore:2"]');
  await sleep(1500);
  const afterRestore = await page.evaluate(() => ({
    round2: document.querySelector('[data-st="ctx-round:2"]')?.textContent || "",
  }));
  const pR1 = await previewApi(page, "conversation-1710000100.jsonl");
  const histR1 = (pR1.segments || []).find((s) => s.key === "history")?.chars ?? -1;
  check("G3 恢复省略轮 → 状态回「在上下文」+ 投影回升",
    afterRestore.round2.includes("在上下文") && histR1 > histR0,
    JSON.stringify({ round2: afterRestore.round2, histR0, histR1 }));
  await page.click('[data-st="ctx-restore:1"]');
  await sleep(1200);
  const afterRestore1 = await page.evaluate(() =>
    document.querySelector('[data-st="ctx-round:1"]')?.textContent || "");
  check("G3 恢复替换轮 → 状态回「在上下文」",
    afterRestore1.includes("在上下文"), JSON.stringify(afterRestore1));
  check("G3 恢复不改写会话日志（fs 字节一致）",
    fs.readFileSync(CONV, "utf8") === convBefore, "");
  const sideG3 = fs.readFileSync(path.join(WS, "context-edits.jsonl"), "utf8")
    .split("\n").filter((s) => s.trim()).map((s) => JSON.parse(s));
  check("G3 恢复 append-only（sidecar 含 restore 行）",
    sideG3.some((r) => r.op === "restore"
      && r.conversation === "conversation-1710000100.jsonl"), "");
  await page.screenshot({ path: path.join(OUT, "g3-restored.png") });

  const unitCount2 = await page.evaluate(() =>
    document.querySelectorAll('[data-st^="ctx-unit:"]').length);
  if (unitCount2 > 0) {
    await page.click('[data-st="ctx-unit:P-a"]');
    await sleep(1200);
    const u2 = await unitPreviewApi(page, "P-a");
    const pre2 = (u2.segments || []).find((s) => s.key === "fsc_prefix")?.chars ?? -1;
    const idx2 = (u2.messages || []).find((m) =>
      (m.text || "").includes("并行分支A"))?.index;
    if (idx2 !== undefined) {
      await page.click(`[data-st="ctx-msg-restore:${idx2}"]`);
      await sleep(1500);
      const u3 = await unitPreviewApi(page, "P-a");
      const pre3 = (u3.segments || []).find((s) => s.key === "fsc_prefix")?.chars ?? -1;
      const stillOmitted = await page.evaluate((i) =>
        document.querySelector(`[data-st="ctx-msg:${i}"]`)?.textContent?.includes("已省略") ?? true,
        idx2);
      check("G3 碎片消息恢复（前缀回升 + 行不再标已省略）",
        pre3 > pre2 && stillOmitted === false,
        JSON.stringify({ pre2, pre3, stillOmitted }));
    } else {
      check("G3 碎片消息恢复（前缀回升 + 行不再标已省略）", false, "no target msg");
    }
  }

  check("无 pageerror", errors.length === 0, errors.join(" | "));

  // ============ A 期 A1（2026-09-22）：来源开关（会话级持久） ============
  await page.click('[data-st="rail-session:conversation-1710000100.jsonl"]');
  await sleep(1200);
  await page.click('[data-st="dock-tab:sessions"]');
  await sleep(1500);
  const srcBefore = await previewApi(page, "conversation-1710000100.jsonl");
  const histSeg = (srcBefore.segments || []).some((s) => s.key === "history");
  const srcOn = await page.evaluate(() =>
    document.querySelector('[data-st="ctx-src:history"]')?.classList.contains("on") ?? false);
  check("A1 来源开关默认开（history 段在）", srcOn && histSeg,
    JSON.stringify({ srcOn, histSeg }));
  await page.click('[data-st="ctx-src:history"]');
  await sleep(1500);
  const srcOff = await previewApi(page, "conversation-1710000100.jsonl");
  // 选中态 = 颜色深浅（深=选中）；aria-pressed 同步
  const depth = await page.evaluate(() => {
    const lum = (c) => {
      const m = (c.match(/\d+(\.\d+)?/g) || []).map(Number);
      const [r, g, b, a = 1] = m;
      return 0.2126 * (r * a + 255 * (1 - a))
        + 0.7152 * (g * a + 255 * (1 - a))
        + 0.0722 * (b * a + 255 * (1 - a));
    };
    const off = document.querySelector('[data-st="ctx-src:history"]');
    const on = document.querySelector('[data-st="ctx-src:digest"]');
    return { offBg: getComputedStyle(off).backgroundColor,
             onBg: getComputedStyle(on).backgroundColor,
             offLum: lum(getComputedStyle(off).backgroundColor),
             onLum: lum(getComputedStyle(on).backgroundColor),
             offAria: off.getAttribute("aria-pressed"),
             onAria: on.getAttribute("aria-pressed") };
  });
  check("来源选中态 = 颜色深浅（深=选中；aria-pressed 同步）",
    depth.offAria === "false" && depth.onAria === "true"
    && depth.offLum - depth.onLum >= 20, JSON.stringify(depth));
  const barSegs = await page.evaluate(() =>
    [...document.querySelectorAll('[data-st^="ctx-seg:"]')].map((e) => e.dataset.st));
  check("A1 关「会话历史」→ 投影段消失（面板同步）",
    !(srcOff.segments || []).some((s) => s.key === "history")
    && srcOff.sources?.history === false && !barSegs.includes("ctx-seg:history"),
    JSON.stringify({ segs: (srcOff.segments || []).map((s) => s.key),
                     sources: srcOff.sources, barSegs }));
  await page.screenshot({ path: path.join(OUT, "a1-sources-off.png") });
  // 实际注入：提交一轮 → trace 实测 history_chars == 0
  await page.click(".composer textarea");
  await page.type(".composer textarea", "A1 来源开关演示");
  await page.click('[data-st="composer-send"]');
  await sleep(3500);
  const traceRows = fs.readFileSync(path.join(WS, "trace.jsonl"), "utf8")
    .split("\n").filter((s) => s.trim()).map((s) => JSON.parse(s));
  const lastStarted = [...traceRows].reverse().find((r) => r.event === "unit_started");
  check("A1 实际注入：history_chars 字段在且为 0（trace 双证）",
    lastStarted !== undefined && lastStarted.history_chars !== undefined
    && Number(lastStarted.history_chars) === 0,
    JSON.stringify({ history_chars: lastStarted?.history_chars }));
  // 恢复开 → 段回来 + 再提交一轮 → 实测 history_chars > 0（开/关对照）
  await page.click('[data-st="ctx-src:history"]');
  await sleep(1500);
  const srcBack = await previewApi(page, "conversation-1710000100.jsonl");
  check("A1 恢复开 → 投影段回来",
    (srcBack.segments || []).some((s) => s.key === "history")
    && srcBack.sources?.history === true,
    JSON.stringify(srcBack.sources));
  await page.click(".composer textarea");
  await page.type(".composer textarea", "A1 来源恢复演示");
  await page.click('[data-st="composer-send"]');
  await sleep(3500);
  const traceRows2 = fs.readFileSync(path.join(WS, "trace.jsonl"), "utf8")
    .split("\n").filter((s) => s.trim()).map((s) => JSON.parse(s));
  const lastStarted2 = [...traceRows2].reverse().find((r) => r.event === "unit_started");
  check("A1 开/关对照：恢复后 history_chars > 0",
    lastStarted2 !== undefined && Number(lastStarted2.history_chars || 0) > 0,
    JSON.stringify({ history_chars: lastStarted2?.history_chars }));

  // —— A 期 A3：预算设置与裁剪提示 ——
  await page.click('[data-st="dock-tab:sessions"]');
  await sleep(2000);
  const budgetBefore = await page.evaluate(() =>
    document.querySelector('[data-st="ctx-budget-value"]')?.textContent || "");
  check("A3 预算行默认未设",
    budgetBefore.includes("未设") || budgetBefore.includes("no budget"),
    JSON.stringify(budgetBefore));
  await page.click('[data-st="ctx-budget-set"]');
  await sleep(400);
  await page.click('[data-st="prompt-input"]');
  await page.type('[data-st="prompt-input"]', "100");
  await page.click('[data-st="prompt-ok"]');
  await sleep(1500);
  const budgetAfter = await previewApi(page, "conversation-1710000100.jsonl");
  const budgetShown = await page.evaluate(() => ({
    value: document.querySelector('[data-st="ctx-budget-value"]')?.textContent || "",
    trimmed: !!document.querySelector('[data-st="ctx-budget-trimmed"]'),
  }));
  check("A3 设置预算 → 显示值 + 裁剪提示",
    budgetAfter.budget_tokens === 100 && budgetShown.value.includes("100")
    && budgetShown.trimmed,
    JSON.stringify({ budget: budgetAfter.budget_tokens, budgetShown,
                     trimmed: budgetAfter.trimmed }));
  await page.screenshot({ path: path.join(OUT, "a3-budget.png") });
  // 关闭（0）→ 恢复
  await page.click('[data-st="ctx-budget-set"]');
  await sleep(400);
  await page.$eval('[data-st="prompt-input"]', (el) => { el.value = ""; });
  await page.click('[data-st="prompt-input"]');
  await page.type('[data-st="prompt-input"]', "0");
  await page.click('[data-st="prompt-ok"]');
  await sleep(1200);
  const budgetOff = await previewApi(page, "conversation-1710000100.jsonl");
  check("A3 预算关闭（0）→ 恢复", budgetOff.budget_tokens === 0,
    JSON.stringify({ budget: budgetOff.budget_tokens }));
  const failed = results.filter((r) => !r.ok);
  console.log(`\n${failed.length === 0 ? "✔" : "✘"} context 断言 ` +
    `${results.length - failed.length}/${results.length}` +
    (failed.length ? "；失败：" + failed.map((f) => f.name).join("；") : ""));
  await browser.close();
  process.exit(failed.length === 0 && errors.length === 0 ? 0 : 1);
})();
