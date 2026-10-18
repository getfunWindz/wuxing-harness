import { test } from "node:test";
import assert from "node:assert/strict";

import {
  buildConfirmItems,
  deriveArtifactLinks,
  deriveArtifactRows,
  deriveChatMessages,
  deriveConcurrency,
  deriveContextTarget,
  deriveDesignTicketRows,
  deriveEta,
  deriveFloatCardVisible,
  deriveFragmentDomains,
  deriveFscSummary,
  deriveRecoveryActions,
  deriveTopbarAttrs,
  deriveWorkspaceChips,
  domainLabel,
  implTicketStatusKey,
  isInternalArtifact,
  isOutsideWorkspace,
  normalizeTopbarVisible,
  rejectReasonMissing,
  shouldShowOnboard,
  shouldSubmit,
  statusLabel,
  summarizeTask,
  trimKeys,
} from "../src/views/view-model.ts";
import {
  INITIAL_TASK_STATE,
  type TaskState,
} from "../src/runtime/services/tasks.ts";

test("shouldSubmit：Enter 提交；Shift+Enter 与 IME 组字不提交", () => {
  assert.equal(shouldSubmit({ key: "Enter", shiftKey: false, isComposing: false }), true);
  assert.equal(shouldSubmit({ key: "Enter", shiftKey: true, isComposing: false }), false);
  assert.equal(shouldSubmit({ key: "Enter", shiftKey: false, isComposing: true }), false);
  assert.equal(shouldSubmit({ key: "a", shiftKey: false, isComposing: false }), false);
});

test("buildConfirmItems：单元集合 → [unit_id, approve] 对", () => {
  assert.deepEqual(buildConfirmItems(["u1", "u2"], true), [["u1", true], ["u2", true]]);
  assert.deepEqual(buildConfirmItems(["u3"], false), [["u3", false]]);
  assert.deepEqual(buildConfirmItems([], true), []);
});

test("rejectReasonMissing：驳回理由必填（trim 后为空即缺失）", () => {
  assert.equal(rejectReasonMissing(""), true);
  assert.equal(rejectReasonMissing("   "), true);
  assert.equal(rejectReasonMissing("不完整"), false);
  assert.equal(rejectReasonMissing("  不完整  "), false);
});

test("deriveWorkspaceChips：激活标记", () => {
  const list = [
    { id: "w1", path: "/a", name: "a", auto_confirm: false, status: "idle", folder: null },
    { id: "w2", path: "/b", name: "b", auto_confirm: false, status: "running", folder: null },
  ];
  const chips = deriveWorkspaceChips(list, "w2");
  assert.deepEqual(chips.map((chip) => [chip.id, chip.active]), [["w1", false], ["w2", true]]);
});

test("summarizeTask：状态/单元/待确认/错误", () => {
  assert.equal(summarizeTask(INITIAL_TASK_STATE), "就绪");
  const running: TaskState = {
    ...INITIAL_TASK_STATE,
    status: "running",
    rows: [
      { unitId: "u1", domainId: "execute", status: "running", detail: "写代码", eta: "1m", failureClass: "", autoRetryKind: "", autoRetryN: 0 },
      { unitId: "u2", domainId: "verify", status: "ok", detail: "", eta: "", failureClass: "", autoRetryKind: "", autoRetryN: 0 },
    ],
    pendingConfirms: [{ unit_id: "u9", domain_id: "plan", reason: "风险", impact: {}, view: {} }],
  };
  assert.equal(summarizeTask(running), "运行中 · 2 单元 · 待确认 1");
  const errored: TaskState = { ...INITIAL_TASK_STATE, status: "error", error: "炸了" };
  assert.equal(summarizeTask(errored), "错误 · 炸了");
  assert.equal(statusLabel("done"), "完成");
});

test("normalizeTopbarVisible：默认集/非法回退/声明顺序/窄屏前 2", () => {
  assert.deepEqual(normalizeTopbarVisible(null, false),
    ["conc", "ws", "cache", "ctx"]);
  assert.deepEqual(normalizeTopbarVisible(["fsc", "ws", "bogus"], false),
    ["ws", "fsc"], "存储顺序按声明顺序归一（ws 在前）");
  assert.deepEqual(normalizeTopbarVisible([], false), [], "空数组 = 全不选（不是默认）");
  assert.deepEqual(normalizeTopbarVisible(["calls", "fsc"], true),
    ["calls", "fsc"].slice(0, 2), "窄屏仅前 2");
  assert.deepEqual(normalizeTopbarVisible(null, true), ["conc", "ws"]);
});

test("deriveTopbarAttrs：旧壳 10 属性取值（缺失不造假）", () => {
  const state: TaskState = {
    ...INITIAL_TASK_STATE,
    pendingConfirms: [{ unit_id: "u1", domain_id: "execute", reason: "", impact: {}, view: {} }],
  };
  const workspaces = [
    { id: "w1", path: "/a", name: "a", auto_confirm: false, status: "running", folder: null },
    { id: "w2", path: "/b", name: "b", auto_confirm: false, status: "idle", folder: null },
  ] as const;
  const metrics = {
    llm_calls: 7,
    usage: { input: 100, output: 20, cache_read: 75 },
    usage_latest: { input: 100, output: 5, cache_read: 80 },
    cache: { reply: { hits: 3, misses: 1 } },
    fsc: { reused: 2, coverage: 0.5 },
  };
  const attrs = deriveTopbarAttrs([...workspaces], state, metrics);
  const byKey = new Map(attrs.map((a) => [a.key, a.value]));
  assert.deepEqual(attrs.map((a) => a.key),
    ["conc", "ws", "cache", "ctx", "pending", "reqHit", "tokensIn", "tokensOut", "calls", "fsc"]);
  assert.equal(byKey.get("conc"), "1");
  assert.equal(byKey.get("ws"), "2");
  assert.equal(byKey.get("cache"), "80%", "CH = 最近一次请求命中率（非累计 75%）");
  assert.equal(byKey.get("ctx"), "—");
  assert.equal(byKey.get("pending"), "1");
  assert.equal(byKey.get("reqHit"), "75%");
  assert.equal(byKey.get("tokensIn"), "100");
  assert.equal(byKey.get("tokensOut"), "20");
  assert.equal(byKey.get("calls"), "7");
  assert.equal(byKey.get("fsc"), "2");
  const bare = deriveTopbarAttrs([], INITIAL_TASK_STATE, null);
  assert.equal(new Map(bare.map((a) => [a.key, a.value])).get("cache"), "—");
  // 无 usage_latest（旧数据）→ 不拿累计冒充 CH（诚实留 —）
  const noLatest = deriveTopbarAttrs([], INITIAL_TASK_STATE,
    { usage: { input: 100, cache_read: 75 } });
  assert.equal(new Map(noLatest.map((a) => [a.key, a.value])).get("cache"), "—");
});

test("domainLabel／deriveFragmentDomains：域中文化 + 分布", () => {
  assert.equal(domainLabel("plan"), "规划");
  assert.equal(domainLabel("execute"), "执行");
  assert.equal(domainLabel("unknown"), "unknown", "未知域回 id（不造假）");
  assert.equal(domainLabel(""), "—");
  const rows = [
    { unitId: "u1", domainId: "execute", status: "ok", detail: "", eta: "", failureClass: "", autoRetryKind: "", autoRetryN: 0 },
    { unitId: "u2", domainId: "verify", status: "ok", detail: "", eta: "", failureClass: "", autoRetryKind: "", autoRetryN: 0 },
    { unitId: "u3", domainId: "execute", status: "running", detail: "", eta: "", failureClass: "", autoRetryKind: "", autoRetryN: 0 },
  ] as const;
  assert.equal(deriveFragmentDomains([...rows]), "执行 2 / 验证 1");
  assert.equal(deriveFragmentDomains([]), "—");
});

test("deriveEta／deriveConcurrency：预计时间与并发", () => {
  const rows = [
    { unitId: "u1", domainId: "execute", status: "ok", detail: "", eta: "1m", failureClass: "", autoRetryKind: "", autoRetryN: 0 },
    { unitId: "u2", domainId: "execute", status: "running", detail: "", eta: "2m", failureClass: "", autoRetryKind: "", autoRetryN: 0 },
  ] as const;
  const state: TaskState = { ...INITIAL_TASK_STATE, rows: [...rows] };
  assert.equal(deriveEta(state), "2m", "取最后一条非空 eta");
  assert.equal(deriveEta(INITIAL_TASK_STATE), "");
  assert.equal(deriveConcurrency(state, 8), "1 / 8");
  assert.equal(deriveConcurrency(state, null), "1");
});

test("deriveContextTarget：无活动会话回退最近会话并显式标注（U11）", () => {
  assert.deepEqual(deriveContextTarget("conversation-a.jsonl", ["x", "y"]),
    { target: "conversation-a.jsonl", fallback: false });
  assert.deepEqual(deriveContextTarget(null, ["x", "y"]),
    { target: "x", fallback: true }, "无活动会话 → 最近会话 + 标注来源");
  assert.deepEqual(deriveContextTarget(null, []),
    { target: null, fallback: false }, "无会话可回退 → 空态");
});

test("deriveFloatCardVisible：空闲/空工作区隐藏，有任务活动才显示（U6）", () => {
  const idle: TaskState = { ...INITIAL_TASK_STATE, workspaceId: "ws-1" };
  assert.equal(deriveFloatCardVisible(true, idle), false, "空工作区空闲不显示");
  assert.equal(deriveFloatCardVisible(true, INITIAL_TASK_STATE), false, "无工作区不显示");
  assert.equal(deriveFloatCardVisible(false, { ...idle, taskText: "t" }), false, "开关关闭不显示");
  assert.equal(deriveFloatCardVisible(true, { ...idle, taskText: "任务" }), true);
  assert.equal(deriveFloatCardVisible(true, { ...idle, runId: "r1" }), true, "运行绑定即可见");
  assert.equal(deriveFloatCardVisible(true, { ...idle, status: "running" }), true, "运行中即便暂无文本也显示");
  assert.equal(
    deriveFloatCardVisible(true, {
      ...idle,
      rows: [{ unitId: "u1", domainId: "execute", status: "running", detail: "", eta: "", failureClass: "", autoRetryKind: "", autoRetryN: 0 }],
    }),
    true,
    "有单元行即可见",
  );
});

test("deriveFscSummary：指标优先／事件行回退／无则「—」", () => {
  const state: TaskState = { ...INITIAL_TASK_STATE };
  const summary = deriveFscSummary(state,
    { fsc: { reused: 3, coverage: 0.87 } });
  assert.ok(summary.includes("3"), summary);
  assert.ok(summary.includes("87%"), summary);
  assert.equal(deriveFscSummary(state, null), "—");
  const withEvents: TaskState = {
    ...state,
    fsc: [
      { unitId: "u1", domainId: "execute", ratio: 0.5, kind: "audit", seq: 1 },
      { unitId: "u1", domainId: "execute", ratio: 0.8, kind: "switch", seq: 2 },
    ],
  };
  const fallback = deriveFscSummary(withEvents, null);
  assert.ok(fallback.includes("1"), fallback);
});

test("trimKeys：超限保留最新 N 个（不超限原样复制）", () => {
  assert.deepEqual(trimKeys(["a", "b"], 400), ["a", "b"]);
  assert.deepEqual(trimKeys(["a", "b", "c", "d"], 2), ["c", "d"]);
  assert.deepEqual(trimKeys([], 2), []);
  assert.deepEqual(trimKeys(["a"], 0), ["a"], "max<=0 视为不裁剪");
});

test("isOutsideWorkspace：大小写/分隔符/边界", () => {
  assert.equal(isOutsideWorkspace("C:\\ws\\a.md", "C:\\ws"), false);
  assert.equal(isOutsideWorkspace("c:/WS/sub/a.md", "C:\\ws"), false, "大小写不敏感");
  assert.equal(isOutsideWorkspace("C:\\ws2\\a.md", "C:\\ws"), true, "前缀边界不得误判");
  assert.equal(isOutsideWorkspace("D:\\other\\a.md", "C:\\ws"), true);
  assert.equal(isOutsideWorkspace("C:\\ws", "C:\\ws\\"), false, "尾分隔符归一");
  assert.equal(isOutsideWorkspace("", "C:\\ws"), false, "空路径不标外部");
  assert.equal(isOutsideWorkspace("C:\\ws\\a.md", ""), false, "无工作区不标外部");
});

test("deriveChatMessages：轮次行 → 用户+助手双侧消息（修复②）", () => {
  const msgs = deriveChatMessages([
    { round: 1, user_text: "你好", summary: "done；交付物 a.md", artifacts: ["a.md"], ts: 1 },
    { round: 2, user_text: "继续", summary: "failed", artifacts: [], ts: 2 },
  ]);
  assert.deepEqual(msgs.map((m) => [m.kind, m.text]), [
    ["user", "你好"], ["assistant", "done；交付物 a.md"],
    ["user", "继续"], ["assistant", "failed"],
  ]);
  assert.deepEqual(msgs[1]!.artifacts, ["a.md"]);
  assert.equal(msgs[0]?.ts, 1, "用户气泡带时间戳");
  assert.equal(msgs[1]?.ts, 1, "助手气泡带同一轮时间戳");
  assert.equal(msgs[2]?.ts, 2);
});

test("deriveChatMessages：role/content 与 messages[] 形状 + 破损行跳过", () => {
  const msgs = deriveChatMessages([
    { role: "user", content: "问一句" },
    { role: "assistant", content: "答一句" },
    { messages: [{ role: "user", content: "内层问" }, { role: "assistant", content: "内层答" }] },
    { broken: true },
    { user_text: "" },
  ]);
  assert.deepEqual(msgs.map((m) => [m.kind, m.text]), [
    ["user", "问一句"], ["assistant", "答一句"],
    ["user", "内层问"], ["assistant", "内层答"],
  ]);
});

test("恢复动作：needs_design → override（跳过设计仍要执行）", () => {
  const actions = deriveRecoveryActions("needs_design");
  assert.deepEqual(actions.map((a) => a.id), ["override"]);
  assert.deepEqual(deriveRecoveryActions("done").map((a) => a.id),
    ["retry", "rollback"]);
});

test("设计票据行：票据优先；旧态回落问题列表（兼容）", () => {
  const rows = deriveDesignTicketRows(
    [{ id: "Q-1", statement: "A", recommend: "a", blocked_by: [], frontier: true }],
    [{ q: "旧问题", recommend: "r" }]);
  assert.deepEqual(rows.map((r) => [r.id, r.statement, r.frontier]),
    [["Q-1", "A", true]]);
  const fallback = deriveDesignTicketRows([], [{ q: "旧问题", recommend: "r" }]);
  assert.equal(fallback[0]?.id, "");
  assert.equal(fallback[0]?.statement, "旧问题");
});

test("实施票据状态 key：全状态可读（审查 F3——done/failed 不得显示成待发布）", () => {
  assert.equal(implTicketStatusKey("proposed"), "design.ticketProposed");
  assert.equal(implTicketStatusKey("ready"), "design.ticketReady");
  assert.equal(implTicketStatusKey("running"), "design.ticketRunning");
  assert.equal(implTicketStatusKey("done"), "design.ticketDone");
  assert.equal(implTicketStatusKey("failed"), "design.ticketFailed");
  assert.equal(implTicketStatusKey("cancelled"), "design.ticketCancelled");
  assert.equal(implTicketStatusKey("unknown"), "design.ticketProposed");
});

test("产物视图屏蔽内部收纳路径（.wuxing/reports 等——2026-10-01 用户裁决）", () => {
  const rows = deriveArtifactRows({
    status: "done",
    report: "",
    artifacts: [
      { path: "index.html", kind: "" },
      { path: ".wuxing/reports/F-0001-result.md", kind: "result" },
      { path: "src/a.js", kind: "" },
    ],
    metrics: {},
  } as never);
  assert.deepEqual(rows.map((r) => r.path), ["index.html", "src/a.js"]);
  const links = deriveArtifactLinks({
    status: "done",
    report: "",
    artifacts: [
      { path: "index.html", kind: "" },
      { path: ".wuxing/reports/F-0001-result.md", kind: "result" },
    ],
    metrics: {},
  } as never, [], "w1");
  assert.deepEqual(links.map((l) => l.path), ["index.html"]);
  assert.equal(isInternalArtifact(".wuxing/reports/x.md"), true);
  assert.equal(isInternalArtifact(".wuxing/truncated/x.txt"), true);
  assert.equal(isInternalArtifact("index.html"), false);
});

test("deriveChatMessages（Task 4-3）：助手文本优先 reply（模型总体回复），无则回退 summary", () => {
  const rows = [
    { round: 1, user_text: "做站点", summary: "done；交付物 a.md",
      reply: "总体回复：站点已完成", artifacts: ["a.md"] },
    { round: 2, user_text: "改一版", summary: "done；交付物 b.md", artifacts: ["b.md"] },
    { round: 3, user_text: "空回复", summary: "done", reply: "   ", artifacts: [] },
  ];
  const msgs = deriveChatMessages(rows);
  const assistants = msgs.filter((m) => m.kind === "assistant");
  assert.equal(assistants[0]?.text, "总体回复：站点已完成");
  assert.equal(assistants[1]?.text, "done；交付物 b.md", "无 reply 回退机械 summary");
  assert.equal(assistants[2]?.text, "done", "空白 reply 回退机械 summary");
});

test("shouldShowOnboard：零态且无记账才显示（T-6）", () => {
  assert.equal(shouldShowOnboard({ heroVisible: true, done: false }), true);
  assert.equal(shouldShowOnboard({ heroVisible: true, done: true }), false);
  assert.equal(shouldShowOnboard({ heroVisible: false, done: false }), false);
  assert.equal(shouldShowOnboard({ heroVisible: false, done: true }), false);
});
