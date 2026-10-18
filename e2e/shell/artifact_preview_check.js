/* A6（W1）产物预览 E2E：点击产物行 → 预览面板（Markdown/截断/二进制托底）
   + 复制路径 / 本地打开动作（浏览器承载诚实降级）。
   用法：python e2e/shell/restart_fixture.py
        SHELL_URL=http://127.0.0.60:8833/next/ node e2e/shell/artifact_preview_check.js
   前置：cd apps/shell && npm run deploy。
   夹具：任务文本「产物预览演示」→ artifacts/报告.md + 大文件.txt(600KB) + 图片.png。
   纪律：交互断言用真实鼠标事件（page.mouse）——合成 click 绕过命中测试，
        不得作为交互可用性证据（2026-09-15 教训）。 */
const puppeteer = require("puppeteer-core");

const EDGE = process.env.EDGE_PATH ||
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
const SHELL_URL = process.env.SHELL_URL || "http://127.0.0.60:8833/next/";
const HOST = new URL(SHELL_URL).origin;

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
  // 剪贴板权限：headless Edge 下 Puppeteer overridePermissions 映射不生效（实测 denied）——
  // 直接走 CDP Browser.grantPermissions（clipboardSanitizedWrite = Edge/Chromium 写入权限名）
  const page = await browser.newPage();
  const cdp = await page.createCDPSession();
  await cdp.send("Browser.grantPermissions", {
    origin: HOST, permissions: ["clipboardSanitizedWrite"],
  });
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
  // 可见判定：fixed 定位元素 offsetParent 为 null——用 rect/display/visibility（弹层适用）
  const visible = (sel) => page.evaluate((s) => {
    const el = document.querySelector(s);
    if (!el || !el.isConnected) return false;
    const cs = getComputedStyle(el);
    if (cs.display === "none" || cs.visibility === "hidden") return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  }, sel);
  // 命中验证 + 真实鼠标（防遮挡盲区——沿用切片脚本口径）
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
  // E0-1（2026-10-02）口径：关键点击「校验效果 + 有界重试」（重渲染会移动元素）
  const clickUntil = async (selector, predicate, attempts = 3, waitMs = 5000) => {
    for (let i = 0; i < attempts; i++) {
      await mouseClick(selector);
      if (await waitFor(predicate, waitMs)) return true;
      if (i < attempts - 1) console.log(`WARN clickUntil(${selector}) 未生效——重试 ${i + 1}`);
    }
    return false;
  };
  const text = (sel) => page.evaluate((s) => document.querySelector(s)?.textContent || "", sel);
  const api = (path) => page.evaluate(async (p) => {
    const res = await fetch(p);
    let data = null;
    try { data = await res.json(); } catch (_e) { data = null; }
    return { status: res.status, data };
  }, path);
  const submitTask = async (t) => {
    // E0-1：提交以「输入区被清空」为受理信号；未受理则重试一次
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

  // 0) 确保有激活工作区（夹具默认打开 fake-ws；无则点击首项）
  let active = await page.evaluate(() =>
    document.querySelector(".rail-item.active .rail-name")?.textContent || "");
  if (active.trim() === "") {
    await mouseClick(".rail-item");
    await sleep(900);
    active = await page.evaluate(() =>
      document.querySelector(".rail-item.active .rail-name")?.textContent || "");
  }
  check("A6 前置：激活工作区", active.trim() !== "", active || "(无)");

  // 1) 提交夹具任务并等完成（服务端快照双证）
  const submitted = await submitTask("产物预览演示");
  const done = await waitFor(async () => {
    const r = await api("/api/v1/workspaces");
    const list = r.data?.workspaces || [];
    const ws = list.find((w) => w.name === active.trim()) || list[0];
    if (!ws) return false;
    const snap = await api(`/api/v1/workspaces/${ws.id}/snapshot`);
    return snap.data?.result?.status === "done";
  }, 20000);
  check("A6 前置：任务完成（snapshot done）", submitted && done, JSON.stringify({ submitted, done }));

  // 确保 dock 处于「产物」视图（默认视图即产物；标签存在时点选一次保证确定性）
  if (await page.evaluate(() => document.querySelector('[data-st="dock-tab:artifacts"]') !== null)) {
    await mouseClick('[data-st="dock-tab:artifacts"]');
    await sleep(400);
  }

  // 2) 三行产物（md / txt / png）可见
  const rowsSeen = await waitFor(async () => await page.evaluate(() =>
    document.querySelector('[data-st="art-row:artifacts/报告.md"]') !== null
    && document.querySelector('[data-st="art-row:artifacts/大文件.txt"]') !== null
    && document.querySelector('[data-st="art-row:artifacts/图片.png"]') !== null), 10000);
  check("A6 产物行（md/txt/png 三行可见）", rowsSeen);

  // 3) Markdown 预览：面板 + 内容 + 元信息
  const mdOpened = await clickUntil('[data-st="art-row:artifacts/报告.md"]',
    async () => await visible('[data-st="artifact-preview"]'));
  const mdContent = await text('[data-st="art-content"]');
  const mdMeta = await text('[data-st="artifact-preview"] .dock-item-meta');
  check("A6 Markdown 预览（面板 + 内容 + 元信息含 md）",
    mdOpened && mdContent.includes("演示产物") && mdMeta.includes("md"),
    JSON.stringify({ mdOpened, mdContent: mdContent.slice(0, 24), mdMeta: mdMeta.slice(0, 48) }));

  // 4) 复制路径 → 面板内反馈
  const copied = await clickUntil('[data-st="art-copy"]',
    async () => (await text('[data-st="art-notice"]')).includes("已复制路径"), 3, 4000);
  check("A6 复制路径（面板内反馈）", copied, await text('[data-st="art-notice"]'));

  // 5) 本地打开：浏览器承载诚实降级（复制 + 提示，不伪称已打开）
  const webFallback = await clickUntil('[data-st="art-open"]',
    async () => (await text('[data-st="art-notice"]')).includes("浏览器承载不支持本地打开"), 3, 4000);
  check("A6 本地打开降级（浏览器承载：复制 + 提示）", webFallback, await text('[data-st="art-notice"]'));

  // 6) 大文本截断：>512KiB → 提示 + 内容封顶 524288 字节
  const bigClicked = await clickUntil('[data-st="art-row:artifacts/大文件.txt"]',
    async () => await visible('[data-st="art-truncated"]'), 3, 6000);
  const bigLen = await page.evaluate(() =>
    (document.querySelector('[data-st="art-content"]')?.textContent || "").length);
  check("A6 大文本截断（提示 + 内容 ≤ 512KiB）",
    bigClicked && bigLen === 524288, JSON.stringify({ bigClicked, bigLen }));

  // 7) 二进制兜底：仅元信息，不渲染内容
  const binClicked = await clickUntil('[data-st="art-row:artifacts/图片.png"]',
    async () => await visible('[data-st="art-binary"]'), 3, 6000);
  const binInfo = await page.evaluate(() => ({
    binary: document.querySelector('[data-st="art-binary"]')?.textContent || "",
    hasContent: document.querySelector('[data-st="art-content"]') !== null,
  }));
  check("A6 二进制兜底（仅元信息 + 不渲染内容）",
    binClicked && binInfo.hasContent === false && binInfo.binary.includes("二进制"),
    JSON.stringify(binInfo));

  // 8) 关闭预览面板
  const closed = await clickUntil('[data-st="art-close"]',
    async () => !(await visible('[data-st="artifact-preview"]')), 3, 3000);
  check("A6 关闭预览面板", closed);

  check("无 pageerror", pageErrors.length === 0, pageErrors.join("; "));

  const failed = results.filter((r) => !r.pass);
  console.log(`\n== A6 产物预览：${results.length - failed.length}/${results.length} PASS ==`);
  await browser.close();
  process.exit(failed.length === 0 ? 0 : 1);
})().catch((err) => { console.error("FATAL", err); process.exit(2); });
