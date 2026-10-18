/* U5 覆盖盲区补测（剩余项）：hero 占位符语言切换 / 碎片钻取视图 /
   通知中心与回收站动作 / 确认门 UI 逐项 / 窄屏 <768 抽屉 / SEC3 权限剖面控件。
   用法：python e2e/shell/restart_fixture.py
        SHELL_URL=http://127.0.0.60:8833/next/ node e2e/shell/u5_remaining_check.js
   全过退出 0；任一失败退出 1。
   纪律：交互断言用真实鼠标事件（page.mouse）——合成 click 绕过命中测试。 */
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

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const waitFor = async (fn, timeoutMs = 10000) => {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      if (await fn()) return true;
      await sleep(150);
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
  // 稳定点击（异步重渲染会移动按钮——两次探针一致才点）
  const stableClick = async (selector) => {
    let prev = null;
    for (let i = 0; i < 5; i++) {
      const box = await probeBox(selector);
      if (!box) { console.log(`WARN stableClick(${selector}) 元素缺失`); return false; }
      if (prev && box.ok && Math.abs(box.x - prev.x) < 2 && Math.abs(box.y - prev.y) < 2) {
        await page.mouse.move(box.x, box.y);
        await sleep(60);
        await page.mouse.click(box.x, box.y);
        return true;
      }
      prev = box;
      await sleep(200);
    }
    console.log(`WARN stableClick(${selector}) 未稳定命中：last hit=${prev ? prev.hit : "?"}`);
    return false;
  };
  // E0-1（2026-10-02）：确认卡勾选校验+重试（合成点击偶发丢点；幂等补点未勾选项）
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
  const text = (sel) => page.evaluate((s) => document.querySelector(s)?.textContent || "", sel);
  const inputValue = (sel) => page.evaluate((s) => {
    const el = document.querySelector(s);
    return el ? (el.getAttribute("placeholder") || el.value || "") : "";
  }, sel);
  const api = (path, method = "GET", body = null) => page.evaluate(
    async (p, m, b) => {
      const res = await fetch(p, {
        method: m,
        headers: { "X-Wuxing": "1", "Content-Type": "application/json" },
        body: b === null ? undefined : JSON.stringify(b),
      });
      let data = null;
      try { data = await res.json(); } catch (_e) { data = null; }
      return { status: res.status, data };
    }, path, method, body);
  // 原生 select 下拉无法真实点击（浏览器 UI 层）——用 select 值变更 + change 事件（标准做法）
  const selectLang = (val) => page.evaluate((v) => {
    const sel = document.querySelector('[data-st="lang"]');
    if (!sel) return false;
    sel.value = v;
    sel.dispatchEvent(new Event("change", { bubbles: true }));
    return true;
  }, val);

  // 回收站弹层开/关（弹层开启时可能遮挡触发器——先外点关闭（onDocPointer 惯例），
  // 再按需重开以保证列表刷新）
  const ensureRecyclePopover = async (open) => {
    await page.mouse.click(760, 500);
    await sleep(350);
    if (open) {
      await stableClick('[data-st="rail-recycle"]');
      await sleep(500);
    }
  };

  await page.goto(URL, { waitUntil: "domcontentloaded" });
  await sleep(1800);

  // ============ 1) hero 占位符/静态文案语言切换 ============
  const heroVisible = await visible(".hero-text");
  check("hero 可见（零态启动）", heroVisible);
  if (heroVisible) {
    const zhBefore = {
      ph: await inputValue(".hero-text"), tag: await text(".hero-tag"),
      hint: await text(".hero-hint"),
    };
    check("hero 初始为中文（占位符/标语/提示）",
      zhBefore.ph.includes("描述你想完成的任务") && zhBefore.tag.includes("机制是裁决者")
      && zhBefore.hint.includes("输入后按 Enter 提交"), JSON.stringify(zhBefore));

    await mouseClick('[data-st="open-settings"]');
    await sleep(700);
    check("设置浮层打开", await visible('[data-st="st-search"]'));
    await mouseClick('[data-st="nav:appearance"]');
    await sleep(500);
    check("外观分区渲染（语言控件在场）", await visible('[data-st="lang"]'));
    await selectLang("en");
    await sleep(500);
    await page.keyboard.press("Escape");
    await sleep(500);
    const en = {
      ph: await inputValue(".hero-text"), tag: await text(".hero-tag"),
      hint: await text(".hero-hint"),
    };
    check("hero 占位符随语言切换更新（EN）", en.ph.includes("Describe the task"), en.ph);
    check("hero 静态文案随语言切换更新（标语/提示 EN）",
      en.tag.includes("Mechanism is the judge") && en.hint.includes("Press Enter to submit"),
      JSON.stringify(en));

    // 切回中文（不影响后续）
    await mouseClick('[data-st="open-settings"]');
    await sleep(700);
    if (await visible('[data-st="st-search"]')) {
      await mouseClick('[data-st="nav:appearance"]');
      await sleep(400);
      await selectLang("zh");
      await sleep(500);
    }
    await page.keyboard.press("Escape");
    await sleep(500);
    check("语言切回中文（占位符恢复）",
      (await inputValue(".hero-text")).includes("描述你想完成的任务"));
  }

  // ============ 2) 跑一个默认任务（供通知/工件/会话状态） ============
  await page.click(".hero-text");
  await page.type(".hero-text", "U5 剩余巡检任务");
  await page.keyboard.press("Enter");
  const doneSeen = await waitFor(async () =>
    (await text(".stream-meta")).includes("完成"), 15000);
  check("默认任务完成（流可见）", doneSeen, await text(".stream-meta"));

  // ============ 3) 碎片钻取视图（种子会话 P-a） ============
  const wsList = (await api("/api/v1/workspaces")).data?.workspaces || [];
  const fakeWs = wsList.find((w) => (w.name || "").includes("fake-ws"));
  if (fakeWs) await mouseClick(`[data-st="rail:${fakeWs.id}"]`);
  await sleep(900);
  await mouseClick('[data-st="rail-session:conversation-1710000100.jsonl"]');
  await sleep(1200);
  const chipBox = await probeBox('[data-st="frag-chip:P-a"]');
  check("历史轮碎片 chip 可见（frag-chip:P-a）", !!chipBox);
  let drillOk = false;
  if (chipBox) {
    await page.mouse.move(chipBox.x, chipBox.y);
    await sleep(60);
    await page.mouse.click(chipBox.x, chipBox.y);
    drillOk = await waitFor(async () => await visible('[data-st="fragment"]'), 8000);
  }
  check("碎片钻取视图打开", drillOk);
  if (drillOk) {
    const badge = await text('[data-st="fragment-badge"]');
    const title = await text('.fragment-title');
    check("碎片视图标注 unit（fragment-title = P-a）", title.includes("P-a"),
      `title=${title} badge=${badge}`);
    const bodyOk = await waitFor(async () =>
      (await text(".fragment-body")).includes("并行分支A"), 8000);
    const body = await text(".fragment-body");
    check("碎片视图渲染种子消息（并行分支A）", bodyOk, body.slice(0, 80));
    const unitApi = fakeWs
      ? await api(`/api/v1/workspaces/${fakeWs.id}/unit-sessions/P-a`)
      : { status: 0 };
    check("服务端双证：unit-sessions/P-a 含 1-P-a.jsonl",
      unitApi.status === 200
      && (unitApi.data?.files || []).includes("1-P-a.jsonl"),
      JSON.stringify(unitApi.data?.files || []));
    await mouseClick('[data-st="fragment-back"]');
    await sleep(500);
    check("碎片返回（回主视图）", !(await visible('[data-st="fragment"]')));
  }

  // ============ 4) 通知中心与回收站动作 ============
  await stableClick('[data-st="rail-notices"]');
  await sleep(600);
  const noticesPop = await visible('[data-st="rail-notices-pop"]');
  const noticeRows = await page.evaluate(() =>
    document.querySelectorAll('[data-st="rail-notices-pop"] .rp-entry').length);
  check("rail 通知弹层（条目渲染）", noticesPop && noticeRows >= 1,
    `pop=${noticesPop} rows=${noticeRows}`);
  if (noticesPop) {
    await stableClick('[data-st="rail-notices-all"]');
    await sleep(800);
    const activeTab = await text(".dock-tab.on");
    const dockRows = await page.evaluate(() =>
      document.querySelectorAll(".dock-item").length);
    check("「全部」跳转通知面板（tab 激活 + 条目）",
      activeTab.includes("通知") && dockRows >= 1, `${activeTab} / ${dockRows}`);
  }
  // 关闭残留通知弹层（若仍开——防遮挡后续 rail 按钮）
  if (await visible('[data-st="rail-notices-pop"]')) {
    await stableClick('[data-st="rail-notices"]');
    await sleep(400);
  }

  // 回收站：归档 → 弹层恢复（双证）
  const ws2 = wsList.find((w) => (w.name || "").includes("fake-ws2"));
  if (ws2) await api(`/api/v1/workspaces/${ws2.id}/archive`, "POST", { state: "archived" });
  await sleep(700);
  await ensureRecyclePopover(true);
  let rc = (await api("/api/v1/recycle")).data?.entries || [];
  const entry = rc.find((e) => (e.name || "").includes("fake-ws2"));
  check("rail 回收站弹层（归档条目出现）", !!entry, JSON.stringify(rc.map((e) => e.name)));
  if (entry) {
    await stableClick(`[data-st="rail-rc-restore:${entry.id}"]`);
    await sleep(900);
    const afterRestore = {
      ws: ((await api("/api/v1/workspaces")).data?.workspaces || []).map((w) => w.name),
      rc: ((await api("/api/v1/recycle")).data?.entries || []).map((e) => e.name),
    };
    check("回收站恢复（服务端双证）",
      afterRestore.ws.some((n) => n.includes("fake-ws2"))
      && !afterRestore.rc.some((n) => n.includes("fake-ws2")),
      JSON.stringify(afterRestore));
  }
  await ensureRecyclePopover(false);
  // 回收站：两步彻底删除（双证）
  if (ws2) await api(`/api/v1/workspaces/${ws2.id}/archive`, "POST", { state: "archived" });
  await sleep(700);
  await ensureRecyclePopover(true);
  rc = (await api("/api/v1/recycle")).data?.entries || [];
  const entry2 = rc.find((e) => (e.name || "").includes("fake-ws2"));
  if (entry2) {
    await stableClick(`[data-st="rail-rc-purge:${entry2.id}"]`);
    await sleep(400);
    const stepTwo = await visible(`[data-st="rail-rc-purge-ok:${entry2.id}"]`);
    check("彻底删除两步确认（第一步 → 二次按钮出现）", stepTwo);
    if (stepTwo) {
      await stableClick(`[data-st="rail-rc-purge-ok:${entry2.id}"]`);
      await sleep(900);
      const afterPurge = (await api("/api/v1/recycle")).data?.entries || [];
      check("彻底删除生效（服务端双证：条目移除）",
        !afterPurge.some((e) => e.name.includes("fake-ws2")),
        JSON.stringify(afterPurge.map((e) => e.name)));
    }
  } else {
    check("彻底删除前置（归档条目存在）", false, "fake-ws2 未归档成功");
  }
  await ensureRecyclePopover(false);

  // ============ 5) 确认门 UI 逐项 ============
  const composerSel = ".cbox textarea";
  await page.click(composerSel);
  await page.type(composerSel, "U5 待确认巡检");
  await page.keyboard.press("Enter");
  const twoRows = await waitFor(async () => await page.evaluate(() =>
    document.querySelectorAll(".stream-confirm-row").length === 2), 12000);
  check("确认门两卡（待确认场景）", twoRows);
  if (twoRows) {
    const ids = await page.evaluate(() => ({
      checkId: !!document.querySelector('#confirm-check-C-1[name="confirm-check"]'),
      reasonId: !!document.querySelector('#confirm-reason-C-2[name="confirm-reason"]'),
    }));
    check("确认门控件 id/name（复选与理由）", ids.checkId && ids.reasonId, JSON.stringify(ids));
    const info0 = await text('[data-st="confirm-batch-info"]');
    await ensureConfirmSelection(["C-1"], 1);
    const info1 = await text('[data-st="confirm-batch-info"]');
    await ensureConfirmSelection(["C-1", "C-2"], 2);
    const info2 = await text('[data-st="confirm-batch-info"]');
    check("批量条选中计数（0→1→2）",
      info0.includes("已选 0") && info1.includes("已选 1") && info2.includes("已选 2"),
      `${info0} | ${info1} | ${info2}`);
    // 单条批准 C-1（已决保留 + 余 1 + 批量条隐藏）
    await mouseClick('[data-st="confirm-approve:C-1"]');
    await sleep(800);
    const resolved = await waitFor(async () =>
      (await text('[data-st="confirm-resolved:C-1"]')).includes("已批准"), 6000);
    const rowsLeft = await page.evaluate(() =>
      document.querySelectorAll(".stream-confirm-row").length);
    const batchHidden = await page.evaluate(() =>
      document.querySelector(".stream-batch")?.hasAttribute("hidden") ?? true);
    check("单条批准（已决保留 + 余 1 + 批量条隐藏）",
      resolved && rowsLeft === 1 && batchHidden,
      `resolved=${resolved} rows=${rowsLeft} batchHidden=${batchHidden}`);
    // 单条驳回：空理由阻断 → 填理由后驳回成功
    await mouseClick('[data-st="confirm-reject:C-2"]');
    await sleep(300);
    const bad = await page.evaluate(() =>
      document.querySelector('[data-st="confirm-reason:C-2"]')?.classList.contains("bad") ?? false);
    check("驳回空理由阻断（bad 标记）", bad);
    await page.type('[data-st="confirm-reason:C-2"]', "不完整");
    await mouseClick('[data-st="confirm-reject:C-2"]');
    await sleep(800);
    const rejected = await waitFor(async () =>
      (await text('[data-st="confirm-resolved:C-2"]')).includes("已驳回"), 6000);
    check("单条驳回（已决理由 + 任务失败）", rejected);
  }
  // 确认失败可见（引擎异常 → 错误卡）
  await sleep(500);
  await page.click(composerSel);
  await page.type(composerSel, "U5 确认失败巡检（确认失败）");
  await page.keyboard.press("Enter");
  await waitFor(async () => await page.evaluate(() =>
    document.querySelectorAll(".stream-confirm-row").length >= 1), 12000);
  await mouseClick('[data-st="confirm-approve:FU-1"]');
  const errSeen = await waitFor(async () =>
    (await text(".error-card .card-body p")).includes("确认处理失败"), 8000);
  check("确认失败可见（错误卡）", errSeen, await text(".error-card .card-body p"));

  // ============ 6) 窄屏 <768（抽屉） ============
  await page.setViewport({ width: 720, height: 900, deviceScaleFactor: 1 });
  await sleep(800);
  const narrowState = await page.evaluate(() => ({
    collapsed: document.querySelector(".rail")?.classList.contains("collapsed") ?? null,
    mini: !!document.querySelector(".rail-mini"),
    overflow: document.scrollingElement.scrollWidth - window.innerWidth,
  }));
  check("窄屏：rail 抽屉态（收起 + 迷你入口）+ 无横向溢出",
    narrowState.collapsed === true && narrowState.mini && narrowState.overflow <= 1,
    JSON.stringify(narrowState));
  await mouseClick('[data-st="rail-expand"]');
  await sleep(700);
  const drawerOpen = await page.evaluate(() =>
    document.querySelector(".rail")?.classList.contains("collapsed") === false);
  check("窄屏：抽屉展开（rail-expand）", drawerOpen);
  if (drawerOpen) {
    await stableClick('[data-st="rail-recycle"]');
    await sleep(500);
    check("窄屏：抽屉内回收站弹层可用", await visible('[data-st="rail-recycle-pop"]'));
    // 外点关闭弹层（onDocPointer 惯例）——避免遮挡后续探针
    await page.mouse.click(1300, 300);
    await sleep(400);
  }
  await page.setViewport({ width: 1440, height: 900, deviceScaleFactor: 1 });
  await sleep(800);
  const backWide = await page.evaluate(() => ({
    collapsed: document.querySelector(".rail")?.classList.contains("collapsed") ?? null,
    overflow: document.scrollingElement.scrollWidth - window.innerWidth,
  }));
  check("回宽屏：rail 恢复展开 + 无横向溢出",
    backWide.collapsed === false && backWide.overflow <= 1, JSON.stringify(backWide));

  // ============ 7) SEC3：权限剖面控件（三档 + full-access 警告） ============
  await mouseClick('[data-st="open-settings"]');
  await sleep(700);
  await mouseClick('[data-st="nav:mechanism"]');
  await sleep(600);
  const profileOk = await visible('[data-st="field:permission_profile"]');
  const profileOpts = profileOk ? await page.$$eval(
    '[data-st="field:permission_profile"] option',
    (os) => os.map((o) => o.value)) : [];
  check("SEC3 权限剖面控件（三档选项）",
    profileOk && profileOpts.join("|") === "read-only|workspace-write|full-access",
    profileOpts.join("|"));
  if (profileOk) {
    await page.select('[data-st="field:permission_profile"]', "full-access");
    await sleep(900);
    check("SEC3 full-access 警告可见", await visible('[data-st="perm-profile-warning"]'));
    const cfg1 = (await api("/api/v1/config")).data?.values?.permission_profile;
    check("SEC3 剖面落盘（服务端双证）", cfg1 === "full-access", String(cfg1));
    await page.select('[data-st="field:permission_profile"]', "workspace-write");
    await sleep(900);
    const cfg2 = (await api("/api/v1/config")).data?.values?.permission_profile;
    check("SEC3 剖面恢复默认（不留污染）", cfg2 === "workspace-write", String(cfg2));
    await page.keyboard.press("Escape");
    await sleep(400);
  }

  check("无 pageerror", pageErrors.length === 0, pageErrors.join("; "));

  const failed = results.filter((r) => !r.pass);
  console.log(`\n== U5 剩余巡检：${results.length - failed.length}/${results.length} PASS ==`);
  await browser.close();
  process.exit(failed.length === 0 ? 0 : 1);
})().catch((err) => { console.error("FATAL", err); process.exit(2); });
