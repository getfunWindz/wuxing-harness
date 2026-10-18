/* G8-M3 定向 E2E（8833 假引擎夹具）：
   ① 两会话并行任务（慢任务窗口内，B 会话 202 受理）
   ② 同会话并发提交 → 409（该会话已有活动任务）
   ③ 票据认领冲突 → 提交 409（持有者可见）
   ④ 陈旧认领标记展示（设计卡：ghost-session +（陈旧））
   用法：python e2e/shell/restart_fixture.py
        SHELL_URL=http://127.0.0.60:8833/next/ node e2e/shell/g8_m3_check.js
   全过退出 0；任一失败退出 1。交互断言用真实鼠标事件（page.mouse）。 */
const puppeteer = require("puppeteer-core");
const fs = require("fs");
const path = require("path");
const { execFileSync } = require("child_process");

const EDGE = process.env.EDGE_PATH ||
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
const SHELL_URL = process.env.SHELL_URL || "http://127.0.0.60:8833/next/";
const HOST = new URL(SHELL_URL).origin;
const PAR_WS = path.resolve(__dirname, "g8-par-ws");
const CLAIM_WS = path.resolve(__dirname, "g8-claim-ws");

const results = [];
function check(name, pass, detail) {
  results.push({ name, pass });
  console.log(`${pass ? "PASS" : "FAIL"}  ${name}${detail ? "  :: " + detail : ""}`);
}

/** 目录清空重建（本环境 Node fs.rmSync 在仓库树内静默失效——用 cmd rmdir）。 */
function wipeDir(p) {
  if (fs.existsSync(p)) {
    execFileSync("cmd", ["/c", "rmdir", "/s", "/q", p], { stdio: "ignore" });
  }
  fs.mkdirSync(p, { recursive: true });
}

(async () => {
  // ---- 夹具准备（脚本侧；UI 交互随后真实鼠标驱动）----
  wipeDir(PAR_WS);
  wipeDir(CLAIM_WS);
  for (const p of [PAR_WS, CLAIM_WS]) {
    const r = await fetch(`${HOST}/api/v1/workspaces`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Wuxing": "1" },
      body: JSON.stringify({ path: p.split(path.sep).join("/") }),
    });
    if (!r.ok) throw new Error(`注册工作区失败 ${p}: ${r.status}`);
  }

  const browser = await puppeteer.launch({
    executablePath: EDGE, headless: "new",
    args: ["--no-sandbox", "--disable-gpu"],
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 900, deviceScaleFactor: 1 });
  const pageErrors = [];
  page.on("pageerror", (e) => pageErrors.push(e.message));
  const responses = [];
  page.on("response", (res) => {
    const rec = { url: res.url(), status: res.status(), body: "" };
    responses.push(rec);
    if (res.request().method() === "POST" && res.url().includes("/tasks")) {
      res.text().then((t) => { rec.body = t; }).catch(() => { /* 体读取失败不阻断 */ });
    }
  });
  await page.evaluateOnNewDocument(() => {
    window.__rej = [];
    window.addEventListener("unhandledrejection", (ev) => {
      window.__rej.push(String((ev.reason && ev.reason.stack) || ev.reason));
    });
  });

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const waitFor = async (fn, timeoutMs = 8000, stepMs = 150) => {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      if (await fn()) return true;
      await sleep(stepMs);
    }
    return false;
  };
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
    let box = await probeBox(selector);
    if (!box) return false;
    if (!box.ok) {
      await sleep(200);
      box = await probeBox(selector);
      if (!box || !box.ok) {
        console.log(`WARN mouseClick(${selector}) 被遮挡：${box ? box.hit : "element-gone"}`);
        return false;
      }
    }
    await page.mouse.move(box.x, box.y);
    await sleep(60);
    await page.mouse.click(box.x, box.y);
    return true;
  };
  const clickByText = async (selector, text, opts = {}) => {
    const exact = opts.exact === true;
    const box = await page.evaluate((sel, want, ex) => {
      const el = [...document.querySelectorAll(sel)].find((e) => {
        const t = (e.textContent || "").trim();
        return ex ? t === want : t.includes(want);
      });
      if (!el) return null;
      el.scrollIntoView({ block: "center" });
      const r = el.getBoundingClientRect();
      return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) };
    }, selector, text, exact);
    if (!box) return false;
    await page.mouse.move(box.x, box.y);
    await sleep(60);
    await page.mouse.click(box.x, box.y);
    return true;
  };
  const openPalette = async () => {
    await page.keyboard.down("Control");
    await page.keyboard.press("k");
    await page.keyboard.up("Control");
    return waitFor(async () => await page.evaluate(() =>
      !!document.querySelector(".palette-overlay")), 5000);
  };
  const filterPalette = async (text) => {
    await mouseClick('[data-st="palette-input"]');
    await page.keyboard.down("Control");
    await page.keyboard.press("a");
    await page.keyboard.up("Control");
    await page.keyboard.press("Backspace");
    await page.type('[data-st="palette-input"]', text);
    await sleep(250);
  };
  const composerField = () => page.evaluate(() => {
    const vis = (s) => { const el = document.querySelector(s); return !!(el && el.offsetParent !== null); };
    return vis(".hero-text") ? ".hero-text" : ".cbox textarea";
  });
  const typeTask = async (text, clearFirst = false) => {
    const field = await composerField();
    await mouseClick(field);
    if (clearFirst) {
      await page.keyboard.down("Control");
      await page.keyboard.press("a");
      await page.keyboard.up("Control");
      await page.keyboard.press("Backspace");
    }
    await page.type(field, text);
    await page.keyboard.press("Enter");
  };
  const switchWs = async (name) => {
    await openPalette();
    await filterPalette("切换到工作区");
    const ok = await clickByText(".palette-item", `切换到工作区：${name}`, { exact: true });
    await sleep(700);
    return ok && await waitFor(async () => await page.evaluate((n) =>
      (document.querySelector(".rail-item.active")?.textContent || "").includes(n), name), 5000);
  };
  const wsIdByBase = async (base) => {
    const r = await fetch(`${HOST}/api/v1/workspaces`).then((x) => x.json());
    return (r.workspaces || []).find((w) =>
      String(w.path || "").replace(/\\/g, "/").endsWith(`/${base}`))?.id || "";
  };
  const snapshot = (wsId) =>
    fetch(`${HOST}/api/v1/workspaces/${wsId}/snapshot`).then((x) => x.json());
  const tasksResp = (wsId) =>
    responses.filter((r) => r.url.includes(`/workspaces/${wsId}/tasks`));
  const toastText = () => page.evaluate(() => {
    const el = document.querySelector('[data-st="toast"]');
    return el && !el.hasAttribute("hidden") ? (el.textContent || "") : "";
  });

  try {
    await page.goto(SHELL_URL, { waitUntil: "domcontentloaded" });
    const ready = await waitFor(async () => await page.evaluate(() =>
      document.body.dataset.state === "ready"), 15000);
    check("壳就绪（data-state=ready）", ready, "");
    if (!ready) throw new Error("壳未就绪");

    // ================= A 段：并行 + 同会话 409（g8-par-ws） =================
    check("切换并行工作区（g8-par-ws）", await switchWs("g8-par-ws"), "");
    const parId = await wsIdByBase("g8-par-ws");
    check("并行工作区可寻（ws id）", !!parId, parId);

    await typeTask("慢任务 A");
    const a202 = await waitFor(() => tasksResp(parId).some((r) => r.status === 202), 8000);
    const aRunning = await waitFor(async () =>
      (await snapshot(parId)).active_run?.status === "running", 8000);
    check("慢任务 A 受理并运行中", a202 && aRunning, "");

    // 同会话并发：壳侧运行中输入区禁用（真实渲染断言）+ 机制侧 409 直证（页面同源 fetch）
    const composerDisabled = await page.evaluate(() => {
      const el = document.querySelector(".cbox textarea");
      return !!(el && el.disabled);
    });
    const sessA = (await snapshot(parId)).active_run?.session || "";
    const dupStatus = sessA === "" ? 0 : await page.evaluate(async (wsId, session) => {
      const r = await fetch(`/api/v1/workspaces/${wsId}/tasks`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Wuxing": "1" },
        body: JSON.stringify({ text: "重复提交", session }),
      });
      return r.status;
    }, parId, sessA);
    check("同会话并发（运行中输入区禁用 + 机制 409）",
      composerDisabled && dupStatus === 409,
      `disabled=${composerDisabled} dupStatus=${dupStatus} session=${sessA}`);

    const newSession = await mouseClick('[data-st="rail-new-session"]');
    await sleep(500);
    await typeTask("慢任务 B", true);
    const b202 = await waitFor(() =>
      tasksResp(parId).filter((r) => r.status === 202).length >= 2, 8000);
    const stillRunning = (await snapshot(parId)).active_run?.status === "running";
    check("两会话并行（A 运行中 B 受理 202）",
      newSession && b202 && stillRunning, `newSession=${newSession} b202=${b202} stillRunning=${stillRunning}`);

    const idle = await waitFor(async () =>
      (await snapshot(parId)).workspace?.status === "idle", 45000, 500);
    check("并行任务全部收尾（workspace idle）", idle, "");

    // ================= B 段：票据 409 + 陈旧标记（g8-claim-ws） =================
    check("切换认领工作区（g8-claim-ws）", await switchWs("g8-claim-ws"), "");
    const claimId = await wsIdByBase("g8-claim-ws");
    check("认领工作区可寻（ws id）", !!claimId, claimId);

    // 新会话（消除跨工作区 activeSession 残留）
    await mouseClick('[data-st="rail-new-session"]');
    await sleep(400);

    await mouseClick('[data-st="mode-chip"]');
    await sleep(300);
    await mouseClick('[data-st="mode-pick:theroad"]');
    await sleep(600);
    const modeTag = await page.evaluate(() =>
      document.querySelector('[data-st="session-mode-tag"]')?.textContent || "");
    check("会话模式切到循迹（空白会话）", modeTag.includes("循迹"), modeTag);

    await typeTask("快任务");
    const fast202 = await waitFor(() =>
      tasksResp(claimId).some((r) => r.status === 202), 8000);
    const fastIdle = await waitFor(async () =>
      (await snapshot(claimId)).workspace?.status === "idle", 25000, 400);
    const claimSnap = await snapshot(claimId);
    check("首任务受理并收尾（建立会话）", fast202 && fastIdle,
      JSON.stringify({
        fast202, fastIdle,
        resp: tasksResp(claimId).map((r) => [r.status, r.body]),
        wsStatus: claimSnap.workspace?.status,
        runId: claimSnap.run_id, session: claimSnap.session,
      }));

    let seeded = "";
    try {
      seeded = String(execFileSync(
        "python", [path.join(__dirname, "g8_seed.py"), CLAIM_WS, "ghost-session"],
        { encoding: "utf-8" })).trim();
    } catch (err) {
      seeded = `ERR ${err.message}`;
    }
    check("种子写入（ghost 认领 + 地图/规格）", seeded.includes("ghost-session"), seeded);

    // 刷新设计态：dock 会话视图 → 点当前会话行（触发 refreshSessionMeta）
    await openPalette();
    await filterPalette("打开：会话");
    await clickByText(".palette-item", "打开：会话");
    await sleep(700);
    const rowClicked = await mouseClick('[data-st^="ctx-session:"]');
    const cardVisible = await waitFor(async () => await page.evaluate(() =>
      !!document.querySelector('[data-st="design-impl-tickets"]')), 8000);
    const cardText = await page.evaluate(() =>
      document.querySelector('[data-st="design-impl-tickets"]')?.textContent || "");
    check("陈旧认领标记展示（设计卡：ghost-session + 陈旧）",
      rowClicked && cardVisible && cardText.includes("ghost-session")
      && cardText.includes("陈旧"),
      cardText.slice(0, 140));

    const before409 = tasksResp(claimId).filter((r) => r.status === 409).length;
    await typeTask("执行切片");
    const conflict = await waitFor(() =>
      tasksResp(claimId).filter((r) => r.status === 409).length > before409, 8000);
    const toastClaim = await toastText();
    check("票据认领冲突 → 提交 409 + 提示（持有者可见）",
      conflict && toastClaim.includes("票据已被认领") && toastClaim.includes("ghost-session"),
      `409New=${conflict} toast=${toastClaim.slice(0, 120)} resp=${JSON.stringify(tasksResp(claimId).map((r) => [r.status, r.body && r.body.slice(0, 80)]))}`);

    const rej = await page.evaluate(() => window.__rej || []);
    check("无页面错误 / 未处理拒绝",
      pageErrors.length === 0 && rej.length === 0,
      JSON.stringify({ pageErrors, rej }).slice(0, 400));
  } catch (err) {
    check("脚本执行（未捕获异常）", false, String(err && err.stack || err));
  }

  const failed = results.filter((r) => !r.pass);
  console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
  await browser.close();
  process.exit(failed.length === 0 ? 0 : 1);
})().catch((err) => {
  console.error("FATAL", err);
  process.exit(1);
});
