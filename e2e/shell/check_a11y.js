/* T-3 无障碍基线 E2E（真实键盘/鼠标）：F1 键盘链 · F2 弹层语义 · F3 名称 · F4 对比度/焦点 · F5 h1。
   用法：python e2e/shell/run_all.py --only a11y（前置：cd apps/shell && npm run deploy）
   纪律：交互一律真实键鼠事件；对比度按最近祖先不透明背景合成（同审计脚本口径）。 */
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
  const visible = (sel) => page.evaluate((s) => {
    const el = document.querySelector(s);
    if (!el || !el.isConnected) return false;
    const cs = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return cs.display !== "none" && cs.visibility !== "hidden" && r.width > 0 && r.height > 0;
  }, sel);
  const focusSt = (sel) => page.evaluate((s) => {
    const el = document.querySelector(s);
    if (!el) return false;
    el.focus();
    return document.activeElement === el;
  }, sel);
  const activeDesc = () => page.evaluate(() => {
    const el = document.activeElement;
    if (!el) return "none";
    return el.getAttribute("data-st") || el.id || el.tagName;
  });

  await page.goto(SHELL_URL, { waitUntil: "domcontentloaded" });
  await sleep(1800);

  // —— T-6：首用引导条（无标记 → 显示；知道了 → 隐藏且持久；清除标记 → 提交后隐藏） ——
  const onboardVisible = () => visible('[data-st="hero-onboard"]');
  const onboardShown = await onboardVisible();
  check("T-6 首用引导条显示（零态 + 无标记）", onboardShown, "");
  const dismissEl = await page.$('[data-st="onboard-dismiss"]');
  if (dismissEl !== null) await dismissEl.click();
  await sleep(200);
  check("T-6 「知道了」关闭引导条", onboardShown && !(await onboardVisible()), "");
  await page.reload({ waitUntil: "domcontentloaded" });
  await sleep(1500);
  check("T-6 关闭后刷新仍隐藏（localStorage 持久）",
    onboardShown && !(await onboardVisible()), "");
  await page.evaluate(() => {
    try { localStorage.removeItem("wuxing.onboard.v1"); } catch (err) { void err; }
  });
  await page.reload({ waitUntil: "domcontentloaded" });
  await sleep(1500);
  const onboardAgain = await onboardVisible();
  check("T-6 清除标记后重新显示（记账键生效）", onboardAgain, "");

  let active = await page.evaluate(() =>
    document.querySelector(".rail-item.active .rail-name")?.textContent || "");
  if (active.trim() === "") {
    await page.click(".rail-item").catch(() => undefined);
    await sleep(900);
  }
  await page.click(".hero-text");
  await page.type(".hero-text", "确认文案演示");
  await page.keyboard.press("Enter");
  await waitFor(async () => await visible('[data-st="confirm:V-1"]'), 15000);
  check("前置：确认卡场景就绪", await visible('[data-st="confirm:V-1"]'), "");
  check("T-6 首次提交任务后引导条隐藏",
    onboardAgain && !(await onboardVisible()), JSON.stringify({ onboardAgain }));

  // —— F1a：Tab 链不再被 rail 搜索截断；搜索框聚焦不弹层；Enter 激活；Esc 归还焦点 ——
  await focusSt('[data-st="topbar-card-toggle"]');
  const chain = [];
  let sawSearchHijack = false;
  for (let i = 0; i < 45; i++) {
    await page.keyboard.press("Tab");
    await sleep(30);
    const item = await page.evaluate(() => {
      const el = document.activeElement;
      let searchOpening = false;
      if (el && (el.getAttribute("data-st") || "") === "rail-search") {
        searchOpening = !!document.querySelector(".search-overlay");
      }
      return { id: (el && (el.getAttribute("data-st") || el.id || el.tagName)) || "none", searchOpening };
    });
    if (item.searchOpening) sawSearchHijack = true;
    chain.push(item.id);
    if (chain.includes("composer-text") && chain.includes("confirm-check:V-1")) break;
  }
  check("F1 Tab 链不再被搜索框截断（rail-search 聚焦不弹层）",
    !sawSearchHijack && chain.includes("rail-search"), JSON.stringify({ hijack: sawSearchHijack }));
  check("F1 Tab 链可达确认卡与 composer",
    chain.includes("confirm-check:V-1") && chain.includes("composer-text"),
    JSON.stringify(chain.slice(-14)));
  await focusSt('[data-st="rail-search"]');
  await page.keyboard.press("Enter");
  const searchOpen = await waitFor(async () => await visible(".search-overlay"), 4000);
  const searchFocus = await activeDesc();
  check("F1 搜索框 Enter 激活 + 焦点入覆盖层",
    searchOpen && searchFocus === "search-input", JSON.stringify({ searchOpen, searchFocus }));
  const ring = await page.evaluate(() => {
    const el = document.querySelector("#search-input");
    if (!el) return null;
    const cs = getComputedStyle(el);
    return { outline: cs.outlineStyle, width: cs.outlineWidth };
  });
  check("F4 搜索输入焦点指示可见",
    !!ring && ring.outline !== "none" && parseFloat(ring.width) > 0, JSON.stringify(ring));
  await page.keyboard.press("Escape");
  await sleep(200);
  check("F1 搜索关闭后焦点归还触发输入",
    (await activeDesc()) === "rail-search" && !(await visible(".search-overlay")),
    await activeDesc());

  // —— F1b：palette 焦点归还 ——
  await focusSt('[data-st="rail-recycle"]');
  await page.keyboard.down("Control");
  await page.keyboard.press("k");
  await page.keyboard.up("Control");
  await waitFor(async () => await visible("#palette-input"), 4000);
  await page.keyboard.press("Escape");
  await sleep(200);
  check("F1 palette 关闭焦点归还", (await activeDesc()) === "rail-recycle", await activeDesc());

  // —— F1c + F2：help 模态（焦点入 + 语义 + 归还） ——
  await focusSt('[data-st="open-help"]');
  await page.keyboard.press("Enter");
  await waitFor(async () => await visible('[data-st="help"]'), 4000);
  const helpDialog = await page.evaluate(() => {
    const el = document.querySelector('[data-st="help"]');
    return el ? {
      role: el.getAttribute("role"), ariaModal: el.getAttribute("aria-modal"),
      label: el.getAttribute("aria-label"),
      focusedInside: el.contains(document.activeElement),
    } : null;
  });
  check("F2 help 弹层语义（dialog/aria-modal/label）",
    !!helpDialog && helpDialog.role === "dialog" && helpDialog.ariaModal === "true"
      && !!helpDialog.label, JSON.stringify(helpDialog));
  check("F1 help 打开焦点入模态", !!helpDialog && helpDialog.focusedInside === true,
    JSON.stringify(helpDialog));
  await page.keyboard.press("Escape");
  await sleep(200);
  check("F1 help 关闭焦点归还触发按钮", (await activeDesc()) === "open-help", await activeDesc());

  // —— F2：settings 弹层语义 ——
  await page.keyboard.down("Control");
  await page.keyboard.press("k");
  await page.keyboard.up("Control");
  await waitFor(async () => await visible("#palette-input"), 4000);
  await page.type("#palette-input", "settings");
  await sleep(250);
  await page.keyboard.press("Enter");
  await waitFor(async () => await visible(".settings-overlay:not([hidden])"), 5000);
  const settingsDialog = await page.evaluate(() => {
    const el = document.querySelector(".settings-overlay");
    return el ? {
      role: el.getAttribute("role"), ariaModal: el.getAttribute("aria-modal"),
      label: el.getAttribute("aria-label"),
    } : null;
  });
  check("F2 settings 弹层语义", !!settingsDialog && settingsDialog.role === "dialog"
    && settingsDialog.ariaModal === "true" && !!settingsDialog.label,
    JSON.stringify(settingsDialog));
  await page.keyboard.press("Escape");
  await sleep(250);

  // —— F3：可访问名称 ——
  const names = await page.evaluate(() => {
    const label = (s) => {
      const node = document.querySelector(s);
      return node ? (node.getAttribute("aria-label") || "").trim() : "";
    };
    return {
      composer: label("#composer-text"),
      batchReason: label("#confirm-batch-reason"),
      cardReason: label("#confirm-reason-V-1"),
      help: label('[data-st="open-help"]'),
      railCollapse: label('[data-st="rail-collapse"]'),
      attach: label('[data-st="composer-attach"]'),
      skill: label('[data-st="composer-skill"]'),
      dockCollapse: label('[data-st="dock-collapse"]'),
      confirmCheck: label('[data-st="confirm-check:V-1"]'),
    };
  });
  check("F3 关键控件均有可访问名称（aria-label）",
    Object.values(names).every((v) => v.length > 0), JSON.stringify(names));

  // —— F4：rail-status 对比度 ≥ 4.5 ——
  const contrast = await page.evaluate(() => {
    const parse = (c) => {
      const m = String(c).match(/rgba?\(([^)]+)\)/);
      if (!m) return null;
      const p = m[1].split(",").map((s) => parseFloat(s));
      return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 };
    };
    const blend = (t, b) => ({ r: t.r * t.a + b.r * (1 - t.a), g: t.g * t.a + b.g * (1 - t.a),
      b: t.b * t.a + b.b * (1 - t.a), a: 1 });
    const lum = (c) => {
      const f = (v) => { const x = v / 255; return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4); };
      return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b);
    };
    const ratio = (a, b) => {
      const l1 = lum(a), l2 = lum(b);
      return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
    };
    const el = document.querySelector(".rail-status");
    if (!el) return null;
    const fg = parse(getComputedStyle(el).color);
    const layers = [];
    for (let node = el; node; node = node.parentElement) {
      const c = parse(getComputedStyle(node).backgroundColor);
      if (c && c.a > 0) layers.push(c);
    }
    let bg = { r: 255, g: 255, b: 255, a: 1 };
    for (let i = layers.length - 1; i >= 0; i--) bg = blend(layers[i], bg);
    return { ratio: Math.round(ratio(fg, bg) * 100) / 100, color: getComputedStyle(el).color };
  });
  check("F4 rail-status 对比度 ≥4.5", !!contrast && contrast.ratio >= 4.5, JSON.stringify(contrast));

  // —— F5：sr-only h1 ——
  const h1 = await page.evaluate(() => {
    const el = document.querySelector("h1.sr-only");
    return el ? { text: (el.textContent || "").trim() } : null;
  });
  check("F5 页面级 sr-only h1", !!h1 && h1.text.length > 0, JSON.stringify(h1));

  check("无 pageerror", pageErrors.length === 0, pageErrors.join("; "));

  const failed = results.filter((r) => !r.pass);
  console.log(`\n== T-3 无障碍基线：${results.length - failed.length}/${results.length} PASS ==`);
  await browser.close();
  process.exit(failed.length === 0 ? 0 : 1);
})().catch((err) => { console.error("FATAL", err); process.exit(2); });
