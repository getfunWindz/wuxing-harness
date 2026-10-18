/* 重大优化清单 #2：确认卡四要素渲染 E2E——view 渲染 / 详情折叠（真实鼠标）/ 旧载荷回退。
   覆盖：#2 四要素/折叠/回退 · P1.5 偏好驱动 · T-4 键盘导航与批量键 · T-2 挂起通知（记录桩）。
   用法：python e2e/shell/restart_fixture.py
        SHELL_URL=http://127.0.0.60:8833/next/ node e2e/shell/check_confirm_view.js
   前置：cd apps/shell && npm run deploy。
   夹具：任务文本「确认文案演示」→ V-1（带 view）/ V-2（旧载荷无 view 回退）。
   纪律：交互断言用真实鼠标/键盘事件（page.mouse/page.keyboard）——合成事件不得作为可用性证据；
        T-2 的 Notification 记录桩仅替代 OS 投递（真实 toast 登记真机抽查）。 */
const puppeteer = require("puppeteer-core");

const EDGE = process.env.EDGE_PATH ||
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
const SHELL_URL = process.env.SHELL_URL || "http://127.0.0.60:8833/next/";
const BASE = SHELL_URL.replace(/\/next\/$/, "");

const results = [];
function check(name, pass, detail) {
  results.push({ name, pass });
  console.log(`${pass ? "PASS" : "FAIL"}  ${name}${detail ? "  :: " + detail : ""}`);
}

(async () => {
  const browser = await puppeteer.launch({
    executablePath: EDGE, headless: "new", protocolTimeout: 180000,
    args: ["--no-sandbox", "--disable-gpu"],
  });
  const page = await browser.newPage();
  // —— T-2：Notification 记录桩（granted；替代 OS 投递——真实 toast 由真机抽查覆盖） ——
  await page.evaluateOnNewDocument(() => {
    window.__wuxingNotified = [];
    class FakeNotification {
      constructor(title, options) {
        window.__wuxingNotified.push({
          title: String(title), body: String((options || {}).body || ""),
        });
      }
      close() {}
    }
    FakeNotification.permission = "granted";
    FakeNotification.requestPermission = async () => "granted";
    window.Notification = FakeNotification;
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
  const textOf = (sel) => page.evaluate((s) =>
    document.querySelector(s)?.textContent?.trim() || "", sel);
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

  // Phase 1.5 前置：将 fake-ws 交互偏好复位（确定性；workspace 作用域，不碰真实用户目录）
  const _wsList = await (await fetch(`${BASE}/api/v1/workspaces`)).json();
  const wsId = (_wsList.workspaces || [])[0]?.id ?? null;
  const postPrefs = (values) => fetch(`${BASE}/api/v1/interaction`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Wuxing": "1" },
    body: JSON.stringify({ scope: "workspace", ws: wsId, values }),
  }).then((r) => r.status);
  const stReset = await postPrefs({ confirm_verbosity: "standard",
    details_default_open: false, remember_details_choice: false,
    confirm_notify: true });
  if (stReset !== 200) console.log(`WARN 偏好复位失败：HTTP ${stReset}`);

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
  check("前置：激活工作区", active.trim() !== "", active || "(无)");

  const submitted = await submitTask("确认文案演示");
  const cardSeen = await waitFor(async () =>
    await visible('[data-st="confirm:V-1"]'), 15000);
  check("确认卡出现（V-1）", submitted && cardSeen,
    JSON.stringify({ submitted, cardSeen }));

  const vTitle = await textOf('[data-st="confirm-view:V-1"] .cf-view-title');
  const vObject = await textOf('[data-st="confirm-view:V-1"] .cf-view-object');
  const vAllow = await textOf('[data-st="confirm-view:V-1"] .cf-view-allow');
  const vDeny = await textOf('[data-st="confirm-view:V-1"] .cf-view-deny');
  const vHint = await textOf('[data-st="confirm-view:V-1"] .cf-view-hint');
  check("V-1 四要素渲染（标题/涉及/允许/拒绝/建议）",
    [vTitle, vObject, vAllow, vDeny, vHint].every((s) => s.length > 0),
    JSON.stringify({ vTitle, vObject, vAllow, vDeny, vHint }));

  const vMeta = await textOf('[data-st="confirm-view:V-1"] .cf-view-meta');
  check("V-1 触发说明 + 位置感",
    vMeta.includes("为什么问你") && vMeta.includes("任务位置：共 2 步，这是第 1 步"),
    vMeta);

  const closedBefore = await page.evaluate(() => {
    const el = document.querySelector('[data-st="confirm-details:V-1"]');
    return el ? el.open : null;
  });
  check("V-1 技术细节默认折叠", closedBefore === false, String(closedBefore));

  const clicked = await mouseClick('[data-st="confirm-details:V-1"] summary');
  const opened = await waitFor(async () => await page.evaluate(() => {
    const el = document.querySelector('[data-st="confirm-details:V-1"]');
    return !!(el && el.open);
  }), 3000);
  const detailText = await page.evaluate(() =>
    document.querySelector('[data-st="confirm-details:V-1"]')?.textContent || "");
  check("V-1 真实鼠标展开技术细节（含工具/交付）",
    clicked && opened && detailText.includes("write_artifact")
      && detailText.includes("演示产物"),
    JSON.stringify({ clicked, opened }));

  const v2Reason = await textOf('[data-st="confirm:V-2"] .confirm-reason');
  const v2ViewInactive = await page.evaluate(() => {
    const el = document.querySelector('[data-st="confirm-view:V-2"]');
    return !el || el.hidden || el.children.length === 0;
  });
  check("V-2 旧载荷回退（reason 可见 + 四要素区不渲染）",
    v2Reason.length > 0 && v2ViewInactive,
    JSON.stringify({ v2Reason, v2ViewInactive }));

  // —— Phase 1.5：交互偏好驱动渲染（workspace 作用域写 <fake-ws>/.wuxing/，不碰真实用户目录）——
  const st1 = await postPrefs({ confirm_verbosity: "concise",
                                details_default_open: true });
  await page.reload({ waitUntil: "domcontentloaded" });
  await waitFor(async () => await visible('[data-st="confirm:V-1"]'), 15000);
  const concise = await page.evaluate(() => ({
    meta: document.querySelector('[data-st="confirm-view:V-1"] .cf-view-meta')?.textContent ?? "",
    open: document.querySelector('[data-st="confirm-details:V-1"]')?.open ?? null,
    title: document.querySelector('[data-st="confirm-view:V-1"] .cf-view-title')?.textContent ?? "",
    link: document.querySelector('[data-st="confirm-view:V-1"] .cf-pref-link')?.textContent ?? "",
  }));
  check("P1.5 简洁档：次级行隐藏 + 四要素保留 + 细节默认展开",
    st1 === 200 && !concise.meta.includes("为什么问你")
      && !concise.meta.includes("任务位置")
      && concise.open === true && concise.title.length > 0
      && concise.link.trim() !== "",
    JSON.stringify({ st1, ...concise }));

  const st2 = await postPrefs({ confirm_verbosity: "standard",
                                details_default_open: false,
                                remember_details_choice: null });
  await page.reload({ waitUntil: "domcontentloaded" });
  await waitFor(async () => await visible('[data-st="confirm:V-1"]'), 15000);
  const back = await page.evaluate(() => ({
    meta: document.querySelector('[data-st="confirm-view:V-1"] .cf-view-meta')?.textContent ?? "",
    open: document.querySelector('[data-st="confirm-details:V-1"]')?.open ?? null,
    link: document.querySelector('[data-st="confirm-view:V-1"] .cf-pref-link')?.textContent ?? "",
  }));
  check("P1.5 标准档回退 + 反馈链接可见",
    st2 === 200 && back.meta.includes("为什么问你") && back.open === false
      && back.link.trim() !== "", JSON.stringify({ st2, ...back }));

  // —— T-2：挂起通知（记录桩；可见控制组 → 隐藏触发 → 去重） ——
  const notifiedCount = () => page.evaluate(() => (window.__wuxingNotified || []).length);
  const notifiedTitle = (i) => page.evaluate(
    (idx) => (window.__wuxingNotified || [])[idx]?.title || "", i);
  const n0 = await notifiedCount();
  check("T-2 可见时不通知（控制组）", n0 === 0, String(n0));
  await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState",
      { configurable: true, get: () => "hidden" });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await sleep(150);
  const n1 = await notifiedCount();
  const title1 = await notifiedTitle(0);
  check("T-2 隐藏切换触发通知（已有挂起；标题含计数）",
    n1 === 1 && title1.includes("2"), JSON.stringify({ n1, title1 }));
  await page.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));
  await sleep(150);
  check("T-2 重复触发不重发（按 unit 去重）",
    (await notifiedCount()) === 1, String(await notifiedCount()));
  await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState",
      { configurable: true, get: () => "visible" });
    document.dispatchEvent(new Event("visibilitychange"));
  });

  // —— T-4：确认区键盘导航 + 批量键（真实键盘事件；焦点环；守卫；钳制）——
  const activeSt = () => page.evaluate(() => {
    const el = document.activeElement;
    return el ? (el.id || el.getAttribute("data-st") || el.tagName) : "null";
  });
  const batchInfoText = () => page.evaluate(() =>
    document.querySelector('[data-st="confirm-batch-info"]')?.textContent?.trim() || "");
  const checkedUnits = () => page.evaluate(() =>
    [...document.querySelectorAll(".stream-confirm-list input[type='checkbox'][data-unit]")]
      .filter((el) => el.checked).map((el) => el.getAttribute("data-unit")));
  const pressAlt = async (keyName) => {
    await page.keyboard.down("Alt");
    await page.keyboard.press(keyName);
    await page.keyboard.up("Alt");
    await sleep(80);
  };
  await page.evaluate(() => { const el = document.activeElement;
    if (el instanceof HTMLElement) el.blur(); });
  await pressAlt("ArrowDown");
  const f1 = await activeSt();
  await pressAlt("ArrowDown");
  const f2 = await activeSt();
  await pressAlt("ArrowUp");
  const f3 = await activeSt();
  check("T-4 Alt+↓/↑ 依次跳转 V-1→V-2→V-1（checkbox 焦点）",
    f1 === "confirm-check-V-1" && f2 === "confirm-check-V-2" && f3 === "confirm-check-V-1",
    JSON.stringify({ f1, f2, f3 }));

  const ring = await page.evaluate(() => {
    const card = document.querySelector('[data-st="confirm:V-1"]');
    if (!card) return null;
    const cs = getComputedStyle(card);
    return { within: card.matches(":focus-within"), outline: cs.outlineStyle };
  });
  check("T-4 焦点环（:focus-within + outline）",
    !!ring && ring.within === true && ring.outline !== "none", JSON.stringify(ring));

  await page.evaluate(() => { document.querySelector("#confirm-reason-V-2")?.focus(); });
  await pressAlt("ArrowDown");
  const guarded = await activeSt();
  check("T-4 文本输入框内不触发跳转（守卫）", guarded === "confirm-reason-V-2", guarded);

  await page.evaluate(() => { document.querySelector("#confirm-check-V-1")?.focus(); });
  await pressAlt("ArrowUp");
  const clamped = await activeSt();
  check("T-4 首卡 Alt+↑ 钳制不循环（仍 V-1）", clamped === "confirm-check-V-1", clamped);

  await pressAlt("x");
  const t1 = await checkedUnits();
  const info1 = await batchInfoText();
  check("T-4 Alt+X 勾选当前卡（已选 1）",
    t1.length === 1 && t1[0] === "V-1" && info1.includes("已选 1"),
    JSON.stringify({ t1, info1 }));

  await pressAlt("a");
  const all = await checkedUnits();
  await pressAlt("a");
  const none = await checkedUnits();
  await pressAlt("a");
  const all2 = await checkedUnits();
  check("T-4 Alt+A 全选↔清空（2→0→2）",
    all.length === 2 && none.length === 0 && all2.length === 2,
    JSON.stringify({ all, none, all2 }));

  await pressAlt("n");
  const rejectFocus = await activeSt();
  const stillPending = await visible('[data-st="confirm:V-1"]');
  check("T-4 Alt+N 空原因 → 聚焦批量原因框且未提交",
    rejectFocus === "confirm-batch-reason" && stillPending === true,
    JSON.stringify({ rejectFocus, stillPending }));

  const reasonClicked = await mouseClick("#confirm-batch-reason");
  await page.type("#confirm-batch-reason", "批量拒绝演示");
  await pressAlt("n");
  const rejected = await waitFor(async () =>
    await visible('[data-st="confirm-resolved:V-1"]')
      && await visible('[data-st="confirm-resolved:V-2"]')
      && !(await visible('[data-st="confirm:V-1"]')), 8000);
  const resolvedText = await textOf('[data-st="confirm-resolved:V-1"]');
  check("T-4 填原因后 Alt+N 拒绝已选（两卡已决 + 原因回显）",
    reasonClicked && rejected && resolvedText.includes("已驳回")
      && resolvedText.includes("批量拒绝演示"),
    JSON.stringify({ reasonClicked, rejected, resolvedText }));

  // —— T-2：解决后再现（隐藏态新挂起 → 可再通知） ——
  const nBefore = await notifiedCount();
  await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState",
      { configurable: true, get: () => "hidden" });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  const resub = await submitTask("确认文案演示");
  const repend = await waitFor(async () => await visible('[data-st="confirm:V-1"]'), 15000);
  await sleep(300);
  const nAfter = await notifiedCount();
  const titles = await page.evaluate(() =>
    (window.__wuxingNotified || []).map((item) => item.title));
  check("T-2 隐藏态新挂起再通知（解决后再现）",
    resub && repend && nAfter > nBefore,
    JSON.stringify({ resub, repend, nBefore, nAfter, titles }));
  await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState",
      { configurable: true, get: () => "visible" });
  });

  check("无 pageerror", pageErrors.length === 0, pageErrors.join("; "));

  const failed = results.filter((r) => !r.pass);
  console.log(`\n== 确认文案：${results.length - failed.length}/${results.length} PASS ==`);
  await browser.close();
  process.exit(failed.length === 0 ? 0 : 1);
})().catch((err) => { console.error("FATAL", err); process.exit(2); });
