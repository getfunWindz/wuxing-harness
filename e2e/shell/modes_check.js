/* 双模式批 1 断言（模式机制 + 极简两分支）——真实鼠标（1440×900）。
   用法：SHELL_URL=http://127.0.0.60:8833/next/ node e2e/shell/modes_check.js
   前置：serve_fake 8833 零态（夹具每轮重启；session-modes.json 已重置）。
   证据：sidecar 落盘（fs 双证）+ 夹具 trace 回放（mode/skills_chars/tools——
   夹具经真实 session_modes.resolve 解析 sidecar；真实装配面由 pytest 覆盖）。 */
const puppeteer = require("puppeteer-core");
const path = require("node:path");
const fs = require("node:fs");

const EDGE = process.env.EDGE_PATH ||
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
const URL = process.env.SHELL_URL || "http://127.0.0.60:8833/next/";
const OUT = process.env.OUT_DIR || path.join(__dirname, "visual", "modes");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
fs.mkdirSync(OUT, { recursive: true });

const WUX = path.join(__dirname, "fake-ws", ".wuxing");
const SIDECAR = path.join(WUX, "session-modes.json");
const TRACE = path.join(WUX, "trace.jsonl");
const CFG = path.join(__dirname, "fake-ws", "user", "config.jsonc");
const CORE = ["bash", "read_file", "write_file", "write_artifact", "read_dependency"];

const sidecar = () => {
  try { return JSON.parse(fs.readFileSync(SIDECAR, "utf8")); }
  catch { return {}; }
};
const sidecarConvs = () => sidecar().conversations || {};
const traceRows = () => fs.readFileSync(TRACE, "utf8").split("\n")
  .filter((x) => x.trim()).map((x) => { try { return JSON.parse(x); } catch { return {}; } });

const results = [];
function check(name, ok, detail) {
  results.push({ name, ok: !!ok });
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail !== undefined ? "  :: " + JSON.stringify(detail) : ""}`);
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
  const waitFor = async (fn, timeoutMs = 10000) => {
    const t0 = Date.now();
    for (;;) {
      const v = fn();
      if (v) return v;
      if (Date.now() - t0 > timeoutMs) return null;
      await sleep(200);
    }
  };
  const chipInfo = () => page.evaluate(() => {
    const bar = document.querySelector(".mode-bar");
    const chip = document.querySelector('[data-st="mode-chip"]');
    const tag = document.querySelector('[data-st="session-mode-tag"]');
    const visible = !!bar && !bar.hidden
      && getComputedStyle(bar).display !== "none";
    return { chip: chip?.textContent || "", tag: tag?.textContent || "", visible };
  });
  const wsIdOf = async (name) => page.evaluate(async (n) => {
    const list = await (await fetch("/api/v1/workspaces")).json();
    return list.workspaces.find((w) => w.name === n)?.id ?? "";
  }, name);
  const openModesSettings = async () => {
    await mouseClick('[data-st="open-settings"]');
    await sleep(900);
    await mouseClick('[data-st="nav:modes"]');
    await sleep(700);
  };
  const closeSettings = async () => {
    await mouseClick('[data-st="close"]');
    await sleep(700);
  };

  await page.goto(URL, { waitUntil: "networkidle2", timeout: 25000 });
  await sleep(1500);

  // —— 断言 1：新建会话默认 = 极简·标准（chip 与标签一致） ——
  let info = await chipInfo();
  if (!info.visible) {   // 兜底：未自动激活工作区时手动选中
    const wsId = await wsIdOf("fake-ws");
    if (wsId) { await mouseClick(`[data-st="rail:${wsId}"]`); await sleep(900); }
    info = await chipInfo();
  }
  check("1 新建会话默认 = 极简·标准（chip 可见）",
    info.visible && info.chip.includes("极简·标准"), info);
  check("1b 会话标签与 chip 一致（极简·标准）",
    info.tag.includes("极简·标准"), info.tag);

  // —— 断言 2：空白会话切换成功（chip → 极简·纯净）+ sidecar 落盘 ——
  await mouseClick('[data-st="mode-chip"]');
  await sleep(300);
  await mouseClick('[data-st="mode-pick:minimal-pure"]');
  await sleep(900);
  const convs1 = sidecarConvs();
  const names1 = Object.keys(convs1);
  const pendingName = names1.find((n) => convs1[n].variant === "pure") || names1[0] || "";
  check("2 空白会话切换到极简·纯净（sidecar 落盘为 pure）",
    pendingName !== "" && convs1[pendingName]?.mode === "minimal"
      && convs1[pendingName]?.variant === "pure",
    { convs: names1, row: convs1[pendingName] });
  info = await chipInfo();
  check("2b chip 更新为极简·纯净（会话级来源生效）",
    info.chip.includes("极简·纯净"), info.chip);

  // —— 断言 3：提交任务 → trace 判定 pure（无技能索引 + 工具 ⊆ 核心集） ——
  await page.click(".hero-text");
  await page.type(".hero-text", "纯模式演示任务");
  await mouseClick('[data-st="hero-send"]');
  const row1 = await waitFor(() => traceRows().find(
    (r) => r.conversation === pendingName && r.event === "unit_started"));
  check("3 trace: mode=minimal/variant=pure（提交链路口径一致）",
    row1 && row1.mode === "minimal" && row1.variant === "pure",
    row1 && { mode: row1.mode, variant: row1.variant });
  check("3b trace: skills_chars=0（技能索引未注入）",
    row1 && Number(row1.skills_chars) === 0, row1 && row1.skills_chars);
  check("3c trace: 工具集合 ⊆ 核心集（delegate/load_skill 不在场）",
    row1 && Array.isArray(row1.tools) && row1.tools.length > 0
      && row1.tools.every((t) => CORE.includes(t))
      && !row1.tools.includes("delegate") && !row1.tools.includes("load_skill"),
    row1 && row1.tools);
  await page.screenshot({ path: path.join(OUT, "pure-submitted.png") });
  await sleep(1500);

  // —— 断言 4：极简·标准分支（技能索引在场 + 工具含 delegate） ——
  await mouseClick('[data-st="rail-new-session"]');
  await sleep(800);
  await mouseClick('[data-st="mode-chip"]');
  await sleep(300);
  await mouseClick('[data-st="mode-pick:minimal-standard"]');
  await sleep(900);
  const convs2 = sidecarConvs();
  const pendingName2 = Object.keys(convs2).find((n) => n !== pendingName
    && convs2[n].variant === "standard") || "";
  await page.click(".hero-text");
  await page.type(".hero-text", "标准模式演示任务");
  await mouseClick('[data-st="hero-send"]');
  const row2 = await waitFor(() => traceRows().find(
    (r) => r.conversation === pendingName2 && r.event === "unit_started"));
  check("4 标准分支：技能索引在场（skills_chars>0）",
    row2 && Number(row2.skills_chars) > 0, row2 && row2.skills_chars);
  check("4b 标准分支：工具含 delegate（全量面）",
    row2 && Array.isArray(row2.tools) && row2.tools.includes("delegate"),
    row2 && row2.tools);
  await sleep(1500);

  // —— 断言 5：非空白会话切换被拒（可见提示 + sidecar 零写入） ——
  await mouseClick('[data-st="rail-session:conversation-1710000100.jsonl"]');
  await sleep(1000);
  await mouseClick('[data-st="mode-chip"]');
  await sleep(300);
  await mouseClick('[data-st="mode-pick:minimal-pure"]');
  await sleep(500);
  const locked = await page.evaluate(() => {
    const el = document.querySelector('[data-st="mode-locked-tip"]');
    return {
      text: el?.textContent || "",
      visible: !!el && !el.hidden && getComputedStyle(el).display !== "none",
    };
  });
  check("5 非空白会话切换 → 拒绝可见（内联提示）",
    locked.visible && locked.text.length > 0, locked);
  check("5b 非空白会话未写 sidecar（机制守卫双证）",
    !sidecarConvs()["conversation-1710000100.jsonl"],
    Object.keys(sidecarConvs()));

  // —— 断言 6：设置中心切默认（极简·纯净）→ 新会话按新默认 ——
  await openModesSettings();
  await page.select('[data-st="field:mode_default"]', "minimal-pure");
  await sleep(900);
  const cfgText = fs.existsSync(CFG) ? fs.readFileSync(CFG, "utf8") : "";
  check("6 user config 落盘 mode_default=minimal-pure",
    cfgText.includes("minimal-pure"), cfgText.slice(0, 160));
  await closeSettings();
  await mouseClick('[data-st="rail-new-session"]');
  await sleep(1000);
  info = await chipInfo();
  check("6b 新会话默认生效（chip = 极简·纯净）",
    info.visible && info.chip.includes("极简·纯净"), info.chip);

  // —— 断言 7：选择器显隐开关（关 → chip 隐藏；开 → 恢复） ——
  await openModesSettings();
  await mouseClick('[data-st="field:mode_picker_enabled"]');
  await sleep(900);
  await closeSettings();
  info = await chipInfo();
  check("7 显隐开关关 → chip/标签隐藏", !info.visible, info);
  await openModesSettings();
  await mouseClick('[data-st="field:mode_picker_enabled"]');
  await sleep(900);
  await closeSettings();
  info = await chipInfo();
  check("7b 显隐开关开 → chip 恢复", info.visible, info);

  // —— 断言 8：无 pageerror ——
  check("8 无 pageerror", errors.length === 0, errors.slice(0, 2));

  const failed = results.filter((r) => !r.ok);
  console.log(`\n${failed.length === 0 ? "✔" : "✘"} modes 断言 ` +
    `${results.length - failed.length}/${results.length}` +
    (failed.length ? "；失败：" + failed.map((f) => f.name).join("；") : ""));
  await browser.close();
  process.exit(failed.length === 0 && errors.length === 0 ? 0 : 1);
})();
