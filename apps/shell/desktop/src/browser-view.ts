/** Electron 浏览器视图驱动（O2-2 P1；§11.5-② 多视图）。
 *
 * 安全：sandbox/contextIsolation/nodeIntegration=false；拒绝新窗口；导航仅 http(s)（第二道，
 * 第一道在 Python 授权层）；控制通道仅回环 + token。
 * 多视图（Q1=B/视图=身份 1:1）：`Map<key, ViewState>`；每次命令刷新活跃并置前；
 * 关闭后回退次新；memory 引用 LRU=8；run 终态由引擎 close(identity) 清理。
 * 说明：本模块依赖 Electron，无法在纯 Node 下单测——纯策略（激活/LRU/派生键）在
 * browser-view-policy.ts（单测覆盖）；本层由 Windows 真机冒烟覆盖。
 */
import { WebContentsView, session, type BrowserWindow, type Session } from "electron";
import { readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

import type { BrowserDriver } from "./browser-server";
import type { BrowserIdentity } from "./browser-protocol";
import { partitionFor, removeRegistry, upsertRegistry } from "./browser-identity";
import { quadsToPoint, serializeValue } from "./browser-input";
import { lruEvictions, nextActive, overlayKeysFor } from "./browser-view-policy";
import {
  cookieParams,
  parseStorageState,
  type StorageCounts,
  type StorageOrigin,
} from "./browser-storage-state";
import {
  simplifyAxTree,
  type AxNodeLike,
  type SnapshotRef,
} from "./browser-snapshot";

const LOAD_TIMEOUT_MS = 20_000;
const SNAPSHOT_MAX_LINES = 400;
const MEMORY_SESSION_LIMIT = 8;   // D3：memory 引用 LRU 上限（淘汰=冷启动）

export interface BrowserViewDriver extends BrowserDriver {
  dispose(): void;
}

interface ViewState {
  view: WebContentsView;
  refs: Record<string, SnapshotRef>;
  refSeq: number;
  identity: BrowserIdentity;
  lastActiveMs: number;
  seq: number;
  injectPromise: Promise<void> | null;   // §11.5-③：storage-state cookies 注入
  storageCounts: StorageCounts | null;
  storageOrigins: StorageOrigin[] | null;  // §11.5-③：localStorage 播种源
}

function withTimeout<T>(run: Promise<T>, ms: number, label: string): Promise<T> {
  let timer: NodeJS.Timeout | undefined;
  const guarded = run.finally(() => {
    if (timer !== undefined) clearTimeout(timer);
  });
  return Promise.race([
    guarded,
    new Promise<never>((_, reject) => {
      timer = setTimeout(
        () => reject(new Error(`${label}超时（${ms}ms）`)),
        ms,
      );
    }),
  ]);
}

export function createBrowserViewDriver(options: {
  getWindow: () => BrowserWindow | null;
  log?: (message: string) => void;
}): BrowserViewDriver {
  const log = options.log ?? (() => {});
  const views = new Map<string, ViewState>();
  let activeKey: string | null = null;
  let seqCounter = 0;
  let resizeHandler: (() => void) | null = null;
  // v2/v3：身份键控视图 partition（专用——永不用 default session）；
  // memory 档持 session 引用保活（LRU 8）。
  const memorySessions = new Map<string, Session>();

  function applyBounds(v: WebContentsView): void {
    const win = options.getWindow();
    if (win === null || win.isDestroyed()) return;
    const { width, height } = win.getContentBounds();
    const panelWidth = Math.max(480, Math.floor(width / 2));
    v.setBounds({ x: Math.max(0, width - panelWidth), y: 0, width: panelWidth, height });
  }

  function attachDebugger(v: WebContentsView): void {
    const dbg = v.webContents.debugger;
    if (!dbg.isAttached()) dbg.attach("1.3");
  }

  function detachDebugger(v: WebContentsView): void {
    try {
      if (v.webContents.debugger.isAttached()) v.webContents.debugger.detach();
    } catch {
      // 解绑失败不影响关闭
    }
  }

  function ensureResizeHandler(): void {
    if (resizeHandler !== null) return;
    const win = options.getWindow();
    if (win === null || win.isDestroyed()) return;
    resizeHandler = (): void => {
      for (const state of views.values()) {
        if (!state.view.webContents.isDestroyed()) applyBounds(state.view);
      }
    };
    win.on("resize", resizeHandler);
  }

  function touchMemory(partition: string): void {
    memorySessions.delete(partition);   // 重插刷新 LRU 序
    memorySessions.set(partition, session.fromPartition(partition));
    const inUse = [...views.values()]
      .filter((s) => s.identity.mode === "memory")
      .map((s) => partitionFor(s.identity));
    for (const key of lruEvictions([...memorySessions.keys()], inUse,
                                   MEMORY_SESSION_LIMIT)) {
      memorySessions.delete(key);
      log(`[browser-view] memory 会话引用超限淘汰：${key}`);
    }
  }

  function orderKeys(): string[] {
    return [...views.entries()]
      .sort((a, b) => a[1].seq - b[1].seq)
      .map(([key]) => key);
  }

  function activate(key: string | null): void {
    activeKey = key;
    for (const [k, state] of views) {
      const on = k === key;
      try {
        state.view.setVisible(on);
        if (on) applyBounds(state.view);
      } catch (error) {
        log(`[browser-view] 视图可见性设置失败（${k}）：${String(error)}`);
      }
    }
  }

  /** 命令到达：刷新活跃序并置前（Q5=A——可见=最近活跃）。 */
  function touch(key: string): void {
    const state = views.get(key);
    if (state === undefined) return;
    state.seq = ++seqCounter;
    state.lastActiveMs = Date.now();
    activate(key);
  }

  function removeView(key: string): boolean {
    const state = views.get(key);
    if (state === undefined) return false;
    views.delete(key);
    detachDebugger(state.view);
    try {
      options.getWindow()?.contentView.removeChildView(state.view);
    } catch {
      // 窗口已销毁——下面直接关 webContents
    }
    try {
      state.view.webContents.close();
    } catch {
      // 尽力而为
    }
    return true;
  }

  /** §11.5-③：localStorage 播种（导航后 executeJavaScript——不依赖导航前 CDP）。
   *
   * 命中当前 origin → setItem 并返回 true（调用方需重载一次使播种先于页面脚本）；
   * 未命中/空 → false（不重载）。
   */
  async function seedLocalStorage(state: ViewState): Promise<boolean> {
    const origins = state.storageOrigins;
    if (origins === null || origins.length === 0) return false;
    let current = "";
    try {
      current = new URL(state.view.webContents.getURL()).origin;
    } catch {
      return false;
    }
    const match = origins.find((o) => o.origin === current);
    if (match === undefined || match.localStorage.length === 0) return false;
    const payload = JSON.stringify(match.localStorage);
    await withTimeout(
      state.view.webContents.executeJavaScript(
        `(() => { try { const items = ${payload};`
        + " for (const it of items) { localStorage.setItem(it.name, it.value); }"
        + " return true; } catch (e) { return false; } })();"),
      10_000, "storage-state localStorage 播种");
    return true;
  }

  /** §11.5-③：storage-state 注入（cookies via session；localStorage 存播种源）。
   *
   * 失败 → 抛（fail-closed，不建可用视图）；值纪律：日志只记计数/路径。
   * 注：CDP Page 命令在首次导航前不可用（真机发现）——localStorage 改走
   * 导航后 executeJavaScript + 命中时重载（见 `open`）。
   */
  async function injectStorageState(
    state: ViewState,
    identity: BrowserIdentity,
  ): Promise<void> {
    const rawPath = String(identity.state_path ?? "").trim();
    if (rawPath === "") throw new Error("storage-state 档缺少 state_path");
    let raw: string;
    try {
      raw = readFileSync(rawPath, "utf8");
    } catch {
      throw new Error(`storage-state 文件读取失败：${rawPath}`);
    }
    if (Buffer.byteLength(raw, "utf8") > 2 * 1024 * 1024) {
      throw new Error("storage-state 文件超限（>2MB）");
    }
    const parsed = parseStorageState(raw);
    if (!parsed.ok) throw new Error(parsed.error);
    const partition = partitionFor(identity);
    const ses = session.fromPartition(partition);
    let failed = 0;
    for (const cookie of parsed.cookies) {
      try {
        await ses.cookies.set(
          cookieParams(cookie) as unknown as Parameters<
            typeof ses.cookies.set>[0]);
      } catch (error) {
        failed += 1;
        log(`[browser-view] storage-state cookie 注入失败：${String(error)}`);
      }
    }
    if (parsed.cookies.length > 0 && failed === parsed.cookies.length) {
      throw new Error("storage-state cookies 全部注入失败（fail-closed）");
    }
    state.storageOrigins = parsed.origins;
    state.storageCounts = {
      cookies: parsed.counts.cookies - failed,
      origins: parsed.counts.origins,
    };
    log(`[browser-view] storage-state 注入完成 cookies=${state.storageCounts.cookies}`
        + ` origins=${state.storageCounts.origins}`);
  }

  function createView(identity: BrowserIdentity): ViewState {
    const win = options.getWindow();
    if (win === null || win.isDestroyed()) throw new Error("桌面窗口未就绪");
    const partition = partitionFor(identity);
    const v = new WebContentsView({
      webPreferences: {
        sandbox: true,
        contextIsolation: true,
        nodeIntegration: false,
        partition,
      },
    });
    if (identity.mode === "memory") {
      touchMemory(partition);   // memory 档：持 session 引用保活（应用退出才清）
    } else {
      upsertRegistry(identity);   // persist 档：注册表登记（last_used 刷新）
    }
    v.setVisible(false);
    v.setBackgroundColor("#ffffff");
    win.contentView.addChildView(v);
    v.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
    v.webContents.on("will-navigate", (event, url) => {
      if (!/^https?:\/\//i.test(url)) {
        event.preventDefault();
        log(`[browser-view] 拒绝非 http(s) 导航：${url}`);
      }
    });
    try {
      attachDebugger(v);
    } catch (error) {
      log(`[browser-view] debugger attach 失败：${String(error)}`);
    }
    ensureResizeHandler();
    const state: ViewState = {
      view: v,
      refs: {},
      refSeq: 0,
      identity: { ...identity },
      lastActiveMs: Date.now(),
      seq: ++seqCounter,
      injectPromise: null,
      storageCounts: null,
      storageOrigins: null,
    };
    views.set(identity.key, state);
    if (identity.mode === "storage-state") {
      state.injectPromise = injectStorageState(state, identity);
    }
    return state;
  }

  /** 同键（且同模式）复用；否则新建（不再拆旧——多视图并存）。
   *
   * storage-state 档：首次创建时 await 注入（失败 → 拆视图 + 抛，fail-closed）。
   */
  async function acquire(identity: BrowserIdentity): Promise<{ state: ViewState; ensure: string }> {
    const existing = views.get(identity.key);
    if (existing !== undefined && !existing.view.webContents.isDestroyed()
        && existing.identity.mode === identity.mode) {
      if (existing.injectPromise !== null) await existing.injectPromise;
      return { state: existing, ensure: "reused" };
    }
    if (existing !== undefined) removeView(identity.key);
    const state = createView(identity);
    if (state.injectPromise !== null) {
      try {
        await state.injectPromise;
      } catch (error) {
        removeView(identity.key);
        throw error;
      }
    }
    return { state, ensure: "created" };
  }

  async function open(url: string, identity: BrowserIdentity): Promise<Record<string, unknown>> {
    const { state, ensure } = await acquire(identity);
    touch(identity.key);
    state.refs = {};   // P2：导航即失效旧 ref（换代 fail-visible）
    log(`[browser-view] open ${url} key=${identity.key} ${ensure}`);
    await withTimeout(state.view.webContents.loadURL(url), LOAD_TIMEOUT_MS, "页面加载");
    // §11.5-③：localStorage 播种（命中当前 origin → 重载一次使播种先于页面脚本）
    let seeded = false;
    try {
      seeded = await seedLocalStorage(state);
    } catch (error) {
      log(`[browser-view] storage-state localStorage 播种失败：${String(error)}`);
    }
    if (seeded) {
      log("[browser-view] storage-state localStorage 已播种——重载一次");
      await withTimeout(new Promise<void>((resolve) => {
        const timer = setTimeout(resolve, LOAD_TIMEOUT_MS);
        state.view.webContents.once("did-finish-load", () => {
          clearTimeout(timer);
          resolve();
        });
        state.view.webContents.reload();
      }), LOAD_TIMEOUT_MS, "页面重载");
    }
    return { title: state.view.webContents.getTitle(),
             url: state.view.webContents.getURL(),
             identity: { key: identity.key, mode: identity.mode, state: ensure },
             ...(state.storageCounts !== null
                 ? { storage_state: state.storageCounts } : {}) };
  }

  async function snapshot(identity: BrowserIdentity): Promise<Record<string, unknown>> {
    const { state } = await acquire(identity);
    touch(identity.key);
    attachDebugger(state.view);
    const result = (await state.view.webContents.debugger.sendCommand(
      "Accessibility.getFullAXTree",
      {},
    )) as { nodes?: AxNodeLike[] };
    const simplified = simplifyAxTree(result?.nodes ?? [], {
      maxLines: SNAPSHOT_MAX_LINES,
      startRef: state.refSeq,
    });
    state.refSeq = simplified.nextRef;
    state.refs = simplified.refs;
    return {
      snapshot: simplified.lines.join("\n"),
      refs: Object.keys(state.refs).length,
      truncated: simplified.truncated,
      total: simplified.total,
    };
  }

  async function screenshot(
    args: Record<string, unknown>,
    identity: BrowserIdentity,
  ): Promise<Record<string, unknown>> {
    const { state } = await acquire(identity);
    touch(identity.key);
    attachDebugger(state.view);
    const fullPage = args.full_page === true;
    await state.view.webContents.debugger.sendCommand("Page.enable", {});
    const shot = (await state.view.webContents.debugger.sendCommand(
      "Page.captureScreenshot",
      {
        format: "png",
        ...(fullPage ? { captureBeyondViewport: true } : {}),
      },
    )) as { data?: string };
    const file = path.join(
      tmpdir(),
      `wuxing-browser-${Date.now()}-${Math.random().toString(16).slice(2)}.png`,
    );
    writeFileSync(file, Buffer.from(String(shot?.data ?? ""), "base64"));
    return { path: file, full_page: fullPage };
  }

  // ---- P2：操作面（click/type/wait——CDP 真实输入，白名单子集） ----

  const sleep = (ms: number): Promise<void> =>
    new Promise((resolve) => setTimeout(resolve, ms));

  /** ref|selector → backendNodeId（ref 过期 = fail-visible，不猜目标）。 */
  async function resolveNode(
    args: Record<string, unknown>,
    state: ViewState,
  ): Promise<{ backendNodeId: number; label: string }> {
    attachDebugger(state.view);
    const ref = typeof args.ref === "string" ? args.ref : "";
    if (ref !== "") {
      const target: SnapshotRef | undefined = state.refs[ref];
      if (target === undefined || target.backendNodeId === undefined) {
        throw new Error(`ref ${ref} 已过期或未知（快照已换代）——请重新取快照`);
      }
      return { backendNodeId: target.backendNodeId, label: `ref=${ref}` };
    }
    const selector = typeof args.selector === "string" ? args.selector : "";
    const doc = (await state.view.webContents.debugger.sendCommand(
      "DOM.getDocument", {},
    )) as { root?: { nodeId?: number } };
    const rootId = doc?.root?.nodeId;
    if (rootId === undefined) throw new Error("DOM 文档不可用");
    const found = (await state.view.webContents.debugger.sendCommand(
      "DOM.querySelector", { nodeId: rootId, selector },
    )) as { nodeId?: number };
    if (found?.nodeId === undefined || found.nodeId === 0) {
      throw new Error(`selector 未命中：${selector}`);
    }
    const described = (await state.view.webContents.debugger.sendCommand(
      "DOM.describeNode", { nodeId: found.nodeId },
    )) as { node?: { backendNodeId?: number } };
    const backendNodeId = described?.node?.backendNodeId;
    if (backendNodeId === undefined) {
      throw new Error(`selector 节点不可用：${selector}`);
    }
    return { backendNodeId, label: `selector=${selector}` };
  }

  /** 节点 → 视口坐标（不可见先 scrollIntoViewIfNeeded 重试一次）。 */
  async function pointFor(
    backendNodeId: number,
    state: ViewState,
  ): Promise<{ x: number; y: number }> {
    attachDebugger(state.view);
    for (let attempt = 0; attempt < 2; attempt += 1) {
      const metrics = (await state.view.webContents.debugger.sendCommand(
        "Page.getLayoutMetrics", {},
      )) as {
        cssLayoutViewport?: { pageX?: number; pageY?: number };
        layoutViewport?: { pageX?: number; pageY?: number };
      };
      const viewport = metrics.cssLayoutViewport ??
        metrics.layoutViewport ?? {};
      const quads = (await state.view.webContents.debugger.sendCommand(
        "DOM.getContentQuads", { backendNodeId },
      )) as { quads?: number[][] };
      const point = quadsToPoint(quads?.quads ?? [], {
        pageX: Number(viewport.pageX ?? 0),
        pageY: Number(viewport.pageY ?? 0),
      });
      if (point !== null) return point;
      await state.view.webContents.debugger.sendCommand(
        "DOM.scrollIntoViewIfNeeded", { backendNodeId },
      );
    }
    throw new Error("元素不可见（无法定位坐标）——请重新取快照后重试");
  }

  async function clickAt(
    point: { x: number; y: number },
    state: ViewState,
  ): Promise<void> {
    attachDebugger(state.view);
    await state.view.webContents.debugger.sendCommand("Input.dispatchMouseEvent", {
      type: "mouseMoved", x: point.x, y: point.y,
    });
    const press = {
      x: point.x, y: point.y, button: "left" as const, clickCount: 1,
    };
    await state.view.webContents.debugger.sendCommand(
      "Input.dispatchMouseEvent", { type: "mousePressed", ...press },
    );
    await state.view.webContents.debugger.sendCommand(
      "Input.dispatchMouseEvent", { type: "mouseReleased", ...press },
    );
  }

  async function click(
    args: Record<string, unknown>,
    identity: BrowserIdentity,
  ): Promise<Record<string, unknown>> {
    const { state } = await acquire(identity);
    touch(identity.key);
    const node = await resolveNode(args, state);
    const point = await pointFor(node.backendNodeId, state);
    await clickAt(point, state);
    log(`[browser-view] click ${node.label} @ ${Math.round(point.x)},` +
        `${Math.round(point.y)}`);
    return {
      clicked: true, by: node.label,
      x: Math.round(point.x), y: Math.round(point.y),
      hint: `已点击 ${node.label}；请重新取快照查看页面变化`,
    };
  }

  async function type(
    args: Record<string, unknown>,
    identity: BrowserIdentity,
  ): Promise<Record<string, unknown>> {
    const { state } = await acquire(identity);
    touch(identity.key);
    attachDebugger(state.view);
    const node = await resolveNode(args, state);
    const point = await pointFor(node.backendNodeId, state);
    await clickAt(point, state);   // 真实点击聚焦（isTrusted）
    const text = String(args.text ?? "");
    if (text !== "") {
      await state.view.webContents.debugger.sendCommand("Input.insertText", { text });
    }
    const submit = args.submit === true;
    if (submit) {
      const key = {
        key: "Enter", code: "Enter",
        windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13,
      };
      await state.view.webContents.debugger.sendCommand(
        "Input.dispatchKeyEvent", { type: "keyDown", ...key },
      );
      await state.view.webContents.debugger.sendCommand(
        "Input.dispatchKeyEvent", { type: "keyUp", ...key },
      );
    }
    log(`[browser-view] type ${node.label} chars=${text.length} ` +
        `submit=${submit}`);
    return {
      typed: true, by: node.label, chars: text.length, submit,
      hint: `已输入 ${node.label}；请重新取快照查看结果`,
    };
  }

  async function wait(
    args: Record<string, unknown>,
    identity: BrowserIdentity,
  ): Promise<Record<string, unknown>> {
    const { state } = await acquire(identity);
    touch(identity.key);
    attachDebugger(state.view);
    const started = Date.now();
    if (typeof args.ms === "number") {
      const ms = Math.min(60_000, Math.max(0, Math.floor(args.ms)));
      await sleep(ms);
      return { found: true, mode: "ms", elapsed_ms: Date.now() - started };
    }
    const timeoutMs = Math.min(
      30_000, Math.max(1, Number(args.timeout_ms ?? 5000)),
    );
    const selector = typeof args.selector === "string" ? args.selector : "";
    if (selector !== "") {
      while (Date.now() - started <= timeoutMs) {
        const doc = (await state.view.webContents.debugger.sendCommand(
          "DOM.getDocument", {},
        )) as { root?: { nodeId?: number } };
        const rootId = doc?.root?.nodeId;
        if (rootId !== undefined) {
          const found = (await state.view.webContents.debugger.sendCommand(
            "DOM.querySelector", { nodeId: rootId, selector },
          )) as { nodeId?: number };
          if (found?.nodeId !== undefined && found.nodeId !== 0) {
            return { found: true, mode: "selector",
                     elapsed_ms: Date.now() - started };
          }
        }
        await sleep(200);
      }
      return { found: false, mode: "selector",
               elapsed_ms: Date.now() - started,
               note: `未在 ${timeoutMs}ms 内出现：${selector}` };
    }
    const text = typeof args.text === "string" ? args.text : "";
    while (Date.now() - started <= timeoutMs) {
      const ax = (await state.view.webContents.debugger.sendCommand(
        "Accessibility.getFullAXTree", {},
      )) as { nodes?: AxNodeLike[] };
      const hit = (ax?.nodes ?? []).some((n) =>
        String(n?.name?.value ?? "").includes(text));
      if (hit) {
        return { found: true, mode: "text",
                 elapsed_ms: Date.now() - started };
      }
      await sleep(200);
    }
    return { found: false, mode: "text",
             elapsed_ms: Date.now() - started,
             note: `未在 ${timeoutMs}ms 内出现文本：${text}` };
  }

  /** P3：表达式求值（固定参数 Runtime.evaluate；非任意 CDP 透传）。 */
  async function evaluate(
    args: Record<string, unknown>,
    identity: BrowserIdentity,
  ): Promise<Record<string, unknown>> {
    const { state } = await acquire(identity);
    touch(identity.key);
    attachDebugger(state.view);
    const expression = String(args.expression ?? "");
    const result = (await state.view.webContents.debugger.sendCommand(
      "Runtime.evaluate",
      {
        expression,
        returnByValue: true,
        awaitPromise: false,
        userGesture: false,
        timeout: 5000,
      },
    )) as {
      result?: { value?: unknown };
      exceptionDetails?: {
        text?: string;
        exception?: { description?: string };
      };
    };
    if (result?.exceptionDetails !== undefined) {
      const detail = result.exceptionDetails;
      const text = String(
        detail.exception?.description ?? detail.text ?? "未知异常",
      );
      return { value: null, exception: text };
    }
    const value = serializeValue(result?.result?.value);
    log(`[browser-view] evaluate chars=${value.length}`);
    return { value, exception: null };
  }

  /** v3：关闭目标视图（目标不存在 = 幂等 closed:false）；活跃关闭后回退次新。 */
  async function close(
    identity: BrowserIdentity,
  ): Promise<Record<string, unknown>> {
    const order = orderKeys();
    const wasActive = activeKey === identity.key;
    const closed = removeView(identity.key);
    if (wasActive) {
      const next = nextActive(order, identity.key);
      activate(next);
    }
    log(`[browser-view] close key=${identity.key} closed=${closed}`);
    return { closed, active: activeKey };
  }

  /** v3：视图清单（只读元数据——无 cookie/存储值）。 */
  async function listViews(): Promise<Record<string, unknown>> {
    return {
      views: [...views.entries()].map(([key, state]) => ({
        key,
        mode: state.identity.mode,
        workspace: state.identity.workspace,
        url: state.view.webContents.getURL(),
        title: state.view.webContents.getTitle(),
        last_active_ms: state.lastActiveMs,
        visible: key === activeKey,
      })),
      active: activeKey,
    };
  }

  /** 身份清除（§11.5-②）：关 base 全部视图（含 overlay）+ 清两档派生分区 + 注册表。 */
  async function identityClear(key: string): Promise<Record<string, unknown>> {
    const viewKeys = overlayKeysFor([...views.keys()], key);
    let closedViews = 0;
    for (const viewKey of viewKeys) {
      if (removeView(viewKey)) closedViews += 1;
    }
    if (activeKey !== null && !views.has(activeKey)) {
      const order = orderKeys();
      activate(order.length > 0 ? order[order.length - 1] : null);
    }
    const partitions = new Set<string>([key, `persist:${key}`]);
    for (const partition of overlayKeysFor([...memorySessions.keys()], key)) {
      partitions.add(partition);
    }
    let failures = 0;
    for (const partition of partitions) {
      try {
        const ses = session.fromPartition(partition);
        await ses.clearStorageData();
        await ses.clearCache();
        memorySessions.delete(partition);
      } catch (error) {
        failures += 1;
        log(`[browser-view] 身份清除失败（${partition}）：${String(error)}`);
      }
    }
    if (failures === partitions.size) {
      throw new Error(`身份清除失败（${key}）——会话数据不可清除`);
    }
    const removed = removeRegistry(key);
    log(`[browser-view] identity cleared key=${key} ` +
        `views=${closedViews} registry_removed=${removed}`);
    return { cleared: true, key, closed_views: closedViews,
             registry_removed: removed, partial: failures > 0 };
  }

  function dispose(): void {
    const win = options.getWindow();
    if (win !== null && !win.isDestroyed() && resizeHandler !== null) {
      win.removeListener("resize", resizeHandler);
    }
    resizeHandler = null;
    for (const key of [...views.keys()]) removeView(key);
    activate(null);
  }

  return {
    status: async () => ({
      app: "wuxing-shell",
      electron: process.versions.electron,
    }),
    open,
    snapshot,
    click,
    type,
    wait,
    evaluate,
    screenshot,
    close,
    views: listViews,
    identityClear,
    dispose,
  };
}
