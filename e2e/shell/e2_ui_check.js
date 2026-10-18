/* E2-UI 端到端（8833 假引擎夹具）：扩展命令（面板条目/逐字段表单/结果卡片）+
   装配预设（面板切换 + 设置「装配」分区）。
   用法：python e2e/shell/restart_fixture.py
        SHELL_URL=http://127.0.0.60:8833/next/ node e2e/shell/e2_ui_check.js
   全过退出 0；任一失败退出 1。
   纪律：交互断言用真实鼠标事件（page.mouse）——合成 click 绕过命中测试（2026-09-15 教训）。 */
const puppeteer = require("puppeteer-core");

const EDGE = process.env.EDGE_PATH ||
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
const URL = process.env.SHELL_URL || "http://127.0.0.60:8833/next/";

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
  const reqs = [];
  page.on("request", (req) => {
    reqs.push({ method: req.method(), url: req.url(), body: req.postData() || "" });
  });
  await page.evaluateOnNewDocument(() => {
    window.__rej = [];
    window.addEventListener("unhandledrejection", (ev) => {
      window.__rej.push(String((ev.reason && ev.reason.stack) || ev.reason));
    });
  });

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const waitFor = async (fn, timeoutMs = 8000) => {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      if (await fn()) return true;
      await sleep(150);
    }
    return false;
  };
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
  const paletteTexts = () => page.evaluate(() =>
    [...document.querySelectorAll(".palette-item")].map((e) => (e.textContent || "").trim()));
  const resultText = () => page.evaluate(() => {
    const el = document.querySelector('[data-st="cmd-result"]');
    return el ? (el.textContent || "") : "";
  });

  try {
    await page.goto(URL, { waitUntil: "domcontentloaded" });
    const ready = await waitFor(async () => await page.evaluate(() =>
      document.body.dataset.state === "ready"), 15000);
    check("壳就绪（data-state=ready）", ready, "");
    if (!ready) throw new Error("壳未就绪");

    // ---- 工作区：切到 fake-ws（首个 opened——保险起见显式切换）----
    await openPalette();
    await filterPalette("切换到工作区");
    const wsClicked = await clickByText(".palette-item", "切换到工作区：fake-ws", { exact: true });
    check("工作区选择（fake-ws）", wsClicked, "");
    await sleep(700);

    // ---- 检查 1：命令面板出现扩展命令 ----
    await openPalette();
    await filterPalette("扩展");
    const extTitles = await paletteTexts();
    const hasEcho = extTitles.some((t) => t.includes("回声（无参数）"));
    const hasSum = extTitles.some((t) => t.includes("求和"));
    check("命令面板出现扩展命令（回声/求和）", hasEcho && hasSum, extTitles.join(" | "));

    // ---- 检查 2：无参命令直跑 → 结果卡片 ----
    const echoClicked = await clickByText(".palette-item", "回声");
    const echoCard = await waitFor(async () => (await resultText()).includes("echo-ok"), 6000);
    const echoNoErr = await page.evaluate(() =>
      !document.querySelector('[data-st="cmd-result-error"]'));
    check("无参命令直跑 → 结果卡片（echo-ok）", echoClicked && echoCard && echoNoErr, await resultText());
    const echoClosed = await mouseClick('[data-st="cmd-result-close"]');
    check("结果卡片关闭（真实鼠标）", echoClosed
      && await waitFor(async () => await page.evaluate(() =>
        !document.querySelector('[data-st="cmd-result"]')), 3000), "");
    await sleep(250);

    // ---- 检查 3：带参命令 → 逐字段表单（无 JSON 裸输入）→ 提交 → 结果 ----
    await openPalette();
    await filterPalette("求和");
    const sumClicked = await clickByText(".palette-item", "求和");
    const formOpen = await waitFor(async () => await page.evaluate(() =>
      !!document.querySelector('[data-st="cmd-args"]')), 5000);
    const formShape = await page.evaluate(() => {
      const overlay = document.querySelector('[data-st="cmd-args"]');
      return {
        a: !!document.querySelector('[data-st="cmd-arg:a"]'),
        b: !!document.querySelector('[data-st="cmd-arg:b"]'),
        textarea: overlay ? overlay.querySelectorAll("textarea").length : -1,
      };
    });
    check("带参命令 → 逐字段表单（无 JSON 裸输入）",
      sumClicked && formOpen && formShape.a && formShape.b && formShape.textarea === 0,
      JSON.stringify(formShape));
    await mouseClick('[data-st="cmd-arg:a"]');
    await page.type('[data-st="cmd-arg:a"]', "41");
    await mouseClick('[data-st="cmd-args-submit"]');
    const sumCard = await waitFor(async () => (await resultText()).includes("sum=42"), 6000);
    check("参数提交 → 结果（sum=42；b 默认 1 预填）", sumCard, await resultText());
    await mouseClick('[data-st="cmd-result-close"]');
    await sleep(250);

    // ---- 检查 4：必填校验（行内错误、表单不关）----
    await openPalette();
    await filterPalette("求和");
    await clickByText(".palette-item", "求和");
    await waitFor(async () => await page.evaluate(() =>
      !!document.querySelector('[data-st="cmd-args"]')), 5000);
    await mouseClick('[data-st="cmd-args-submit"]');
    const reqErr = await waitFor(async () => await page.evaluate(() => {
      const el = document.querySelector('[data-st="cmd-arg-err:a"]');
      return !!el && (el.textContent || "").trim().length > 0;
    }), 4000);
    const stillOpen = await page.evaluate(() => !!document.querySelector('[data-st="cmd-args"]'));
    check("必填校验（表单不关 + 行内错误）", reqErr && stillOpen, "");
    await mouseClick('[data-st="cmd-args-cancel"]');
    await sleep(250);

    // ---- 检查 5：预设切换（面板条目 + PUT + toast + 当前标记）----
    await openPalette();
    await filterPalette("本会话装配");
    const presetTitles = await paletteTexts();
    const hasE2e = presetTitles.some((t) => t === "本会话装配：e2e");
    const hasDefault = presetTitles.some((t) => t === "本会话装配：跟随默认");
    check("命令面板出现预设条目（e2e + 跟随默认）", hasE2e && hasDefault,
      presetTitles.join(" | "));
    const putBefore = reqs.filter((r) =>
      r.method === "PUT" && r.url.includes("/session-preset")).length;
    await clickByText(".palette-item", "本会话装配：e2e", { exact: true });
    await sleep(800);
    const putHit = reqs.filter((r) => r.method === "PUT"
      && r.url.includes("/session-preset") && r.body.includes("e2e")).length;
    const toast = await page.evaluate(() => {
      const el = document.querySelector('[data-st="toast"]');
      return el && !el.hasAttribute("hidden") ? (el.textContent || "") : "";
    });
    check("预设切换（PUT session-preset + toast）",
      putHit > putBefore && toast.includes("e2e"),
      `put=${putHit}/${putBefore} toast=${toast}`);
    await openPalette();
    await filterPalette("本会话装配");
    const currentMarked = (await paletteTexts()).some((t) =>
      t.includes("e2e") && t.includes("（当前）"));
    check("当前预设标记（（当前））", currentMarked, (await paletteTexts()).join(" | "));
    await page.keyboard.press("Escape");
    await sleep(300);

    // ---- 检查 6：设置「装配」分区（清单/链/描述/损坏 + 两种写入）----
    await openPalette();
    await filterPalette("设置");
    const settingsClicked = await clickByText(".palette-item", "打开设置");
    const settingsOpen = await waitFor(async () => await page.evaluate(() => {
      const o = document.querySelector(".settings-overlay");
      return !!o && !o.hasAttribute("hidden");
    }), 6000);
    check("设置打开（命令面板）", settingsClicked && settingsOpen, "");
    await mouseClick('[data-st="nav:assembly"]');
    const sectionReady = await waitFor(async () => await page.evaluate(() => {
      const el = document.querySelector('[data-st="assembly-session"]');
      if (!el) return false;
      return [...el.querySelectorAll("option")].some((o) => o.value === "e2e");
    }), 8000);
    const secInfo = await page.evaluate(() => {
      const sel = document.querySelector('[data-st="assembly-session"]');
      const opts = sel ? [...sel.querySelectorAll("option")].map((o) => o.value) : [];
      const err = document.querySelector('[data-st="assembly-err:broken"]');
      const body = document.querySelector('[data-st="settings-assembly"]')
        ?.closest(".st-body")?.textContent || "";
      return {
        opts,
        broken: err ? (err.textContent || "").trim() : "",
        hasChain: body.includes("继承链") && body.includes("指纹"),
        hasDesc: body.includes("E2E 演示预设"),
      };
    });
    check("设置「装配」分区（清单/链/描述/损坏可见）",
      sectionReady && secInfo.opts.includes("e2e") && secInfo.opts.includes("broken")
      && secInfo.broken.includes("未知") && secInfo.hasChain && secInfo.hasDesc,
      JSON.stringify(secInfo));
    await page.select('[data-st="assembly-session"]', "lean");
    await sleep(800);
    const leanPut = reqs.filter((r) => r.method === "PUT"
      && r.url.includes("/session-preset") && r.body.includes("lean")).length;
    check("会话绑定选择 → PUT（lean）", leanPut > 0, `n=${leanPut}`);
    await page.select('[data-st="assembly-default"]', "e2e");
    await sleep(1000);
    const cfgPut = reqs.filter((r) => r.method === "PUT"
      && r.url.includes("/api/v1/config") && r.body.includes("assembly_preset"));
    check("全局默认选择 → 配置写入（assembly_preset）",
      cfgPut.some((r) => r.body.includes("e2e")), `n=${cfgPut.length}`);
    const settingsClosed = await mouseClick(".st-head [data-st='close']");
    check("设置关闭（真实鼠标）", settingsClosed && await waitFor(async () =>
      await page.evaluate(() => {
        const o = document.querySelector(".settings-overlay");
        return !o || o.hasAttribute("hidden");
      }), 4000), "");

    // ---- 页面错误与未处理拒绝 ----
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
