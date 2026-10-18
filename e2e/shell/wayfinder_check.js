/* 循迹 v1 断言（双模式批 3）——真实鼠标（1440×900）；两阶段（服务重启恢复双证）。
   用法：
     node wayfinder_check.js --phase=create   # 前置：serve_fake 8833 零态
     # 脚本将 .wuxing + WUXING.md 备份到 fake-ws-keep/ 后退出
     # 重启夹具：FAKE_RESTORE=<e2e/shell/fake-ws-keep> python serve_fake.py 8833
     node wayfinder_check.js --phase=verify   # 断言服务重启后设计态/地图恢复
*/
const puppeteer = require("puppeteer-core");
const path = require("node:path");
const fs = require("node:fs");

const EDGE = process.env.EDGE_PATH ||
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
const URL = process.env.SHELL_URL || "http://127.0.0.60:8833/next/";
const OUT = process.env.OUT_DIR || path.join(__dirname, "visual", "wayfinder");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
fs.mkdirSync(OUT, { recursive: true });

const WS = path.join(__dirname, "fake-ws");
const WUX = path.join(WS, ".wuxing");
const KEEP = path.join(__dirname, "fake-ws-keep");
const PHASE = (process.argv.find((a) => a.startsWith("--phase=")) || "--phase=create")
  .split("=")[1];

const results = [];
function check(name, ok, detail) {
  results.push({ name, ok: !!ok });
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail !== undefined ? "  :: " + JSON.stringify(detail) : ""}`);
}
const readJson = (p) => { try { return JSON.parse(fs.readFileSync(p, "utf8")); } catch { return null; } };

(async () => {
  const browser = await puppeteer.launch({
    executablePath: EDGE, headless: "new",
    args: ["--no-sandbox", "--disable-gpu"],
  });
  const page = await browser.newPage();
  await page.setCacheEnabled(false);
  await page.setViewport({ width: 1440, height: 900, deviceScaleFactor: 1 });
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(URL, { waitUntil: "networkidle2", timeout: 25000 });
  await sleep(1500);

  const waitDom = async (selector, timeoutMs = 10000) => {
    const t0 = Date.now();
    for (;;) {
      const ok = await page.evaluate((sel) => {
        const el = document.querySelector(sel);
        return !!el && !el.hidden && getComputedStyle(el).display !== "none";
      }, selector);
      if (ok) return true;
      if (Date.now() - t0 > timeoutMs) return false;
      await sleep(200);
    }
  };
  const ensureWorkspace = async () => {
    const vis = await page.evaluate(() =>
      !!document.querySelector(".mode-bar") && !document.querySelector(".mode-bar").hidden);
    if (vis) return;
    const wsId = await page.evaluate(async () => {
      const list = await (await fetch("/api/v1/workspaces")).json();
      const ws = list.workspaces.find((w) => w.name === "fake-ws") ?? list.workspaces[0];
      return ws.id;
    });
    await page.click(`[data-st="rail:${wsId}"]`);
    await sleep(1000);
  };
  const cardInfo = () => page.evaluate(() => {
    const card = document.querySelector('[data-st="design-card"]');
    const phase = document.querySelector('[data-st="design-phase"]');
    const round = document.querySelector('[data-st="design-round"]');
    const q0 = document.querySelector('[data-st="design-ticket:Q-1"]');
    return {
      visible: !!card && !card.hidden,
      open: card ? card.classList.contains("open") : false,
      phase: phase?.textContent || "",
      round: round?.textContent || "",
      q0: q0?.textContent || "",
      tickets: document.querySelectorAll('[data-st^="design-ticket:"]').length,
      handoff: !!document.querySelector('[data-st="design-handoff"]'),
      viewMap: !!document.querySelector('[data-st="design-map-open"]'),
    };
  });
  const submitHero = async (text) => {
    await page.click(".hero-text");
    await page.type(".hero-text", text);
    await page.click('[data-st="hero-send"]');
  };
  const submitComposer = async (text) => {
    await page.click(".composer textarea");
    await page.type(".composer textarea", text);
    await page.click('[data-st="composer-send"]');
  };

  await ensureWorkspace();

  if (PHASE === "create") {
    // —— 1. 新建会话选「循迹模式」 ——
    await page.click('[data-st="rail-new-session"]');
    await sleep(800);
    await page.click('[data-st="mode-chip"]');
    await sleep(300);
    await page.click('[data-st="mode-pick:theroad"]');
    await sleep(800);
    const chip = await page.evaluate(() =>
      document.querySelector('[data-st="mode-chip"]')?.textContent || "");
    check("1 新会话选循迹（chip = 循迹模式）", chip.includes("循迹"), chip);

    // —— 2. 提交设计任务 → 闸：待设计状态 + 设计卡片 + 问题清单 ——
    await submitHero("设计一个发布工具");
    const cardVisible = await waitDom('[data-st="design-card"]', 12000);
    await sleep(1200);
    const state = readJson(path.join(WUX, "design-state.json")) || {};
    const card = await cardInfo();
    check("2 设计轮：闸生效（状态=待设计）+ 设计卡片在场",
      cardVisible && card.visible
        && (await page.evaluate(() => document.body.textContent.includes("待设计"))),
      { cardVisible, phase: card.phase });
    check("2b 卡片：阶段=拷问 + 轮次 1",
      card.phase.includes("拷问") && card.round.includes("1"), card);
    check("2b2 卡片：有待答票据 → 默认展开（T9）", card.open === true, card);
    // 2d 手动开合（真实鼠标——点 head 收起 → 再点展开；以展开态结束不扰后续）
    const foldHeadClick = async () => {
      const box = await page.evaluate(() => {
        const el = document.querySelector('[data-st="design-card"] .fold-head');
        if (!el) return null;
        el.scrollIntoView({ block: "center" });
        const r = el.getBoundingClientRect();
        return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) };
      });
      if (!box) return false;
      await page.mouse.click(box.x, box.y);
      return true;
    };
    await foldHeadClick();
    await sleep(400);
    const afterClose = await cardInfo();
    await foldHeadClick();
    await sleep(400);
    const afterOpen = await cardInfo();
    check("2b3 手动开合：收起 → 展开（T9）",
      afterClose.open === false && afterOpen.open === true,
      { afterClose: afterClose.open, afterOpen: afterOpen.open });
    // 2026-10-16：显式开合按钮（入口显著）+ 真实鼠标开合
    const clickFoldToggle = async () => {
      const box = await page.evaluate(() => {
        const el = document.querySelector('[data-st="design-fold-toggle"]');
        if (!el) return null;
        el.scrollIntoView({ block: "center" });
        const r = el.getBoundingClientRect();
        return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) };
      });
      if (!box) return false;
      await page.mouse.click(box.x, box.y);
      return true;
    };
    const hasFoldBtn = await page.evaluate(() =>
      !!document.querySelector('[data-st="design-fold-toggle"]'));
    check("2b4 显式开合按钮在场（2026-10-16）", hasFoldBtn, "");
    if (hasFoldBtn) {
      await clickFoldToggle();
      await sleep(400);
      const closedViaBtn = await cardInfo();
      await clickFoldToggle();
      await sleep(400);
      const openViaBtn = await cardInfo();
      check("2b5 开合按钮：收起 → 展开（真实鼠标）",
        closedViaBtn.open === false && openViaBtn.open === true,
        { closed: closedViaBtn.open, open: openViaBtn.open });
    }
    check("2c 卡片：决策票据 Q-1（含推荐答案）",
      card.q0.includes("Q-1") && card.q0.includes("目标平台")
        && card.q0.includes("推荐"), card.q0);
    check("2d fs 双证：design-state.json（grilling/round=1/票据 2）",
      state.phase === "grilling" && state.round === 1
        && (state.questions || []).length === 2
        && (state.decision_tickets || []).length === 2
        && state.next_ticket === 3,
      { phase: state.phase, round: state.round,
        q: (state.questions || []).length,
        t: (state.decision_tickets || []).length, next: state.next_ticket });
    check("2e 闸：未进入执行管线（无 WUXING.md、无新产物）",
      !fs.existsSync(path.join(WS, "WUXING.md"))
        && !fs.existsSync(path.join(WUX, "task_state.json")), "");
    const session = String(state.session || "");
    await page.screenshot({ path: path.join(OUT, "wf-design.png") });

    // —— 2f（2026-10-16）：采用推荐可加可退（行级 toggle） ——
    const composerValue = () => page.evaluate(() =>
      document.querySelector(".composer textarea")?.value || "");
    await page.click('[data-st="design-ticket-use:Q-1"]');
    await sleep(400);
    const applied = await composerValue();
    check("2f 采用推荐：追加「回答：…」行",
      applied.includes("回答：Windows"), applied);
    const btnLabel = await page.evaluate(() =>
      document.querySelector('[data-st="design-ticket-use:Q-1"]')?.textContent || "");
    check("2f2 按钮切为「取消采用推荐」",
      btnLabel.includes("取消采用推荐"), btnLabel);
    await page.click('[data-st="design-ticket-use:Q-1"]');
    await sleep(400);
    const reverted = await composerValue();
    check("2f3 取消采用：精确回退该行",
      reverted.trim() === "" && !reverted.includes("回答：Windows"), reverted);
    // 恢复采用后继续既有提交流程（真实键鼠）
    await page.click('[data-st="design-ticket-use:Q-1"]');
    await sleep(300);
    await page.evaluate(() => {
      const t = document.querySelector(".composer textarea");
      if (t) { t.value = ""; t.dispatchEvent(new Event("input", { bubbles: true })); }
    });
    await submitComposer("回答：采用推荐");
    const decReady = async () => {
      const mp = path.join(WS, "WUXING.md");
      if (!fs.existsSync(mp)) return false;
      return fs.readFileSync(mp, "utf8").includes("[D-1]");
    };
    const t1 = Date.now();
    while (!(await decReady()) && Date.now() - t1 < 12000) await sleep(300);
    await sleep(1000);
    const mapText1 = fs.existsSync(path.join(WS, "WUXING.md"))
      ? fs.readFileSync(path.join(WS, "WUXING.md"), "utf8") : "";
    const state2 = readJson(path.join(WUX, "design-state.json")) || {};
    check("2g 决策入地图（[D-1] + 来源 Q-1）+ 票据即弃",
      mapText1.includes("[D-1]") && mapText1.includes("来源：Q-1")
        && state2.branch_head === "D-1"
        && (state2.decision_tickets || []).length === 1,
      { branch: state2.branch_head,
        t: (state2.decision_tickets || []).length,
        hasD: mapText1.includes("[D-1]") });

    // —— 2h/2i（批 3）：写规格 → 落盘 + 卡片规格行 + 查看链接 ——
    await submitComposer("写规格");
    const specReady = async () => {
      const dir = path.join(WUX, "specs");
      return fs.existsSync(dir)
        && fs.readdirSync(dir).some((f) => f.endsWith(".md"));
    };
    const t2 = Date.now();
    while (!(await specReady()) && Date.now() - t2 < 12000) await sleep(300);
    await sleep(1200);
    const specsDir = path.join(WUX, "specs");
    const specFile = fs.existsSync(specsDir)
      ? fs.readdirSync(specsDir).filter((f) => f.endsWith(".md"))[0] : "";
    const specText = specFile
      ? fs.readFileSync(path.join(specsDir, specFile), "utf8") : "";
    const state3 = readJson(path.join(WUX, "design-state.json")) || {};
    check("2h 规格落盘（七段受控格式 + design-state 指针）",
      specText.includes("## Problem Statement")
        && specText.includes("## Testing Decisions")
        && !!state3.spec_slug,
      { file: specFile, slug: state3.spec_slug });
    const specRow = await page.evaluate(() => {
      const row = document.querySelector('[data-st="design-spec-status"]');
      const link = document.querySelector('[data-st="design-spec-open"]');
      return { text: row?.textContent || "",
               href: link?.getAttribute("href") || "" };
    });
    check("2i 卡片规格行 + 查看规格链接（artifact 路径）",
      specRow.text.includes("规格") && specRow.href.includes(".wuxing/specs"),
      specRow);

    // —— 2j/2k（批 4）：提票据 → 卡片票据区；发布 → tickets.jsonl ready ——
    await submitComposer("提票据");
    const tkReady = async () => fs.existsSync(path.join(WUX, "tickets.jsonl"));
    const t3 = Date.now();
    while (!(await tkReady()) && Date.now() - t3 < 12000) await sleep(300);
    await sleep(1200);
    const tkText = fs.existsSync(path.join(WUX, "tickets.jsonl"))
      ? fs.readFileSync(path.join(WUX, "tickets.jsonl"), "utf8") : "";
    const tkRow = await page.evaluate(() =>
      document.querySelector('[data-st="design-impl-ticket:T-1"]')?.textContent || "");
    check("2j 票据提议：卡片 T-1 在场 + jsonl proposed",
      tkRow.includes("T-1") && tkText.includes('"proposed"')
        && tkText.includes("切片一"), tkRow);
    await page.click('[data-st="design-tickets-publish"]');
    await sleep(1500);
    const tkText2 = fs.readFileSync(path.join(WUX, "tickets.jsonl"), "utf8");
    const tkRow2 = await page.evaluate(() =>
      document.querySelector('[data-st="design-impl-ticket:T-1"]')?.textContent || "");
    check("2k 发布票据：jsonl ready + 卡片已发布（双证）",
      tkText2.includes('"ready"') && tkRow2.includes("已发布"),
      { row: tkRow2 });

    // —— 3. 提交「写地图」→ 地图落盘 + 卡片阶段=地图 + 交给执行 ——
    await submitComposer("写地图");
    const mapReady = async () => fs.existsSync(path.join(WS, "WUXING.md"));
    const t0 = Date.now();
    while (!mapReady() && Date.now() - t0 < 12000) await sleep(300);
    await sleep(1200);
    const mapText = fs.existsSync(path.join(WS, "WUXING.md"))
      ? fs.readFileSync(path.join(WS, "WUXING.md"), "utf8") : "";
    const card2 = await cardInfo();
    check("3 WUXING.md 落盘（目的地/路线/决策在场）",
      mapText.includes("完成发布工具 v1") && mapText.includes("## 路线")
        && mapText.includes("决策记录"), mapText.slice(0, 60));
    check("3b 卡片：阶段=地图 + 「交给执行」在场",
      card2.phase.includes("地图") && card2.handoff, card2);

    // —— 3c（批 5）：执行票据 → 票据回写 done（夹具回放 + jsonl 双证） ——
    await submitComposer("执行票据");
    const tkDone = async () => {
      const p = path.join(WUX, "tickets.jsonl");
      return fs.existsSync(p)
        && fs.readFileSync(p, "utf8").includes('"done"');
    };
    const t4 = Date.now();
    while (!(await tkDone()) && Date.now() - t4 < 12000) await sleep(300);
    await sleep(800);
    const tkText3 = fs.readFileSync(path.join(WUX, "tickets.jsonl"), "utf8");
    check("3c 票据编排：执行回写 done（jsonl 双证）",
      tkText3.includes('"done"'), tkText3.slice(-120));

    // —— 4. 地图只读视图（查看地图） ——
    await page.click('[data-st="design-map-open"]');
    const mapShown = await waitDom('[data-st="map-view"]', 8000);
    const mapBody = await page.evaluate(() =>
      document.querySelector('[data-st="map-view"]')?.textContent || "");
    check("4 地图视图：只读渲染（目的地/路线文案在场）",
      mapShown && mapBody.includes("目的地") && mapBody.includes("完成发布工具"),
      mapBody.slice(0, 80));
    await page.click('[data-st="map-close"]');
    await sleep(400);
    await page.screenshot({ path: path.join(OUT, "wf-map.png") });

    // —— 5. 恢复双证 A：重开会话（磁盘重读） ——
    await page.click('[data-st="rail-session:conversation-1710000100.jsonl"]');
    await sleep(1200);
    await page.click(`[data-st="rail-session:${session}"]`);
    await sleep(1500);
    const card3 = await cardInfo();
    check("5 恢复 A（重开会话）：阶段=地图 从磁盘恢复",
      card3.visible && card3.phase.includes("地图"), card3);

    // —— 6. 备份（服务重启双证用）——逐文件复制（Windows：cpSync 拷被占用目录会静默杀进程） ——
    fs.rmSync(KEEP, { recursive: true, force: true });
    fs.mkdirSync(path.join(KEEP, ".wuxing"), { recursive: true });
    const copyFile = (src, dest) => {
      fs.writeFileSync(dest, fs.readFileSync(src));
    };
    if (fs.existsSync(path.join(WUX, "tickets.jsonl"))) {
      copyFile(path.join(WUX, "tickets.jsonl"),
               path.join(KEEP, ".wuxing", "tickets.jsonl"));
    }
    copyFile(path.join(WUX, "design-state.json"),
             path.join(KEEP, ".wuxing", "design-state.json"));
    copyFile(path.join(WUX, session),
             path.join(KEEP, ".wuxing", session));
    copyFile(path.join(WUX, "session-modes.json"),
             path.join(KEEP, ".wuxing", "session-modes.json"));
    copyFile(path.join(WS, "WUXING.md"), path.join(KEEP, "WUXING.md"));
    check("6 备份完成（design-state + 会话文件 + 模式侧车 + WUXING.md）",
      fs.existsSync(path.join(KEEP, ".wuxing", "design-state.json"))
        && fs.existsSync(path.join(KEEP, ".wuxing", session))
        && fs.existsSync(path.join(KEEP, ".wuxing", "session-modes.json"))
        && fs.existsSync(path.join(KEEP, "WUXING.md")), session);
  }

  if (PHASE === "verify") {
    // —— 7. 服务重启后（FAKE_RESTORE）：设计态/地图恢复 ——
    const state = readJson(path.join(WUX, "design-state.json")) || {};
    const session = String(state.session || "");
    check("7 重启恢复：design-state.json 在场（phase=map）",
      session !== "" && state.phase === "map",
      { session, phase: state.phase });
    await page.click(`[data-st="rail-session:${session}"]`);
    await sleep(1500);
    const card = await cardInfo();
    check("7b 重启恢复：设计卡片恢复（阶段=地图 + 交接按钮）",
      card.visible && card.phase.includes("地图") && card.handoff, card);
    const keepHash = fs.existsSync(path.join(KEEP, "WUXING.md"))
      ? fs.readFileSync(path.join(KEEP, "WUXING.md"), "utf8") : "";
    const nowHash = fs.existsSync(path.join(WS, "WUXING.md"))
      ? fs.readFileSync(path.join(WS, "WUXING.md"), "utf8") : "";
    check("7c 重启恢复：WUXING.md 内容与备份一致",
      keepHash !== "" && keepHash === nowHash, keepHash.slice(0, 60));
    await page.click('[data-st="design-map-open"]');
    const mapShown = await waitDom('[data-st="map-view"]', 8000);
    const mapBody = await page.evaluate(() =>
      document.querySelector('[data-st="map-view"]')?.textContent || "");
    check("7d 重启恢复：地图视图可开（内容在场）",
      mapShown && mapBody.includes("完成发布工具"), "");
    await page.click('[data-st="map-close"]');
    await page.screenshot({ path: path.join(OUT, "wf-restored.png") });
  }

  check("8 无 pageerror", errors.length === 0, errors.slice(0, 2));

  const failed = results.filter((r) => !r.ok);
  console.log(`\n${failed.length === 0 ? "✔" : "✘"} wayfinder[${PHASE}] 断言 ` +
    `${results.length - failed.length}/${results.length}` +
    (failed.length ? "；失败：" + failed.map((f) => f.name).join("；") : ""));
  await browser.close();
  process.exit(failed.length === 0 && errors.length === 0 ? 0 : 1);
})();
