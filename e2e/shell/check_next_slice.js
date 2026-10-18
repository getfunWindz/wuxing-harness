/* P1b 切片端到端（假引擎）：settle 揭示 / 工作区 chips / 提交 / 流式行 / 结果。
   用法：python e2e/shell/serve_fake.py 8830
        SHELL_URL=http://127.0.0.60:8830/next/ node e2e/shell/check_next_slice.js
   全过退出 0；任一失败退出 1。

   踩坑沿用（见 check_ui_fixes.js）：任务窗口内不要高频轮询（CDP 伪影）——
   提交后固定等待再读取。 */
const puppeteer = require("puppeteer-core");

const EDGE = process.env.EDGE_PATH ||
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
const URL = process.env.SHELL_URL || "http://127.0.0.60:8830/next/";
const SHOT = process.env.SHOT_PATH || require("path").join(__dirname, "visual", "next_slice.png");
require("fs").mkdirSync(require("path").dirname(SHOT), { recursive: true });
const CREATE_WS = require("path").resolve(__dirname, "next-tmp-ws").replace(/\\/g, "/");
require("fs").mkdirSync(CREATE_WS, { recursive: true });

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
  const requested = [];
  page.on("request", (req) => { requested.push(req.url()); });
  // E0-1（2026-10-02）：任务/确认请求失败必须在日志可见（此前 409 busy 级联静默——
  // 勾选丢点遗留待确认门 → 后续所有提交被拒，日志无提示）
  page.on("response", (res) => {
    const path = res.url().replace(/^https?:\/\/[^/]+/, "").split("?")[0];
    if ((/\/tasks$|\/confirm$/.test(path)) && res.status() >= 400) {
      console.log(`WARN 任务请求失败 ${res.status()} ${path}`);
    }
  });
  await page.evaluateOnNewDocument(() => {
    window.__rej = [];
    window.addEventListener("unhandledrejection", (ev) => {
      window.__rej.push(String((ev.reason && ev.reason.stack) || ev.reason));
    });
  });
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  // 命中验证：报告遮挡（防「点了个空」静默失效——M3 教训：溢出内容被右栏宿主遮挡）
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
      hit: hit ? `${hit.tagName}.${hit.className === "" ? "(none)" : hit.className}|${hit.getAttribute("data-st") || ""}` : "null",
    };
  }, selector);
  const mouseClick = async (selector) => {
    let box = await probeBox(selector);
    if (!box) return false;
    if (!box.ok) {
      await sleep(200);
      box = await probeBox(selector);
    }
    if (!box || !box.ok) {
      // E0-1（2026-10-02）：粘性顶栏部分覆盖时，改试元素内多个候选点（仍为真实鼠标）
      box = await page.evaluate((sel) => {
        const el = document.querySelector(sel);
        if (!el) return null;
        el.scrollIntoView({ block: "center" });
        const r = el.getBoundingClientRect();
        for (const fy of [0.5, 0.3, 0.75]) {
          for (const fx of [0.5, 0.25, 0.75]) {
            const x = Math.round(r.x + r.width * fx), y = Math.round(r.y + r.height * fy);
            const hit = document.elementFromPoint(x, y);
            if (hit && (hit === el || el.contains(hit))) return { x, y, ok: true };
          }
        }
        const x = Math.round(r.x + r.width / 2), y = Math.round(r.y + r.height / 2);
        const hit = document.elementFromPoint(x, y);
        return { x, y, ok: false,
                 hit: hit ? `${hit.tagName}.${hit.className === "" ? "(none)" : hit.className}` : "null" };
      }, selector);
    }
    if (!box || !box.ok) {
      console.log(`WARN mouseClick(${selector}) 被遮挡：${box ? box.hit : "element-gone"}`);
      return false;
    }
    await page.mouse.move(box.x, box.y);
    await sleep(60);
    await page.mouse.click(box.x, box.y);
    return true;
  };
  // 稳定点击（设置页异步重渲染会移动按钮——探针连续两次一致才点）
  const stableClick = async (selector) => {
    let prev = null;
    for (let i = 0; i < 5; i++) {
      const box = await probeBox(selector);
      if (!box) return false;
      if (prev && box.ok && Math.abs(box.x - prev.x) < 2 && Math.abs(box.y - prev.y) < 2) {
        await page.mouse.move(box.x, box.y);
        await sleep(60);
        await page.mouse.click(box.x, box.y);
        return true;
      }
      prev = box;
      await sleep(200);
    }
    return false;
  };
  // E0-1（2026-10-02）：确认卡勾选校验+重试（合成点击偶发丢点——滚动/重渲染竞态；
  // 幂等：只补点未勾选项，计数与批量条文案达标即返回）
  const ensureConfirmSelection = async (ids, expected) => {
    for (let attempt = 0; attempt < 5; attempt++) {
      const state = await page.evaluate((want) => {
        const box = (id) => document.querySelector(`[data-st="confirm-check:${id}"]`);
        return {
          checked: want.filter((id) => box(id)?.checked === true),
          info: document.querySelector('[data-st="confirm-batch-info"]')?.textContent || "",
        };
      }, ids);
      if (state.checked.length === expected && state.info.includes(`已选 ${expected}`)) {
        return true;
      }
      if (attempt > 0) {
        console.log(`WARN 勾选未达标（${state.checked.length}/${expected}）重试 ${attempt}：${state.info}`);
      }
      for (const id of ids) {
        if (!state.checked.includes(id)) {
          await mouseClick(`[data-st="confirm-check:${id}"]`);
          await sleep(150);
        }
      }
      await sleep(150);
    }
    return false;
  };
  const clickByText = async (selector, text) => {
    const box = await page.evaluate((sel, want) => {
      const el = [...document.querySelectorAll(sel)].find((e) => (e.textContent || "").includes(want));
      if (!el) return null;
      el.scrollIntoView({ block: "center" });
      const r = el.getBoundingClientRect();
      return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) };
    }, selector, text);
    if (!box) return false;
    await page.mouse.move(box.x, box.y);
    await sleep(60);
    await page.mouse.click(box.x, box.y);
    return true;
  };

  await page.goto(URL.replace(/\/next\/?$/, "/"), { waitUntil: "domcontentloaded" });
  await sleep(1500);

  // P2-M8：根路径直达新壳（/ → 302 /next/）——旧栈删除后 / 不再提供旧前端
  check("P2-M8 根路径直达新壳（/ → /next/）", page.url().includes("/next/"), page.url());
  // 旧栈判定 = 根路径下的 /theme/、/js/、/index.html（新壳资产在 /next/ 前缀下，不算）
  const oldAssets = requested.filter((u) => {
    try {
      const path = new URL(u).pathname;
      return path.startsWith("/theme/") || path.startsWith("/js/") || path === "/index.html";
    } catch {
      return false;
    }
  });
  check("P2-M8 无旧栈资源请求", oldAssets.length === 0, oldAssets.join("|"));

  const state = await page.evaluate(() => document.body.dataset.state);
  check("settle 后揭示（data-state=ready）", state === "ready", `state=${state}`);

  const heroInfo = await page.evaluate(() => ({
    visible: (() => { const el = document.querySelector(".hero"); return !!(el && el.offsetParent !== null); })(),
    logo: !!document.querySelector(".hero-logo svg"),
    brand: document.querySelector(".hero-brand .brand-mark")?.textContent || "",
    examples: [...document.querySelectorAll(".hero-examples .chip-btn")].map((el) => el.textContent || ""),
    composerHidden: (() => { const el = document.querySelector(".cbox"); return !el || el.offsetParent === null; })(),
  }));
  check("A8 欢迎页（大 LOGO + 品牌 + 示例 chips；hero-mode 隐藏输入区）",
        heroInfo.visible && heroInfo.logo && heroInfo.brand.includes("无形")
        && heroInfo.examples.length >= 1 && heroInfo.composerHidden,
        JSON.stringify(heroInfo));

  const firstField = await page.evaluate(() => {
    const vis = (s) => { const el = document.querySelector(s); return !!(el && el.offsetParent !== null); };
    return vis(".hero-text") ? ".hero-text" : ".cbox textarea";
  });
  await page.click(firstField);
  await page.type(firstField, "P1b 切片冒烟");
  await page.keyboard.press("Enter");

  // 状态到达语义：轮询等待完成（固定 sleep 在负载下会采样到中间态）
  const waitForMeta = async (text, timeoutMs = 12000) => {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      const cur = await page.evaluate(() => document.querySelector(".stream-meta")?.textContent ?? "");
      if (cur.includes(text)) return true;
      await sleep(250);
    }
    return false;
  };
  await waitForMeta("完成");
  const meta = await page.evaluate(() =>
    document.querySelector(".stream-meta")?.textContent ?? "");
  const rows = await page.evaluate(() =>
    [...document.querySelectorAll(".unit-card")].map((el) => el.textContent));
  const report = await page.evaluate(() =>
    document.querySelector(".stream-report")?.textContent ?? "");

  check("出现 F-1 单元卡", rows.some((row) => row.includes("F-1")), rows.join(" | "));
  const cardStyle = await page.evaluate(() => {
    const c = document.querySelector(".unit-card");
    if (!c) return null;
    const cs = getComputedStyle(c);
    return { minH: cs.minHeight, radius: cs.borderRadius, cursor: cs.cursor };
  });
  check("A4 碎片卡（min-height 108 / 圆角 12 / 可点）",
        !!cardStyle && cardStyle.minH === "108px" && cardStyle.radius === "12px"
        && cardStyle.cursor === "pointer", JSON.stringify(cardStyle));
  // 点击展开（跨全宽 + 详情面板）
  // 轮次化（2026-09-21）：完成态过程组默认收起——先展开过程组，再点击碎片卡
  // E2E 加固（2026-09-30）：展开是异步渲染——先确认卡片已可见（尺寸 > 0），
  // 否则未展开时探测到 0 尺寸坐标 (0,0) → 被顶栏 app-top 假遮挡（历史抖动根因）。
  const cardVisible = async () => await page.evaluate(() => {
    const el = document.querySelector('[data-st^="unit:"]');
    if (!el || el.offsetParent === null) return false;
    return el.getBoundingClientRect().height > 0;
  });
  await mouseClick('[data-st="process-summary"]');
  await sleep(300);
  if (!(await cardVisible())) {
    await mouseClick('[data-st="process-summary"]');   // 首次未生效 → 重试一次
    await sleep(300);
  }
  let cardVis = false;
  for (let i = 0; i < 12 && !cardVis; i += 1) {
    cardVis = await cardVisible();
    if (!cardVis) await sleep(200);
  }
  await mouseClick('[data-st^="unit:"]');
  await sleep(400);
  const expanded = await page.evaluate(() => {
    const c = document.querySelector(".unit-card.expanded");
    if (!c) return null;
    const cs = getComputedStyle(c);
    const detail = c.querySelector(".frag-detail");
    return {
      colSpan: cs.gridColumnStart + "/" + cs.gridColumnEnd,
      detailVisible: detail ? getComputedStyle(detail).display : "none",
    };
  });
  check("A4 碎片卡点击放大（跨全宽 + 详情展开）",
        !!expanded && expanded.colSpan === "1/-1" && expanded.detailVisible === "block",
        JSON.stringify(expanded));
  const spanStyles = await page.evaluate(() => {
    const pick = (s) => { const el = document.querySelector(s); if (!el) return null; const cs = getComputedStyle(el); return cs.gridColumnStart + "/" + cs.gridColumnEnd; };
    return { result: pick(".result-card"), think: pick(".think-block") };
  });
  check("A4 全宽卡（结果/思维链 1/-1）",
        spanStyles.result === "1/-1" && (spanStyles.think === null || spanStyles.think === "1/-1"),
        JSON.stringify(spanStyles));

  // A10 安全拦截卡 + FSC 提示行（M7 挂账 B 关闭）
  const safetyInfo = await page.evaluate(() => {
    const card = document.querySelector(".stream-card.safety-card");
    const cmd = card ? card.querySelector(".sf-cmd")?.textContent || "" : "";
    const cs = card ? getComputedStyle(card) : null;
    const fsc = [...document.querySelectorAll(".stream-grid .notice-row")].map((e) => e.textContent || "");
    return {
      card: !!card,
      cmd,
      borderLeft: cs ? `${cs.borderLeftWidth} ${cs.borderLeftStyle}` : "",
      fsc,
    };
  });
  check("A10 安全拦截卡（流内 + 左 3px 红边 + 命令块）",
        safetyInfo.card && safetyInfo.cmd.includes("rm -rf build/") && safetyInfo.borderLeft === "3px solid",
        JSON.stringify(safetyInfo));
  check("A10 FSC 提示行（审查 + 切换）",
        safetyInfo.fsc.some((s) => s.includes("审查")) && safetyInfo.fsc.some((s) => s.includes("切换")),
        safetyInfo.fsc.join("|"));
  check("状态显示完成", meta.includes("完成"), meta);
  check("结果含 mock 报告", report.includes("mock 报告"), report.slice(0, 40));
  check("无 pageerror", pageErrors.length === 0, pageErrors.join("; "));

  // ---- P2 左栏骨架（工作区列表/切换/收起动画） ----
  const railNames = await page.evaluate(() =>
    [...document.querySelectorAll(".rail-item .rail-name")].map((e) => e.textContent || ""));
  check("P2 左栏工作区列表", railNames.length >= 2, railNames.join(","));

  await clickByText(".rail-item", "fake-ws2");
  await sleep(900);
  const switched = await page.evaluate(() => ({
    rail: document.querySelector(".rail-item.active .rail-name")?.textContent || "",
    heroVisible: (() => { const el = document.querySelector(".hero"); return !!(el && el.offsetParent !== null); })(),
  }));
  check("P2 左栏切换工作区（rail 同步 + 空工作区回欢迎页）",
    switched.rail.includes("fake-ws2") && switched.heroVisible, JSON.stringify(switched));

  await mouseClick(String.raw`[data-st="rail-collapse"]`);
  await sleep(600);
  const railCollapsed = await page.evaluate(() => ({
    cls: document.querySelector(".rail")?.className || "",
    width: Math.round(document.querySelector(".rail")?.getBoundingClientRect().width || 0),
    mini: document.querySelectorAll(".rail-mini-ws").length,
  }));
  check("P2 左栏收起（48px + 迷你工作区入口）",
    railCollapsed.cls.includes("collapsed") && railCollapsed.width === 48 && railCollapsed.mini >= 2,
    JSON.stringify(railCollapsed));

  await mouseClick(".rail-toggle-mini");
  await sleep(600);
  const railExpanded = await page.evaluate(() => document.querySelector(".rail")?.className || "");
  check("P2 左栏展开恢复", !railExpanded.includes("collapsed"), railExpanded);

  // ---- P2 右栏 dock（三视图 + 收起工具栏） ----
  const dockTabs = await page.evaluate(() =>
    [...document.querySelectorAll(".dock-tab")].map((e) => e.textContent || ""));
  check("P2 dock 六视图入口（产物/技能/MCP/回收站/会话/通知）",
    dockTabs.length === 6 && dockTabs.some((txt) => txt.includes("通知")), dockTabs.join(","));

  await clickByText(".dock-tab", "技能");
  await sleep(1000);
  const skillNames = await page.evaluate(() =>
    [...document.querySelectorAll(".dock-item-main")].map((e) => e.textContent || ""));
  check("P2 dock 技能视图（服务端事实）", skillNames.some((n) => n.includes("find-skill")), skillNames.join("|"));

  await clickByText(".dock-tab", "MCP");
  await sleep(1000);
  const mcpNames = await page.evaluate(() =>
    [...document.querySelectorAll(".dock-item-main")].map((e) => e.textContent || ""));
  check("P2 dock MCP 视图（服务端事实）", mcpNames.some((n) => n.includes("demo-mcp")), mcpNames.join("|"));

  await mouseClick(".dock-toggle");
  await sleep(600);
  const dockCollapsed = await page.evaluate(() => ({
    cls: document.querySelector(".dock")?.className || "",
    width: Math.round(document.querySelector(".dock")?.getBoundingClientRect().width || 0),
    tools: document.querySelectorAll(".dock-tool").length,
  }));
  check("P2 dock 收起（48px + 工具栏）",
    dockCollapsed.cls.includes("collapsed") && dockCollapsed.width === 48 && dockCollapsed.tools >= 4,
    JSON.stringify(dockCollapsed));

  await mouseClick(".dock-tool");
  await sleep(600);
  const dockExpanded = await page.evaluate(() => document.querySelector(".dock")?.className || "");
  check("P2 dock 展开恢复", !dockExpanded.includes("collapsed"), dockExpanded);

  // ---- P2 顶栏（属性卡 + ＋菜单：新建工作区） ----
  const stats = await page.evaluate(() =>
    [...document.querySelectorAll(".u-item")].map((e) => e.textContent || ""));
  check("P2 顶栏使用信息（默认四属性：并发/工作区/缓存/上下文）",
    stats.length >= 2 && stats.some((s) => s.includes("工作区")) && stats.some((s) => s.includes("并发")),
    stats.join("|"));

  await mouseClick('[data-st="rail-add"]');
  await sleep(400);
  const menuItems = await page.evaluate(() =>
    [...document.querySelectorAll(".topbar-menu-item")].map((e) => e.textContent || ""));
  check("P2 ＋菜单打开", menuItems.some((m) => m.includes("新建工作区")), menuItems.join("|"));

  // 新建工作区主路径：系统文件夹选择（2026-09-19；夹具桩返回目录）
  await mouseClick('[data-st="menu-new-ws"]');
  await sleep(1600);
  const pickedFact = await page.evaluate(async () =>
    (await (await fetch("/api/v1/workspaces")).json()).workspaces.map((w) => w.name));
  check("P2 新建工作区（文件夹选择 → 建出工作区）",
    pickedFact.some((n) => n.includes("picked-ws")), pickedFact.join("|"));

  // 手输回退路径（旧弹窗能力保留）
  await mouseClick('[data-st="rail-add"]');
  await sleep(400);
  await mouseClick('[data-st="menu-new-ws-typed"]');
  await sleep(500);
  const dialogOpen = await page.evaluate(() =>
    document.querySelector('.topbar-dialog [data-st="new-ws-path"]') !== null);
  check("P2 新建工作区弹窗（手输回退）", dialogOpen === true);

  await page.type('[data-st="new-ws-path"]', CREATE_WS);
  await mouseClick('[data-st="new-ws-ok"]');
  await sleep(1800);
  const dialogErr = await page.evaluate(() =>
    document.querySelector(".topbar-dialog .st-err")?.textContent || "");
  const wsFact = await page.evaluate(async () =>
    (await (await fetch("/api/v1/workspaces")).json()).workspaces.map((w) => w.name));
  const railAfter = await page.evaluate(() =>
    [...document.querySelectorAll(".rail-item .rail-name")].map((e) => e.textContent || ""));
  check("P2 新建工作区（服务端 + 左栏双证）",
    wsFact.some((n) => n.includes("next-tmp-ws")) && railAfter.some((n) => n.includes("next-tmp-ws")),
    JSON.stringify({ wsFact, railAfter, dialogErr }));

  // ---- P2 回收站（dock 视图：归档 → 恢复 双证） ----
  const wsId = await page.evaluate(async () => {
    const list = await (await fetch("/api/v1/workspaces")).json();
    const hit = list.workspaces.find((w) => (w.name || "").includes("next-tmp-ws"));
    return hit ? hit.id : null;
  });
  await page.evaluate(async (id) => {
    await fetch(`/api/v1/workspaces/${id}/archive`, {
      method: "POST",
      headers: { "X-Wuxing": "1", "Content-Type": "application/json" },
      body: JSON.stringify({ state: "archived" }),
    });
  }, wsId);
  await sleep(1000);
  await clickByText(".dock-tab", "回收站");
  await sleep(1300);
  const rcNames = await page.evaluate(() =>
    [...document.querySelectorAll(".dock-item-main")].map((e) => e.textContent || ""));
  check("P2 回收站视图（归档条目）", rcNames.some((n) => n.includes("next-tmp-ws")), rcNames.join("|"));

  await clickByText(".dock-item .st-btn", "恢复");
  await sleep(1800);
  const afterRestore = await page.evaluate(async () => ({
    ws: (await (await fetch("/api/v1/workspaces")).json()).workspaces.map((w) => w.name),
    rc: (await (await fetch("/api/v1/recycle")).json()).entries.map((e) => e.name),
  }));
  check("P2 回收站恢复（服务端双证）",
    afterRestore.ws.some((n) => n.includes("next-tmp-ws"))
      && !afterRestore.rc.some((n) => n.includes("next-tmp-ws")),
    JSON.stringify(afterRestore));

  // ---- P2-M1 剩余：行菜单（复制/关闭） + 文件夹全流程 ----
  const wsId2 = await page.evaluate(async () => {
    const list = await (await fetch("/api/v1/workspaces")).json();
    const hit = list.workspaces.find((w) => (w.name || "").includes("next-tmp-ws"));
    return hit ? hit.id : null;
  });

  await mouseClick(`[data-st="rail-more:${wsId2}"]`);
  await sleep(300);
  await mouseClick(`[data-st="rail-menu:copy:${wsId2}"]`);
  await sleep(500);
  const noticeText = await page.evaluate(() => {
    const n = document.querySelector(".app-notice");
    return n !== null && !n.hasAttribute("hidden") ? n.textContent || "" : "";
  });
  check("P2-M1 复制路径（通知可见）", noticeText.includes("已复制路径"), noticeText);

  await mouseClick('[data-st="rail-add"]');
  await sleep(350);
  await mouseClick('[data-st="menu-new-folder"]');
  await sleep(400);
  await page.type('[data-st="prompt-input"]', "审计夹");
  await mouseClick('[data-st="prompt-ok"]');
  await sleep(1200);
  const folders = await page.evaluate(async () => {
    const list = await (await fetch("/api/v1/workspaces")).json();
    return { names: list.folders.map((f) => f.name), id: (list.folders.find((f) => f.name === "审计夹") || {}).id || "" };
  });
  check("P2-M1 新建文件夹（服务端 + 左栏）", folders.names.includes("审计夹"), JSON.stringify(folders));

  await mouseClick(`[data-st="rail-more:${wsId2}"]`);
  await sleep(300);
  await mouseClick(`[data-st="rail-menu:move:${wsId2}:${folders.id}"]`);
  await sleep(1200);
  const moved = await page.evaluate(async () => {
    const list = await (await fetch("/api/v1/workspaces")).json();
    const ws = list.workspaces.find((w) => (w.name || "").includes("next-tmp-ws"));
    const folder = list.folders.find((f) => f.name === "审计夹");
    return { folderId: (ws && ws.folder) || "", folderTarget: folder ? folder.id : "" };
  });
  check("P2-M1 移入文件夹（服务端事实）",
    moved.folderId !== "" && moved.folderId === moved.folderTarget, JSON.stringify(moved));

  await mouseClick(`[data-st="rail-folder-more:${moved.folderTarget}"]`);
  await sleep(300);
  await mouseClick(`[data-st="rail-menu:folder-rename:${moved.folderTarget}"]`);
  await sleep(400);
  await page.keyboard.down("Control");
  await page.keyboard.press("a");
  await page.keyboard.up("Control");
  await page.type('[data-st="prompt-input"]', "审计夹改");
  await mouseClick('[data-st="prompt-ok"]');
  await sleep(1200);
  const renamed = await page.evaluate(async () =>
    (await (await fetch("/api/v1/workspaces")).json()).folders.map((f) => f.name));
  check("P2-M1 重命名文件夹（服务端）", renamed.includes("审计夹改"), JSON.stringify(renamed));

  await mouseClick(`[data-st="rail-folder-more:${moved.folderTarget}"]`);
  await sleep(300);
  await mouseClick(`[data-st="rail-menu:folder-delete:${moved.folderTarget}"]`);
  await sleep(300);
  await mouseClick(`[data-st="rail-menu:folder-delete-ok:${moved.folderTarget}"]`);
  await sleep(1200);
  const afterDel = await page.evaluate(async () =>
    (await (await fetch("/api/v1/workspaces")).json()).folders.map((f) => f.name));
  check("P2-M1 删除文件夹（服务端）", !afterDel.includes("审计夹改"), JSON.stringify(afterDel));

  await mouseClick(`[data-st="rail-more:${wsId2}"]`);
  await sleep(300);
  await mouseClick(`[data-st="rail-menu:close:${wsId2}"]`);
  await sleep(1400);
  const closed = await page.evaluate(async () => ({
    ws: (await (await fetch("/api/v1/workspaces")).json()).workspaces.map((w) => w.name),
    rc: (await (await fetch("/api/v1/recycle")).json()).entries.map((e) => e.name),
  }));
  check("P2-M1 关闭工作区（移出列表 + 无回收站记录）",
    !closed.ws.some((n) => n.includes("next-tmp-ws")) && !closed.rc.some((n) => n.includes("next-tmp-ws")),
    JSON.stringify(closed));

  // ---- P2-M2 会话视图（列表/重命名/导出） ----
  await clickByText(".dock-tab", "会话");
  await sleep(1300);
  const sessNames = await page.evaluate(() =>
    [...document.querySelectorAll(".dock-item-main")].map((e) => ({
      text: e.textContent || "", title: e.getAttribute("title") || "",
    })));
  check("P2-M2 会话列表（LLM 标题显示 / 文件名保留在提示）",
    sessNames.some((r) => r.text.includes("变更摘要会话") || r.text.includes("conversation")),
    JSON.stringify(sessNames));

  await mouseClick('[data-st^="sess-rename:"]');
  await sleep(400);
  await page.keyboard.down("Control");
  await page.keyboard.press("a");
  await page.keyboard.up("Control");
  await page.type('[data-st="prompt-input"]', "conversation-renamed.jsonl");
  await mouseClick('[data-st="prompt-ok"]');
  await sleep(1500);
  const sessFact = await page.evaluate(async () => {
    const list = await (await fetch("/api/v1/workspaces")).json();
    const active = document.querySelector(".rail-item.active .rail-name")?.textContent || "";
    const ws = list.workspaces.find((w) => w.name === active) || list.workspaces[0];
    const sessions = await (await fetch(`/api/v1/workspaces/${ws.id}/sessions`)).json();
    return { names: sessions.sessions.map((s) => s.name), ws: ws.name };
  });
  check("P2-M2 重命名会话（服务端事实）",
    sessFact.names.includes("conversation-renamed.jsonl")
      && !sessFact.names.includes("conversation-1710000000.jsonl"),
    JSON.stringify(sessFact));

  const exportStatus = await page.evaluate(async () => {
    const list = await (await fetch("/api/v1/workspaces")).json();
    const active = document.querySelector(".rail-item.active .rail-name")?.textContent || "";
    const ws = list.workspaces.find((w) => w.name === active) || list.workspaces[0];
    const r = await fetch(`/api/v1/workspaces/${ws.id}/sessions/conversation-renamed.jsonl/export?format=md`);
    return r.status;
  });
  check("P2-M2 导出端点可用（200）", exportStatus === 200, String(exportStatus));

  // 清理：会话列表回到初始（避免影响下次运行）——夹具启动会重置状态文件，无需处理

  // ---- P2-M3 确认门（单条批准/理由驳回 + 批量 + 失败可见；UI + 服务端双证） ----
  await clickByText(".rail-item", "fake-ws");
  await sleep(900);

  const waitFor = async (fn, timeoutMs = 10000) => {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      if (await fn()) return true;
      await sleep(250);
    }
    return false;
  };
  // E0-1（2026-10-02）：关键点击「校验效果 + 重试」（合成点击偶发丢点；有界重试）
  const clickUntil = async (selector, predicate, attempts = 3, waitMs = 2000) => {
    for (let i = 0; i < attempts; i++) {
      await mouseClick(selector);
      if (await waitFor(predicate, waitMs)) return true;
      if (i < attempts - 1) console.log(`WARN clickUntil(${selector}) 未生效——重试 ${i + 1}`);
    }
    return false;
  };
  const submitTask = async (text) => {
    // E0-1（2026-10-02）：提交需校验（焦点/键入/回车丢点会静默失联）——
    // 以「输入区被清空」为受理信号；未受理则重试一次。
    for (let attempt = 0; attempt < 2; attempt++) {
      const sel = await page.evaluate(() => {
        const vis = (s) => { const el = document.querySelector(s); return !!(el && el.offsetParent !== null); };
        return vis(".hero-text") ? ".hero-text" : ".cbox textarea";
      });
      await page.click(sel);
      await page.type(sel, text);
      await page.keyboard.press("Enter");
      const accepted = await waitFor(async () => await page.evaluate(() => {
        const cbox = document.querySelector(".cbox textarea");
        const hero = document.querySelector(".hero-text");
        const el = (cbox && cbox.offsetParent !== null) ? cbox : hero;
        return !el || el.value === "";
      }), 1500);
      if (accepted) return true;
      console.log(`WARN submitTask("${text}") 未被受理——重试 ${attempt + 1}`);
    }
    return false;
  };
  const readLog = () => JSON.parse(require("fs").readFileSync(
    require("path").resolve(__dirname, "fake-ws/confirm_log.json"), "utf8"));
  const snapshotOf = () => page.evaluate(async () => {
    const list = await (await fetch("/api/v1/workspaces")).json();
    const active = document.querySelector(".rail-item.active .rail-name")?.textContent || "";
    const ws = list.workspaces.find((w) => w.name === active) || list.workspaces[0];
    return await (await fetch(`/api/v1/workspaces/${ws.id}/snapshot`)).json();
  });
  const confirmRowCount = () => page.evaluate(() =>
    document.querySelectorAll(".stream-confirm-row").length);

  // 场景一：单条批准 + 单条驳回（理由必填）
  await submitTask("执行待确认步骤");
  const pendingSeen = await waitFor(async () => (await confirmRowCount()) === 2);
  const batchVisible = await page.evaluate(() => {
    const b = document.querySelector(".stream-batch");
    return b !== null && !b.hasAttribute("hidden");
  });
  check("P2-M3 待确认列表（2 卡 + 批量条）", pendingSeen && batchVisible,
    `rows=${pendingSeen} batch=${batchVisible}`);

  await mouseClick('[data-st="confirm-reject:C-2"]');
  await sleep(250);
  const rejectGuarded = await page.evaluate(() => ({
    bad: document.querySelector('[data-st="confirm-reason:C-2"]')?.classList.contains("bad") ?? false,
    rows: document.querySelectorAll(".stream-confirm-row").length,
  }));
  check("P2-M3 驳回理由必填（空理由不提交）",
    rejectGuarded.bad && rejectGuarded.rows === 2, JSON.stringify(rejectGuarded));

  const approveSeal = await page.evaluate(() => {
    const btn = document.querySelector('[data-st="confirm-approve:C-1"]');
    const seal = btn ? btn.querySelector(".seal-stamp") : null;
    if (!seal) return null;
    const cs = getComputedStyle(seal);
    return { text: seal.textContent || "", color: cs.color, bg: cs.backgroundColor,
             border: cs.borderTopColor, pos: cs.position };
  });
  check("A4 确认卡批准按钮印章（红字透明底 + 悬浮）",
        !!approveSeal && approveSeal.text === "无形"
        && approveSeal.color === "rgb(165, 63, 51)"
        && approveSeal.bg === "rgba(0, 0, 0, 0)"
        && approveSeal.pos === "absolute", JSON.stringify(approveSeal));

  const approvedSeen = await clickUntil('[data-st="confirm-approve:C-1"]', async () =>
    await page.evaluate(() =>
      (document.querySelector('[data-st="confirm-resolved:C-1"]')?.textContent || "").includes("已批准")));
  const afterApprove = await page.evaluate(() => ({
    rows: document.querySelectorAll(".stream-confirm-row").length,
    batchHidden: document.querySelector(".stream-batch")?.hasAttribute("hidden") ?? true,
  }));
  const approveServer = await waitFor(async () =>
    (await snapshotOf()).pending_confirms.length === 1);
  const logApprove = readLog().at(-1);
  check("P2-M3 单条批准（已决反馈 + 批量条隐藏）",
    approvedSeen && afterApprove.rows === 1 && afterApprove.batchHidden,
    JSON.stringify(afterApprove));
  check("P2-M3 单条批准（服务端 pending 余 1 + 日志透传）",
    approveServer
      && JSON.stringify(logApprove) === JSON.stringify({ items: [["C-1", true]], reason: "" }),
    JSON.stringify(logApprove));

  let rejectedSeen = false;
  for (let attempt = 0; attempt < 3 && !rejectedSeen; attempt++) {
    await page.click('[data-st="confirm-reason:C-2"]', { clickCount: 3 });
    await page.type('[data-st="confirm-reason:C-2"]', "不完整");
    await mouseClick('[data-st="confirm-reject:C-2"]');
    rejectedSeen = await waitFor(async () => await page.evaluate(() =>
      (document.querySelector('[data-st="confirm-resolved:C-2"]')?.textContent || "").includes("已驳回")), 2000);
  }
  const rejectServer = await waitFor(async () => {
    const snap = await snapshotOf();
    return snap.pending_confirms.length === 0 && snap.result?.status === "failed";
  });
  const resultTitle = await page.evaluate(() =>
    document.querySelector(".rl-main")?.textContent || "");
  const logReject = readLog().at(-1);
  check("P2-M3 单条驳回（已决理由 + 任务失败）",
    rejectedSeen && resultTitle.includes("失败"), `${rejectedSeen} | ${resultTitle}`);
  check("P2-M3 单条驳回（服务端 pending 空 + 理由落盘）",
    rejectServer && logReject?.reason === "不完整" && logReject?.items?.[0]?.[1] === false,
    JSON.stringify(logReject));

  // 场景二：批量批准（勾选两卡）
  await submitTask("再跑待确认步骤");
  await waitFor(async () => (await confirmRowCount()) === 2);
  await ensureConfirmSelection(["C-1", "C-2"], 2);
  const batchInfoText = await page.evaluate(() =>
    document.querySelector('[data-st="confirm-batch-info"]')?.textContent || "");
  const batchResolved = await clickUntil('[data-st="confirm-batch-approve"]', async () =>
    await page.evaluate(() =>
      document.querySelectorAll("[data-st^='confirm-resolved:']").length >= 2));
  const batchServerDone = await waitFor(async () =>
    (await snapshotOf()).result?.status === "done");
  check("P2-M3 批量批准（已选计数 + 双卡已决 + 服务端 done）",
    batchInfoText.includes("已选 2") && batchResolved && batchServerDone,
    JSON.stringify({ batchInfoText, batchResolved, batchServerDone }));

  // 场景三：批量驳回（理由必填 + 透传）
  await submitTask("三跑待确认步骤");
  await waitFor(async () => (await confirmRowCount()) === 2);
  // 时序硬化（批 2 观察）：批次勾选与终态刷新可能相邻——卡重建会丢勾选态；
  // 每次勾选后留出稳定窗口（真实用户节奏本就慢于合成点击）。
  await ensureConfirmSelection(["C-1", "C-2"], 2);
  let batchRejectServer = false;
  for (let attempt = 0; attempt < 3 && !batchRejectServer; attempt++) {
    await page.click('[data-st="confirm-batch-reason"]', { clickCount: 3 });
    await page.type('[data-st="confirm-batch-reason"]', "plan-incomplete");
    await mouseClick('[data-st="confirm-batch-reject"]');
    batchRejectServer = await waitFor(async () => {
      const snap = await snapshotOf();
      return snap.pending_confirms.length === 0 && snap.result?.status === "failed";
    }, 2500);
  }
  const logBatchReject = readLog().at(-1);
  const batchRejectUI = await page.evaluate(() =>
    [...document.querySelectorAll("[data-st^='confirm-resolved:']")].map((e) => e.textContent || ""));
  check("P2-M3 批量驳回（理由透传 + 服务端 failed）",
    batchRejectServer && logBatchReject?.reason === "plan-incomplete"
      && logBatchReject?.items?.length === 2
      && logBatchReject.items.every((pair) => pair[1] === false)
      && batchRejectUI.length === 2 && batchRejectUI.every((t) => t.includes("已驳回")),
    JSON.stringify({ log: logBatchReject, ui: batchRejectUI }));

  // 场景四：确认失败可见（引擎异常 → confirm_error 事件）
  await submitTask("确认失败任务");
  await waitFor(async () => (await confirmRowCount()) === 1);
  const errSeen = await clickUntil('[data-st="confirm-approve:FU-1"]', async () =>
    await page.evaluate(() =>
      (document.querySelector(".error-card .card-body p")?.textContent || "").includes("确认处理失败")), 3, 2500);
  check("P2-M3 确认失败可见（confirm_error 事件）", errSeen,
    await page.evaluate(() => document.querySelector(".error-card .card-body p")?.textContent || "(无)"));

  // ---- P2-M4 默认视图集（2026-09-19：通知默认入列；其余观测默认关） ----
  const defaultDockTabs = await page.evaluate(() =>
    [...document.querySelectorAll(".dock-tab")].map((e) => e.textContent || ""));
  check("P2-M4 默认六视图（含通知；其余观测默认关）", defaultDockTabs.length === 6
    && defaultDockTabs.some((t2) => t2.includes("通知")),
    defaultDockTabs.join(","));

  // ---- P2 设置：模型与供应商 + 机制调优（真实鼠标 + 服务端双证） ----

  await mouseClick('[data-st="open-settings"]');
  await sleep(900);
  const overlayOpen = await page.evaluate(() => {
    const o = document.querySelector(".settings-overlay");
    return o !== null && !o.hasAttribute("hidden");
  });
  check("P2 设置打开（overlay 可见）", overlayOpen === true);

  // 真实形状化无凭据引导（默认开 + 凭据沙盒空 → 机制调优提示行）
  await mouseClick('[data-st="nav:mechanism"]');
  await sleep(600);
  const shapeHint = await page.evaluate(() => {
    const el = document.querySelector('[data-st="hint:use_real_shape"]');
    return el ? (el.textContent || "") : "";
  });
  check("P2 真实形状化无凭据提示（机制调优）",
        shapeHint.includes("默认模型不可用"), shapeHint);

  // A11 设置中心样式（两域横排 / 侧栏 / 行式字段 / 胶囊开关 / 默认值提示）
  const settInfo = await page.evaluate(() => {
    const card = document.querySelector(".settings-card");
    const nav = document.querySelector(".st-nav");
    const field = document.querySelector(".st-field");
    const sw = document.querySelector(".sw") || document.querySelector('[data-st^="field:"]');
    const cs = card ? getComputedStyle(card) : null;
    const ns = nav ? getComputedStyle(nav) : null;
    const fs = field ? getComputedStyle(field) : null;
    const ws = sw ? getComputedStyle(sw) : null;
    return {
      dir: cs ? cs.flexDirection : "",
      width: cs ? cs.width : "",
      vw: window.innerWidth,
      navW: ns ? ns.width : "",
      navBg: ns ? ns.backgroundColor : "",
      fieldBorder: fs ? fs.borderBottomWidth : "",
      swSize: ws ? `${ws.width}x${ws.height}` : "",
      hint: [...document.querySelectorAll(".st-field .st-hint")]
        .map((e) => e.textContent || "").join("|"),
    };
  });
  check("A11 设置中心（两域横排 / 侧栏 210 / 行式字段 / 胶囊开关 38×21 / 默认值提示）",
        settInfo.dir === "row" && parseInt(settInfo.width, 10) >= 700
        && settInfo.navW === "210px" && settInfo.fieldBorder === "1px"
        && settInfo.swSize === "38pxx21px" && settInfo.hint.includes("默认"),
        JSON.stringify(settInfo));
  await mouseClick('[data-st="nav:model"]');
  await sleep(600);

  const providerNames = await page.evaluate(() =>
    [...document.querySelectorAll(".st-provider-name")].map((e) => e.textContent || ""));
  check("P2 供应商行渲染（演示供应商）", providerNames.some((n) => n.includes("演示供应商")), providerNames.join(","));

  // 供应商卡开合（键盘激活：异步重渲染下命中测试会抖动；服务端双证仍是硬断言）
  const activate = async (selector) => {
    const ok = await page.evaluate((sel) => {
      const el = document.querySelector(sel);
      if (!el) return false;
      (el.closest("button") || el).focus();
      return true;
    }, selector);
    if (!ok) return false;
    await page.keyboard.press("Enter");
    return true;
  };
  const toggleProvider = async () => {
    const open = () => page.evaluate(() => !!document.querySelector(".st-provider-card"));
    for (let i = 0; i < 3; i++) {
      await activate(".st-provider-name");
      await sleep(350);
      if (await open()) return true;
    }
    return false;
  };
  const activateByText = async (selector, text) => {
    const ok = await page.evaluate((sel, want) => {
      const el = [...document.querySelectorAll(sel)].find((e) => (e.textContent || "").includes(want));
      if (!el) return false;
      el.focus();
      return true;
    }, selector, text);
    if (!ok) return false;
    await page.keyboard.press("Enter");
    return true;
  };

  await toggleProvider();
  await sleep(200);
  const fields = await page.evaluate(() => ({
    name: !!document.querySelector('.st-provider-card [data-st^="name:"]'),
    url: !!document.querySelector('.st-provider-card [data-st^="url:"]'),
    key: !!document.querySelector('.st-provider-card [data-st^="key:"]'),
  }));
  check("P2 供应商卡四字段（名称/base_url/密钥）", fields.name && fields.url && fields.key, JSON.stringify(fields));

  await page.type('.st-provider-card [data-st^="key:"]', "sk-e2e-next");
  await activate('.st-provider-card [data-st^="save:"]');
  await sleep(1600);
  const cred = await page.evaluate(async () =>
    await (await fetch("/api/v1/credentials/DEMO_PROVIDER_API_KEY")).json());
  check("P2 保存密钥（服务端 configured）", cred.configured === true, JSON.stringify(cred));

  // 保存后卡片收起 → 重新展开（鼠标/键盘自动重试）
  await toggleProvider();
  await sleep(200);
  await activate('.st-provider-card [data-st^="fetch:"]');
  await waitFor(async () => await page.evaluate(() =>
    document.querySelectorAll(".st-pick-item").length === 3), 6000);
  const picks = await page.evaluate(() =>
    [...document.querySelectorAll(".st-pick-item span")].map((e) => e.textContent || ""));
  check("P2 获取可用模型（选择器 3 项）", picks.length === 3, picks.join("|"));
  await activateByText(".st-picker button", "全选");
  await activateByText(".st-picker button", "添加所选");
  await waitFor(async () => await page.evaluate(() => !document.querySelector(".st-picker")), 4000);
  await sleep(300);
  await activate('.st-provider-card [data-st^="save:"]');
  await sleep(1600);
  const cfg = await page.evaluate(async () => await (await fetch("/api/v1/config")).json());
  const models = (((cfg.values.providers || {})["demo-provider"] || {}).models) || [];
  check("P2 模型落盘（服务端事实 3 项）", models.length === 3, JSON.stringify(models));

  // U9 后默认模型 select 的 data-st 为 model-default（withDataSt 覆写；旧 model-select 已失效）
  await page.select('.settings-card select[data-st="model-default"]', "demo-provider/demo-model-alpha");
  await sleep(1300);
  const llm = await page.evaluate(async () =>
    (await (await fetch("/api/v1/config")).json()).values.llm);
  check("P2 默认模型写入（provider/model）", llm === "demo-provider/demo-model-alpha", String(llm));

  await clickByText(".st-nav-item", "机制调优");
  await sleep(600);
  await mouseClick('[data-st="field:sandbox_enabled"]');
  await sleep(1300);
  const sandbox = await page.evaluate(async () =>
    (await (await fetch("/api/v1/config")).json()).values.sandbox_enabled);
  check("P2 沙箱开关写入（机制调优）", sandbox === false, String(sandbox));

  await clickByText(".st-nav-item", "外观与语言");
  await sleep(600);
  await page.select('[data-st="lang"]', "en");
  await sleep(800);
  const navEn = await page.evaluate(() =>
    [...document.querySelectorAll(".st-nav-item")].map((e) => e.textContent || ""));
  check("P2 语言切换（English）", navEn.some((n) => n.includes("Model & providers")), navEn.join("|"));
  await page.select('[data-st="lang"]', "zh");
  await sleep(800);
  const navZh = await page.evaluate(() =>
    [...document.querySelectorAll(".st-nav-item")].map((e) => e.textContent || ""));
  check("P2 语言切回（中文）", navZh.some((n) => n.includes("模型与供应商")), navZh.join("|"));

  // ---- P2-M4 dock 观测视图（设置自选开启 → 只读双证） ----
  await mouseClick('[data-st="nav:appearance"]');
  await sleep(400);
  for (const view of ["tasks", "usage", "provenance", "log", "brain", "reports"]) {   // notifications 已默认开（2026-09-19）
    await mouseClick(`[data-st="dock-view:${view}"]`);
    await sleep(120);
  }
  const checkedViews = await page.evaluate(() =>
    [...document.querySelectorAll("[data-st^='dock-view:']")].filter((el) => el.checked).length);
  check("P2-M4 右栏视图多选（十二项全勾）", checkedViews === 12, String(checkedViews));

  await mouseClick('[data-st="close"]');
  await sleep(600);
  const allTabs = await page.evaluate(() =>
    [...document.querySelectorAll(".dock-tab")].map((e) => e.textContent || ""));
  check("P2-M4 启用后 tabs=12", allTabs.length === 12, allTabs.join(","));

  const openDock = async (id) => {
    await mouseClick(`[data-st="dock-tab:${id}"]`);
    await sleep(900);
  };

  // 任务视图：UI 行 = /tasks/history 双证
  await openDock("tasks");
  const taskViewTexts = await page.evaluate(() =>
    [...document.querySelectorAll(".dock-body .dock-item-main")].map((e) => e.textContent || ""));
  const historyTexts = await page.evaluate(async () => {
    const list = await (await fetch("/api/v1/workspaces")).json();
    const active = document.querySelector(".rail-item.active .rail-name")?.textContent || "";
    const ws = list.workspaces.find((w) => w.name === active) || list.workspaces[0];
    const hist = await (await fetch(`/api/v1/workspaces/${ws.id}/tasks/history`)).json();
    return hist.history.map((h) => h.task_text);
  });
  check("P2-M4 任务视图 = 历史双证",
    historyTexts.length > 0 && taskViewTexts.some((row) => row.includes(historyTexts[0])),
    JSON.stringify({ server: historyTexts.slice(0, 2), ui: taskViewTexts.slice(0, 3) }));

  // 使用视图：先行一任务 → 行 = snapshot.metrics 双证
  await submitTask("M4 使用数据示例");
  await waitFor(async () => await page.evaluate(() =>
    (document.querySelector(".rl-main")?.textContent || "").includes("完成")));
  await openDock("usage");
  const usageKv = await page.evaluate(() =>
    [...document.querySelectorAll(".dock-kv")].map((e) => e.textContent || ""));
  const metricsFact = await page.evaluate(async () => {
    const list = await (await fetch("/api/v1/workspaces")).json();
    const active = document.querySelector(".rail-item.active .rail-name")?.textContent || "";
    const ws = list.workspaces.find((w) => w.name === active) || list.workspaces[0];
    const snap = await (await fetch(`/api/v1/workspaces/${ws.id}/snapshot`)).json();
    return snap.result?.metrics ?? null;
  });
  check("P2-M4 使用视图 = snapshot.metrics 双证",
    metricsFact !== null && usageKv.some((row) => row.includes(String(metricsFact.llm_calls)))
      && usageKv.some((row) => row.includes("75.0%")),
    JSON.stringify({ calls: metricsFact && metricsFact.llm_calls, rows: usageKv.length }));

  // 溯源视图：种子 → 树 + 单元点击展开链路
  await openDock("provenance");
  const provUnits = await page.evaluate(() =>
    [...document.querySelectorAll("[data-st^='prov-unit:']")].map((e) => e.textContent || ""));
  check("P2-M4 溯源树 = provenance.jsonl 双证（≥2——种子随轮次化扩展）",
    provUnits.length >= 2 && provUnits[0].includes("P-1") && provUnits[1].includes("P-2"),
    provUnits.join("|"));
  await mouseClick('[data-st="prov-unit:P-1"]');
  await sleep(900);
  const traceText = await page.evaluate(() =>
    document.querySelector('[data-st="prov-trace"]')?.textContent || "");
  check("P2-M4 单元链路展开（trace 端点）", traceText.includes("unit_start"), traceText.slice(0, 60));

  // 报告视图：种子 docs/报告.md → 列表 + 内容路由 200
  await openDock("reports");
  const reportNames = await page.evaluate(() =>
    [...document.querySelectorAll(".dock-report .dock-item-main")].map((e) => e.textContent || ""));
  const reportHttp = await page.evaluate(async () => {
    const list = await (await fetch("/api/v1/workspaces")).json();
    const active = document.querySelector(".rail-item.active .rail-name")?.textContent || "";
    const ws = list.workspaces.find((w) => w.name === active) || list.workspaces[0];
    const r = await fetch(`/api/v1/workspaces/${ws.id}/artifacts/${encodeURI("docs/报告.md")}`);
    return r.status;
  });
  check("P2-M4 报告视图 = docs 双证",
    reportNames.some((n) => n.includes("报告")) && reportHttp === 200,
    JSON.stringify({ reportNames, reportHttp }));

  // A10 报告内嵌渲染（report-md；M7 挂账 C）
  await mouseClick('[data-st^="report:"]');
  await sleep(700);
  const reportMd = await page.evaluate(() => {
    const root = document.querySelector('[data-st="report-modal"]');
    const md = root ? root.querySelector(".report-md") : null;
    const cs = md ? getComputedStyle(md) : null;
    return {
      open: !!root,
      headings: md ? [...md.querySelectorAll("h3,h4,h5,h6")].map((e) => e.textContent || "") : [],
      items: md ? md.querySelectorAll("li").length : 0,
      font: cs ? `${cs.fontSize}/${cs.lineHeight}` : "",
    };
  });
  check("A10 报告内嵌渲染（report-md 标题/列表/13px·1.75）",
        reportMd.open && reportMd.headings.length >= 1 && reportMd.items >= 1
        && reportMd.font.startsWith("13px") && reportMd.font.includes("22.75px"),
        JSON.stringify(reportMd));
  await page.keyboard.press("Escape");
  await sleep(300);

  // 通知 / 日志：事件积累后的只读列表
  await openDock("notifications");
  const noticeCount = await page.evaluate(() =>
    document.querySelectorAll(".dock-body .dock-item").length);
  const notifFact = await page.evaluate(async () =>
    (await (await fetch("/api/v1/notifications?since=0&limit=100")).json()).items.length);
  check("P2-M4 通知视图 = /notifications 双证", noticeCount > 0 && notifFact > 0,
    `ui=${noticeCount} server=${notifFact}`);
  await openDock("log");
  const logCount = await page.evaluate(() => document.querySelectorAll(".dock-log-row").length);
  check("P2-M4 日志视图（事件日志行）", logCount > 0, String(logCount));

  // 智脑视图（夹具无 brain_memory.json → 空案例态）
  await openDock("brain");
  const brainBody = await page.evaluate(() => document.querySelector(".dock-body")?.textContent || "");
  check("P2-M4 智脑视图（空案例态）",
    brainBody.includes("暂无案例") && brainBody.includes("0 / 500"), brainBody.slice(0, 60));

  // 取消勾选 → tab 消失 + 激活视图回退首个启用视图
  await mouseClick('[data-st="open-settings"]');
  await sleep(800);
  await mouseClick('[data-st="nav:appearance"]');
  await sleep(400);
  await mouseClick('[data-st="dock-view:brain"]');
  await sleep(300);
  await mouseClick('[data-st="close"]');
  await sleep(600);
  const tabsAfterOff = await page.evaluate(() =>
    [...document.querySelectorAll(".dock-tab")].map((e) => e.textContent || ""));
  const activeTab = await page.evaluate(() =>
    document.querySelector(".dock-tab.on")?.textContent || "");
  check("P2-M4 取消勾选 → tab 消失 + 回退首个启用视图",
    tabsAfterOff.length === 11 && !tabsAfterOff.includes("智脑") && activeTab === "产物",
    JSON.stringify({ tabs: tabsAfterOff.length, activeTab }));

  // ---- P2-M5 技能管理（安装→详情→卸载 双证） ----
  await openDock("skills");
  const skTools = await page.evaluate(() => ({
    install: !!document.querySelector('[data-st="sk-install"]'),
    discover: !!document.querySelector('[data-st="sk-discover"]'),
  }));
  const skillNames0 = await page.evaluate(() =>
    [...document.querySelectorAll("[data-st^='skill:'] .dock-item-main")].map((e) => e.textContent || ""));
  check("P2-M5 技能视图（工具行 + 内置清单）",
    skTools.install && skTools.discover && skillNames0.includes("find-skill"),
    JSON.stringify({ skTools, skillNames0 }));

  await mouseClick('[data-st="sk-install"]');
  await sleep(400);
  // A9（v43-⑦）：表单预校验——非法输入在提交前拦截（不进入二次确认）
  await page.type('[data-st="sk-name"]', "Bad Name");
  await page.type('[data-st="sk-content"]', "---\nname: bad\n---\n内容");
  await mouseClick('[data-st="sk-save"]');
  await sleep(250);
  const preInvalid = await page.evaluate(() => ({
    err: document.querySelector('[data-st="sk-error"]')?.textContent || "",
    armed: !!document.querySelector('[data-st="sk-save-ok"]'),
  }));
  check("A9 安装预校验（非法 kebab 名拦截，不进入确认）",
    preInvalid.err.includes("kebab-case") && !preInvalid.armed, JSON.stringify(preInvalid));

  await page.click('[data-st="sk-name"]');
  await page.keyboard.down("Control");
  await page.keyboard.press("a");
  await page.keyboard.up("Control");
  await page.type('[data-st="sk-name"]', "demo-skill");
  await page.click('[data-st="sk-content"]');
  await page.keyboard.down("Control");
  await page.keyboard.press("a");
  await page.keyboard.up("Control");
  await page.type('[data-st="sk-content"]', "---\nname: other-name\n---\n演示内容");
  await mouseClick('[data-st="sk-save"]');
  await sleep(250);
  const preMismatch = await page.evaluate(() => ({
    err: document.querySelector('[data-st="sk-error"]')?.textContent || "",
    armed: !!document.querySelector('[data-st="sk-save-ok"]'),
  }));
  check("A9 安装预校验（frontmatter 名不一致拦截）",
    preMismatch.err.includes("不一致") && !preMismatch.armed, JSON.stringify(preMismatch));

  await page.click('[data-st="sk-content"]');
  await page.keyboard.down("Control");
  await page.keyboard.press("a");
  await page.keyboard.up("Control");
  await page.type('[data-st="sk-content"]', "无 frontmatter 内容");
  await mouseClick('[data-st="sk-save"]');
  await sleep(250);
  const preNoFm = await page.evaluate(() => ({
    err: document.querySelector('[data-st="sk-error"]')?.textContent || "",
    armed: !!document.querySelector('[data-st="sk-save-ok"]'),
  }));
  check("A9 安装预校验（缺 frontmatter 拦截）",
    preNoFm.err.includes("frontmatter") && !preNoFm.armed, JSON.stringify(preNoFm));

  await page.click('[data-st="sk-content"]');
  await page.keyboard.down("Control");
  await page.keyboard.press("a");
  await page.keyboard.up("Control");
  await page.type('[data-st="sk-content"]', "---\nname: demo-skill\ndescription: 演示技能\n---\n演示内容");
  await page.type('[data-st="sk-desc"]', "演示技能");
  await mouseClick('[data-st="sk-save"]');
  await sleep(300);
  const armed = await page.evaluate(() => !!document.querySelector('[data-st="sk-save-ok"]'));
  await mouseClick('[data-st="sk-save-ok"]');
  const installedSeen = await waitFor(async () => await page.evaluate(() =>
    [...document.querySelectorAll("[data-st^='skill:'] .dock-item-main")].map((e) => e.textContent || "").includes("demo-skill")));
  const skillsServer = await page.evaluate(async () =>
    (await (await fetch("/api/v1/skills")).json()).skills.map((s) => s.name));
  check("P2-M5 安装技能（二次确认 + 服务端清单双证）",
    armed && installedSeen && skillsServer.includes("demo-skill"),
    JSON.stringify({ armed, installedSeen, skillsServer }));

  await mouseClick('[data-st="skill:demo-skill"]');
  await sleep(700);
  const detailInfo = await page.evaluate(() => ({
    content: document.querySelector('[data-st="sk-content-view"]')?.textContent || "",
    remove: !!document.querySelector('[data-st="sk-remove"]'),
  }));
  check("P2-M5 技能详情（正文 + 卸载入口）",
    detailInfo.content.includes("演示内容") && detailInfo.remove, JSON.stringify(detailInfo));

  await mouseClick('[data-st="skill:find-skill"]');
  await sleep(700);
  const builtinInfo = await page.evaluate(() => ({
    remove: !!document.querySelector('[data-st="sk-remove"]'),
    badge: document.querySelector(".dock-badge")?.textContent || "",
  }));
  check("P2-M5 内置技能只读（无卸载按钮 + 徽标）",
    !builtinInfo.remove && builtinInfo.badge.includes("内置"), JSON.stringify(builtinInfo));

  const toolsInfo = await page.evaluate(() => ({
    tools: document.querySelector('[data-st="sk-tools"]')?.textContent || "",
    warn: document.querySelector('[data-st="sk-tools-warn"]')?.textContent || "",
  }));
  check("A14 技能依赖工具展示（声明 + 白名单警示）",
    toolsInfo.tools.includes("read_file") && toolsInfo.warn.includes("nonexistent_tool"),
    JSON.stringify(toolsInfo));

  await mouseClick('[data-st="skill:demo-skill"]');
  await sleep(700);
  await mouseClick('[data-st="sk-remove"]');
  await sleep(300);
  const removeArmed = await page.evaluate(() => !!document.querySelector('[data-st="sk-remove-ok"]'));
  await mouseClick('[data-st="sk-remove-ok"]');
  const removedSeen = await waitFor(async () => await page.evaluate(() =>
    ![...document.querySelectorAll("[data-st^='skill:'] .dock-item-main")].map((e) => e.textContent || "").includes("demo-skill")));
  const skillsServerAfter = await page.evaluate(async () =>
    (await (await fetch("/api/v1/skills")).json()).skills.map((s) => s.name));
  check("P2-M5 卸载技能（两步确认 + 服务端清单双证）",
    removeArmed && removedSeen && !skillsServerAfter.includes("demo-skill"),
    JSON.stringify({ removeArmed, removedSeen, skillsServerAfter }));

  await mouseClick('[data-st="sk-discover"]');
  await sleep(400);
  await page.type('[data-st="sk-goal"]', "为任务写测试");
  await mouseClick('[data-st="sk-discover-run"]');
  const foundSeen = await waitFor(async () => await page.evaluate(() =>
    !!document.querySelector("[data-st^='sk-found:']")));
  const foundText = await page.evaluate(() =>
    document.querySelector("[data-st^='sk-found:']")?.textContent || "");
  check("P2-M5 在线发现（结果行）", foundSeen && foundText.includes("radar-demo"), foundText);

  // ---- P2-M5 MCP 管理（状态 + 重载） ----
  await openDock("mcp");
  const mcpInfo = await page.evaluate(() => ({
    command: document.querySelector(".dock-body .dock-item-meta")?.textContent || "",
    chips: [...document.querySelectorAll(".dock-chip")].map((e) => e.textContent || ""),
    reload: !!document.querySelector('[data-st="mcp-reload"]'),
  }));
  check("P2-M5 MCP 状态（命令/工具 chips + 重载入口）",
    mcpInfo.command.includes("npx") && mcpInfo.chips.includes("search") && mcpInfo.reload,
    JSON.stringify(mcpInfo));

  await mouseClick('[data-st="mcp-reload"]');
  const reloadNotice = await waitFor(async () => await page.evaluate(() =>
    (document.querySelector('[data-st="mcp-notice"]')?.textContent || "").includes("已重载")));
  check("P2-M5 MCP 重载（busy → 结果可见）", reloadNotice,
    await page.evaluate(() => document.querySelector('[data-st="mcp-notice"]')?.textContent || "(无)"));

  // ---- P2-M6 主视图细节（思维链/产物/恢复动作/搜索/面板/徽标/参考文件） ----
  await submitTask("M6 主视图示例");
  const thinkSeen = await waitFor(async () => await page.evaluate(() =>
    !!document.querySelector("[data-st^='think:']")), 15000);
  const thinkText = await page.evaluate(() =>
    document.querySelector(".think-body")?.textContent || "");
  check("P2-M6 思维链块（unit_reasoning）",
    thinkSeen && thinkText.includes("先查看仓库结构"),
    JSON.stringify({ thinkSeen, thinkText: thinkText.slice(0, 42) }));

  const tile = await (async () => {
    let out = null;
    await waitFor(async () => {
      out = await page.evaluate(() => {
        const a = document.querySelector('[data-st^="artifact:"]');
        return a ? { text: a.textContent || "", href: a.getAttribute("href") || "" } : null;
      });
      return out !== null;
    }, 8000);
    return out;
  })();
  const artifactHttp = await page.evaluate(async () => {
    const list = await (await fetch("/api/v1/workspaces")).json();
    const active = document.querySelector(".rail-item.active .rail-name")?.textContent || "";
    const ws = list.workspaces.find((w) => w.name === active) || list.workspaces[0];
    const r = await fetch(`/api/v1/workspaces/${ws.id}/artifacts/${encodeURI("artifacts/报告.md")}`);
    return r.status;
  });
  check("P2-M6 产物链接（tile + 内容路由 200 双证）",
    tile !== null && tile.href.includes("/artifacts/") && artifactHttp === 200,
    JSON.stringify({ tile, artifactHttp }));

  const folded = await waitFor(async () => await page.evaluate(() => {
    const el = document.querySelector("[data-st^='think:']");
    return el !== null && !el.hasAttribute("open");
  }));
  check("P2-M6 思维链完成自动折叠", folded, String(folded));

  await stableClick('[data-st="recover:rollback"]');
  await sleep(300);
  const rollbackArmed = await page.evaluate(() =>
    !!document.querySelector('[data-st="recover:rollback-keep"]'));
  await stableClick('[data-st="recover:rollback-keep"]');
  const rollbackFact = await waitFor(async () => await page.evaluate(async () => {
    const list = await (await fetch("/api/v1/workspaces")).json();
    const active = document.querySelector(".rail-item.active .rail-name")?.textContent || "";
    const ws = list.workspaces.find((w) => w.name === active) || list.workspaces[0];
    const snap = await (await fetch(`/api/v1/workspaces/${ws.id}/snapshot`)).json();
    const hist = await (await fetch(`/api/v1/workspaces/${ws.id}/tasks/history`)).json();
    return snap.result === null && hist.history[0]?.status === "rolled_back";
  }));
  const resultGone = await page.evaluate(() => !document.querySelector(".rl-main"));
  check("P2-M6 回滚（两步确认 + 快照清空/历史 rolled_back 双证）",
    rollbackArmed && rollbackFact && resultGone,
    JSON.stringify({ rollbackArmed, rollbackFact, resultGone }));

  await submitTask("M6 重试示例");
  await waitFor(async () => await page.evaluate(() =>
    (document.querySelector(".rl-main")?.textContent || "").includes("完成")));
  await stableClick('[data-st="recover:retry"]');
  await sleep(300);
  const composerText = await page.evaluate(() =>
    document.querySelector(".cbox textarea")?.value || "");
  check("P2-M6 重试回填输入区", composerText.includes("M6 重试示例"), composerText);

  await submitTask("M6 引擎失败示例");
  const failSeen = await waitFor(async () => await page.evaluate(() =>
    (document.querySelector(".error-card .card-body p")?.textContent || "").includes("模拟引擎失败")));
  const resumeBtn = await page.evaluate(() => !!document.querySelector('[data-st="recover:resume"]'));
  check("P2-M6 引擎失败可见（error + 续跑入口）", failSeen && resumeBtn,
    JSON.stringify({ failSeen, resumeBtn }));
  // E0-1 语义延续（Wave-2 收口）：续跑点击需受理校验 + 有界重试
  // （裸点偶发丢点——本断言 2026-09-30 起历史 flaky；受理信号=续跑入口离开 DOM）
  await mouseClick('[data-st="recover:resume"]');
  const resumeAccepted = await waitFor(async () => await page.evaluate(() =>
    !document.querySelector('[data-st="recover:resume"]')), 3000);
  if (!resumeAccepted) await mouseClick('[data-st="recover:resume"]');
  const resumed = await waitFor(async () => await page.evaluate(() =>
    (document.querySelector(".rl-main")?.textContent || "").includes("完成")));
  check("P2-M6 续跑恢复（resume → 完成）", resumed, String(resumed));

  await mouseClick('[data-st="rail-search"]');
  await sleep(400);
  await page.type('[data-st="search-input"]', "M6 重试示例");
  const searchSeen = await waitFor(async () => await page.evaluate(() =>
    (document.querySelector(".search-item")?.textContent || "").includes("M6 重试示例")));
  await mouseClick('[data-st="search-item:0"]');
  await sleep(700);
  const tasksView = await page.evaluate(() =>
    document.querySelector(".dock-tab.on")?.textContent || "");
  check("P2-M6 搜索（结果命中 + 点击切视图）",
    searchSeen && tasksView === "任务", JSON.stringify({ searchSeen, tasksView }));

  await page.keyboard.down("Control");
  await page.keyboard.press("k");
  await page.keyboard.up("Control");
  await sleep(400);
  const paletteOpen = await page.evaluate(() => !!document.querySelector(".palette-overlay"));
  await page.type('[data-st="palette-input"]', "设置");
  await sleep(200);
  await page.keyboard.press("Enter");
  await sleep(700);
  const settingsOpened = await page.evaluate(() => {
    const o = document.querySelector(".settings-overlay");
    return o !== null && !o.hasAttribute("hidden");
  });
  check("P2-M6 命令面板（Ctrl+K → 设置命令生效）",
    paletteOpen && settingsOpened, JSON.stringify({ paletteOpen, settingsOpened }));
  await page.keyboard.press("Escape");
  await sleep(300);

  await submitTask("M6 通知示例");
  // 等待新任务到达（meta 含任务文本——上一任务的陈旧「完成/徽标」会误导断言）
  const metaSeen = await waitFor(async () => await page.evaluate(() =>
    (document.querySelector(".stream-meta")?.textContent || "").includes("M6 通知示例")));
  const doneSeen = await waitFor(async () => await page.evaluate(() =>
    (document.querySelector(".rl-main")?.textContent || "").includes("完成")));
  const badgeSeen = await waitFor(async () => await page.evaluate(() =>
    (document.querySelector('[data-st="rail-notices"] .rail-badge')?.textContent || "") !== ""));
  const badgeText = await page.evaluate(() =>
    document.querySelector('[data-st="rail-notices"] .rail-badge')?.textContent || "");
  const unreadFact = await page.evaluate(async () =>
    (await (await fetch("/api/v1/notifications?since=0&limit=100")).json()).unread);
  check("P2-M6 通知徽标（unread 与 /notifications 双证）",
    metaSeen && doneSeen && badgeSeen && unreadFact > 0,
    JSON.stringify({ metaSeen, doneSeen, badgeText, unreadFact }));
  await mouseClick('[data-st="rail-notices"]');
  await sleep(500);
  // 2026-09-19：左栏通知改为弹出菜单（弹层内「在右栏查看全部」进 dock 视图）
  await mouseClick('[data-st="rail-notices-all"]');
  const badgeGone = await waitFor(async () => await page.evaluate(() =>
    !document.querySelector('[data-st="rail-notices"] .rail-badge')), 4000);
  const noticesTab = await page.evaluate(() =>
    document.querySelector(".dock-tab.on")?.textContent || "");
  const noticesDiag = await page.evaluate(async () => {
    const stored = localStorage.getItem("wuxing.notices.seq.v1");
    const payload = await (await fetch(`/api/v1/notifications?since=${stored || 0}&limit=100`)).json();
    return {
      badge: document.querySelector('[data-st="rail-notices"] .rail-badge')?.textContent || "",
      stored,
      serverUnread: payload.unread,
      serverLast: payload.last_seq,
      dockErr: document.querySelector('[data-st="dock-error:notifications"]')?.textContent || "",
      rej: (window.__rej || []).slice(-3),
    };
  });
  check("P2-M6 打开通知即标读（徽标清零 + 视图打开）",
    badgeGone && noticesTab === "通知",
    JSON.stringify({ badgeGone, noticesTab, noticesDiag }));

  const noticeSeals = await page.evaluate(() =>
    [...document.querySelectorAll(".dock-item .seal-stamp")].map((e) => e.textContent || ""));
  check("A4 通知印章（相关文字代替圆点）",
        noticeSeals.length > 0 && noticeSeals.every((s) => s !== ""),
        noticeSeals.join("|"));

  await mouseClick('[data-st="composer-attach"]');
  await sleep(600);
  const chip = await page.evaluate(() => {
    const el = document.querySelector('[data-st^="ref:"]');
    return el ? { text: el.textContent || "", key: el.getAttribute("data-st") || "" } : null;
  });
  check("P2-M6 参考文件 chips（系统对话框桥桩）",
    chip !== null && chip.text.includes("报告.md"), JSON.stringify(chip));
  await submitTask("M6 参考文件示例");
  // 状态到达轮询：等待提交成功后的 chips 清空（勿采样竞态——上一个任务的「完成」标题会误导）
  const chipsCleared = await waitFor(async () => await page.evaluate(() =>
    document.querySelectorAll('[data-st^="ref:"]').length === 0), 8000);
  let refsLog = [];
  try {
    refsLog = JSON.parse(require("fs").readFileSync(
      require("path").resolve(__dirname, "fake-ws/references_log.json"), "utf8"));
  } catch { /* E0-1：缺失/损坏 → 空数组进入断言（失败可见，不炸脚本） */ }
  const refsDiag = await page.evaluate(() => ({
    chips: document.querySelectorAll('[data-st^="ref:"]').length,
    rej: (window.__rej || []).slice(-3),
  }));
  check("P2-M6 提交携带 references（落盘双证 + chips 清空）",
    refsLog.length > 0 && String(refsLog.at(-1)[0]).includes("报告.md") && chipsCleared,
    JSON.stringify({ refs: refsLog.at(-1), chipsCleared, refsDiag }));

  // ---- P2-M7 停止任务（运行中可见入口 → 状态转已取消） ----
  // 前置：上一任务须已收尾（composer 恢复可用）——否则输入会被运行中禁用态吞掉
  await waitFor(async () => await page.evaluate(() =>
    !(document.querySelector(".cbox textarea")?.disabled ?? true)), 8000);
  await submitTask("M6 慢任务示例");
  const slowStarted = await waitFor(async () => await page.evaluate(() =>
    (document.querySelector(".stream-meta")?.textContent || "").includes("M6 慢任务示例")));
  const stopVisible = await waitFor(async () => await page.evaluate(() => {
    const b = document.querySelector('[data-st="composer-stop"]');
    return b !== null && !b.hidden;
  }), 6000);
  const cancelSeen = await clickUntil('[data-st="composer-stop"]', async () =>
    await page.evaluate(() =>
      (document.querySelector(".stream-meta")?.textContent || "").includes("已取消")), 3, 2500);
  const stopGone = await waitFor(async () => await page.evaluate(() => {
    const b = document.querySelector('[data-st="composer-stop"]');
    return b !== null && b.hidden;
  }), 6000);
  const stopDiag = await page.evaluate(() => ({
    meta: document.querySelector(".stream-meta")?.textContent || "",
    appError: (() => { const n = document.querySelector(".app-error"); return n && !n.hasAttribute("hidden") ? n.textContent : ""; })(),
  }));
  check("P2-M7 停止任务（运行中入口 + 已取消 + 按钮复归）",
    slowStarted && stopVisible && cancelSeen && stopGone,
    JSON.stringify({ slowStarted, stopVisible, cancelSeen, stopGone, stopDiag }));

  // A13 响应式（1000px：dock 浮层 + 40px 贴边条；700px：rail 迷你 + 抽屉）
  await page.setViewport({ width: 1000, height: 800, deviceScaleFactor: 1 });
  await sleep(600);
  const dockOverlay = await page.evaluate(() => {
    const slot = document.querySelector(".app-dock-slot");
    const cs = getComputedStyle(slot);
    return { pos: cs.position, w: Math.round(slot.getBoundingClientRect().width), shadow: cs.boxShadow.slice(0, 24) };
  });
  check("A13 <1280 dock 转固定浮层（320 + 阴影）",
        dockOverlay.pos === "fixed" && dockOverlay.w === 320 && dockOverlay.shadow.includes("rgba"),
        JSON.stringify(dockOverlay));
  await mouseClick('[data-st="dock-collapse"]');
  await sleep(600);
  const dockStrip = await page.evaluate(() => {
    const slot = document.querySelector(".app-dock-slot");
    const r = slot.getBoundingClientRect();
    return { visibleW: Math.round(window.innerWidth - r.left), shadow: getComputedStyle(slot).boxShadow };
  });
  check("A13 dock 收起 = 40px 贴边条（无阴影）",
        dockStrip.visibleW === 40 && dockStrip.shadow === "none", JSON.stringify(dockStrip));
  await mouseClick('[data-st="dock-expand"]');
  await sleep(500);
  await page.setViewport({ width: 700, height: 800, deviceScaleFactor: 1 });
  await sleep(600);
  const railMini = await page.evaluate(() => {
    const rail = document.querySelector(".rail");
    return {
      collapsed: rail.classList.contains("collapsed"),
      mini: document.querySelectorAll(".rail-mini button").length,
      w: Math.round(rail.getBoundingClientRect().width),
    };
  });
  check("A13 <768 rail 强制迷你（48px + 迷你按钮）",
        railMini.collapsed && railMini.mini >= 5 && railMini.w === 48, JSON.stringify(railMini));
  await mouseClick('[data-st="rail-expand"]');
  await sleep(600);
  const drawer = await page.evaluate(() => {
    const slot = document.querySelector(".app-rail-slot");
    const cs = getComputedStyle(slot);
    return { pos: cs.position, w: Math.round(slot.getBoundingClientRect().width), shadow: cs.boxShadow.slice(0, 20) };
  });
  check("A13 rail 展开 = 抽屉浮层（fixed 236 + 阴影）",
        drawer.pos === "fixed" && drawer.w === 236 && drawer.shadow.includes("rgba"), JSON.stringify(drawer));
  await page.setViewport({ width: 1440, height: 900, deviceScaleFactor: 1 });
  await sleep(500);

  // A9 帮助弹窗（M7 挂账 A 关闭；关闭后再做悬浮卡交互）
  await mouseClick('[data-st="open-help"]');
  await sleep(400);
  const helpInfo = await page.evaluate(() => ({
    open: !!document.querySelector('[data-st="help"] .help-card'),
    steps: document.querySelectorAll('[data-st="help"] .help-step').length,
    kbd: [...document.querySelectorAll('[data-st="help"] .help-key kbd')].map((e) => e.textContent || ""),
  }));
  check("A9 帮助弹窗（步骤 + 键帽）",
        helpInfo.open && helpInfo.steps >= 3 && helpInfo.kbd.includes("Enter"),
        JSON.stringify(helpInfo));
  await page.keyboard.press("Escape");
  await sleep(300);
  const helpGone = await page.evaluate(() => !document.querySelector('[data-st="help"]'));
  check("A9 帮助弹窗 Esc 关闭", helpGone, String(helpGone));

  // A8（二）悬浮任务卡（可见 + 拖动 + 点击放大；置于末尾避免浮层遮挡后续用例）
  const fc = await page.evaluate(() => {
    const el = document.querySelector("#float-root .task-card");
    if (!el || el.hidden) return null;
    const r = el.getBoundingClientRect();
    return { x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), text: el.textContent || "" };
  });
  check("A8 悬浮任务卡（工作态可见 + 任务文本 + min 220）",
        !!fc && fc.text.includes("慢任务") && fc.w >= 220, JSON.stringify(fc));
  if (fc) {
    await page.mouse.move(fc.x + 40, fc.y + 14);
    await page.mouse.down();
    await page.mouse.move(fc.x + 100, fc.y + 44, { steps: 6 });
    await page.mouse.up();
    await sleep(250);
    const after = await page.evaluate(() => {
      const el = document.querySelector("#float-root .task-card");
      const r = el.getBoundingClientRect();
      return { x: Math.round(r.left), y: Math.round(r.top), expanded: el.classList.contains("expanded") };
    });
    check("A8 悬浮任务卡拖动（位置变化 + 拖动不触发展开）",
          after.x !== fc.x && !after.expanded, JSON.stringify({ from: fc, after }));
    await page.mouse.click(after.x + 40, after.y + 14);
    await sleep(300);
    const expanded = await page.evaluate(() =>
      document.querySelector("#float-root .task-card")?.classList.contains("expanded") ?? false);
    check("A8 悬浮任务卡点击放大", expanded, String(expanded));
  }

  check("P2 无 pageerror（设置交互后）", pageErrors.length === 0, pageErrors.join("; "));

  await page.screenshot({ path: SHOT, fullPage: true });
  await browser.close();

  const failed = results.filter((r) => !r.pass);
  console.log(`\n${results.length - failed.length}/${results.length} passed`);
  process.exit(failed.length === 0 ? 0 : 1);
})().catch((error) => {
  console.error("E2E ERROR:", error);
  process.exit(1);
});
