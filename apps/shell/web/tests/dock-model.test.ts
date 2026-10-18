import { test } from "node:test";
import assert from "node:assert/strict";

import type { McpStatusDto, NotificationDto, ResultDto, TaskHistoryRowDto } from "../src/protocol/generated.ts";
import type { TaskStatus } from "../src/runtime/services/tasks.ts";
import {
  defaultDockCollapsed,
  deriveArtifactRows,
  deriveBrainRows,
  deriveDiscoverRows,
  deriveEventLogRows,
  deriveMcpRows,
  deriveNoticeRows,
  deriveProvenanceRows,
  deriveReportRows,
  deriveSkillRows,
  deriveTaskRows,
  deriveThoughtRows,
  deriveArtifactLinks,
  deriveRecoveryActions,
  deriveSearchRows,
  deriveTraceRows,
  deriveUsageRows,
  filterPaletteCommands,
  IDLE_DOCK_STATE,
  nextDockState,
} from "../src/views/view-model.ts";

test("deriveArtifactRows：结果快照 → 产物行（mtime 透传；null 安全）", () => {
  assert.deepEqual(deriveArtifactRows(null), []);
  const result = {
    status: "done", report: "",
    artifacts: [{ path: "a.md", kind: "md", mtime: 1700000000 }],
    metrics: {}, units: [],
  } as unknown as ResultDto;
  assert.deepEqual(deriveArtifactRows(result),
    [{ path: "a.md", kind: "md", mtime: 1700000000 }]);
});

test("deriveSkillRows：名称/描述/级别/启停透传", () => {
  const rows = deriveSkillRows([
    { name: "find-skill", description: "内置技能：检索与发现", level: "builtin", enabled: true,
      model_invocable: true, user_invocable: true, allowed_tools: [] },
    { name: "off-skill", description: "已停用技能", level: "fragment", enabled: false,
      model_invocable: true, user_invocable: true, allowed_tools: [] },
  ]);
  assert.deepEqual(rows, [
    { name: "find-skill", description: "内置技能：检索与发现", level: "builtin", enabled: true },
    { name: "off-skill", description: "已停用技能", level: "fragment", enabled: false },
  ]);
});

test("deriveMcpRows：命令/工具权限行 + 工具数/调用数（插值）", () => {
  const status = {
    enabled: true,
    servers: [{
      name: "demo-mcp", command: "npx", args: ["-y", "demo-mcp"],
      tools: [{ name: "search", permissions: { read: true, write: false } }],
      stats: { connections: 2, calls: 17 },
    }],
  } as unknown as McpStatusDto;
  assert.deepEqual(deriveMcpRows(status), [{
    name: "demo-mcp",
    command: "npx -y demo-mcp",
    tools: [{ name: "search", permissions: "read" }],
    detail: "1 个工具 · 17 次调用",
  }]);
  assert.deepEqual(deriveMcpRows(null), []);
});

test("deriveTaskRows：状态点/文案/时间/产物（含回滚状态）", () => {
  const rows = deriveTaskRows([
    {
      run_id: "r1", ws_id: "w1", task_text: "生成摘要", status: "done",
      started_at: 1700000000, ended_at: 1700000060, artifacts: 2, error: "",
    },
    {
      run_id: "r2", ws_id: "w1", task_text: "重写 README", status: "rolled_back",
      started_at: 1700000100, ended_at: 1700000130, artifacts: 0, error: "",
    },
  ] as unknown as TaskHistoryRowDto[]);
  assert.equal(rows[0]?.dot, "ok");
  assert.ok(rows[0]?.status.includes("完成"));
  assert.ok(rows[0]?.meta.includes("2 产物"));
  assert.equal(rows[1]?.dot, "");
  assert.ok(rows[1]?.status.includes("回滚"));
});

test("deriveUsageRows：分组行 + 缺失留 — + 空指标 → 空", () => {
  assert.deepEqual(deriveUsageRows(null), []);
  assert.deepEqual(deriveUsageRows({}), []);
  const sections = deriveUsageRows({
    llm_calls: 3,
    usage: { input: 1000, output: 200, cache_read: 700, cache_write: 100 },
    usage_latest: { input: 100, output: 5, cache_read: 80, cache_write: 0 },
    cache: { reply: { hits: 2, misses: 1, similar_hits: 0 }, shape: { hits: 1, misses: 0 } },
    breakdown: { semantic_hits: 0, semantic_ok: 0, first_round_misses: 1, later_round_misses: 0 },
    cost: { estimate: 0.01, save_tokens: 700, save_cost: 0.005, cache_read_ratio: 0.7 },
    fsc: { reused: 2, sessions: 1, coverage: 0.5, audited: 0, switched: 0 },
  });
  const flat = sections.flatMap((s) => s.rows);
  assert.ok(flat.some((r) => r.value === "3"), "调用数");
  assert.ok(flat.some((r) => r.value === "80.0%"), "CH 最近请求（主口径）");
  assert.ok(flat.some((r) => r.value === "70.0%"), "累计 token 命中（旁系）");
  assert.ok(flat.some((r) => r.value.includes("0.01")), "成本估算");
  const noFsc = deriveUsageRows({ usage: { input: 1 } });
  const noFscFlat = noFsc.flatMap((s) => s.rows);
  assert.ok(noFscFlat.every((r) => r.value !== undefined));
  assert.ok(noFscFlat.some((r) => r.value === "—"), "缺失留 —");
});

test("deriveUsageRows：CH 三分行（首/续/辅助——E0-6）", () => {
  const sections = deriveUsageRows({
    usage: { input: 1000 },
    ch_split: {
      first: { calls: 2, ratio: 0.2 },
      continuation: { calls: 3, ratio: 0.9 },
      auxiliary: { calls: 1, ratio: 0.5, kinds: { shape: 1 } },
      miss_reasons: { new_session: 2 },
    },
  });
  const flat = sections.flatMap((s) => s.rows);
  assert.ok(
    flat.some((r) => r.key === "首调用 CH" && r.value.includes("20.0%")),
    "首调用行",
  );
  assert.ok(
    flat.some((r) => r.key === "延续 CH" && r.value.includes("90.0%")),
    "延续行",
  );
  assert.ok(
    flat.some((r) => r.key === "辅助 CH" && r.value.includes("50.0%")),
    "辅助行",
  );
  const none = deriveUsageRows({ usage: { input: 1 } });
  const noneFlat = none.flatMap((s) => s.rows);
  assert.ok(
    noneFlat.some((r) => r.key === "首调用 CH" && r.value === "—"),
    "缺失留 —",
  );
});

test("deriveProvenanceRows：父子树缩进 + 状态点", () => {
  const rows = deriveProvenanceRows([
    { provenance_id: "a", unit_id: "u1", parent_id: "", domain: "execute", status: "ok", artifacts: ["x"], ts: 1 },
    { provenance_id: "b", unit_id: "u2", parent_id: "u1", domain: "verify", status: "failed", artifacts: [], ts: 2 },
  ]);
  assert.deepEqual(rows.map((r) => [r.unitId, r.depth, r.dot]), [["u1", 0, "ok"], ["u2", 1, "bad"]]);
  assert.ok(rows[0]?.detail.includes("1 产物"));
  assert.deepEqual(deriveProvenanceRows([]), []);
});

test("deriveTraceRows/deriveEventLogRows：防御字段 + 详情拼接", () => {
  const rows = deriveTraceRows([
    { ts: 5, event: "unit_start", unit_id: "u1", domain: "execute", round: 1 },
  ]);
  assert.equal(rows[0]?.event, "unit_start");
  assert.ok(rows[0]?.detail.includes("round=1"));
  const logs = deriveEventLogRows([
    { ts: 5, type: "task_done", workspace_id: "w1", data: { status: "done" } },
  ]);
  assert.equal(logs[0]?.type, "task_done");
  assert.ok(logs[0]?.detail.includes("w1"));
  assert.deepEqual(deriveTraceRows([]), []);
  assert.deepEqual(deriveEventLogRows([]), []);
});

test("deriveNoticeRows：类型/级别映射", () => {
  const rows = deriveNoticeRows([
    { seq: 1, ts: 5, type: "task_done", level: "ok", workspace_id: "w1", workspace_name: "ws", run_id: "r", status: "done", reason: "", tool: "" },
    { seq: 2, ts: 6, type: "safety_blocked", level: "warn", workspace_id: "w1", workspace_name: "ws", run_id: "r", status: "", reason: "危险", tool: "bash" },
  ] as unknown as NotificationDto[]);
  assert.ok(rows[0]?.title.includes("完成"));
  assert.ok(rows[1]?.title.includes("bash"));
  assert.equal(rows[1]?.level, "warn");
});

test("deriveBrainRows：摘要/最近案例/空", () => {
  const view = deriveBrainRows({
    cases: 3, attempts: 4, success_count: 3, success_rate: 0.75,
    tiers: { high: 1, normal: 1, low: 1 }, capacity: 500, enabled: false,
    recent: [{ key: "k", domain: "execute", model: "m", tier: "high", attempts: 2, success_rate: 1, last_at: 1 }],
  });
  assert.ok(view.summary.some((r) => r.value === "3 / 500"));
  assert.equal(view.recent[0]?.title, "k");
  assert.equal(view.recent[0]?.level, "ok");
  assert.deepEqual(deriveBrainRows(null).summary, []);
});

test("deriveReportRows：大小格式化", () => {
  const rows = deriveReportRows([
    { name: "报告.md", path: "docs/报告.md", size: 2048, mtime: 1700000000 },
  ]);
  assert.equal(rows[0]?.name, "报告.md");
  assert.ok(rows[0]?.detail.includes("2.0 KB"));
});

test("deriveDiscoverRows：名称 + 描述/摘要防御", () => {
  const rows = deriveDiscoverRows([
    { name: "demo-skill", description: "演示发现" },
    { name: "b-skill", summary: "摘要字段" },
    { name: "" },
  ]);
  assert.deepEqual(rows.map((r) => r.name), ["demo-skill", "b-skill", "—"]);
  assert.ok(rows[0]?.detail.includes("演示发现"));
  assert.ok(rows[1]?.detail.includes("摘要字段"));
  assert.deepEqual(deriveDiscoverRows([]), []);
});

test("nextDockState：加载态机", () => {
  assert.equal(nextDockState(IDLE_DOCK_STATE, "load").status, "loading");
  assert.equal(nextDockState({ status: "loading", error: "" }, "ready").status, "ready");
  assert.deepEqual(nextDockState({ status: "loading", error: "" }, "fail", "boom"),
    { status: "error", error: "boom" });
  assert.equal(nextDockState({ status: "error", error: "x" }, "load").status, "loading");
  assert.equal(nextDockState({ status: "ready", error: "" }, "invalidate").status, "idle");
});

test("deriveThoughtRows：运行中 open / 终态折叠", () => {
  const thoughts = [{ unitId: "u1", round: 1, text: "思路" }];
  assert.deepEqual(deriveThoughtRows(thoughts, false), [
    { unitId: "u1", round: 1, text: "思路", open: true },
  ]);
  assert.equal(deriveThoughtRows(thoughts, true)[0]?.open, false);
  assert.deepEqual(deriveThoughtRows([], true), []);
});

test("deriveArtifactLinks：结果+单元产物去重 + URL 编码", () => {
  const result = {
    status: "done", report: "", metrics: {},
    artifacts: [{ path: "docs/报告.md", kind: "md" }],
  } as unknown as ResultDto;
  const links = deriveArtifactLinks(result, [
    { unitId: "u1", path: "docs/报告.md", kind: "md" },
    { unitId: "u1", path: "src/a b.py", kind: "py" },
  ], "w1");
  assert.deepEqual(links.map((l) => [l.unitId, l.path]), [
    ["", "docs/报告.md"],
    ["u1", "src/a b.py"],
  ]);
  assert.ok(links[0]?.url.includes("w1"));
  assert.ok(links[0]?.url.includes(encodeURI("docs/报告.md")));
  assert.ok(links[1]?.url.includes(encodeURI("src/a b.py")));
  assert.deepEqual(deriveArtifactLinks(null, [], "w1"), []);
});

test("deriveRecoveryActions：状态 → 动作可见性", () => {
  const ids = (status: string) => deriveRecoveryActions(status as TaskStatus).map((a) => a.id);
  assert.deepEqual(ids("done"), ["retry", "rollback"]);
  assert.deepEqual(ids("partial"), ["retry", "rollback"]);
  assert.deepEqual(ids("failed"), ["retry", "rollback"]);
  assert.deepEqual(ids("error"), ["retry", "resume"]);
  assert.deepEqual(ids("cancelled"), ["retry", "resume"]);
  assert.deepEqual(ids("running"), []);
  assert.deepEqual(ids("pending"), []);
});

test("deriveSearchRows：任务/会话分组行 + 状态文案", () => {
  const rows = deriveSearchRows({
    tasks: [{ kind: "task", ws_id: "w1", ws_name: "ws", run_id: "r1", text: "生成摘要", status: "done", ts: 1 }],
    sessions: [{ kind: "session", ws_id: "w1", ws_name: "ws", name: "conversation-1.jsonl", snippet: "摘要", mtime: 1 }],
  });
  assert.deepEqual(rows.map((r) => r.kind), ["task", "session"]);
  assert.ok(rows[0]?.meta.includes("完成"));
  assert.ok(rows[1]?.title.includes("conversation-1.jsonl"));
  assert.ok(rows[1]?.meta.includes("摘要"));
  assert.deepEqual(deriveSearchRows(null), []);
});

test("filterPaletteCommands：空查询全量 + 关键词过滤", () => {
  const commands = [
    { title: "打开设置", keywords: "settings" },
    { title: "搜索", keywords: "search" },
  ];
  assert.equal(filterPaletteCommands(commands, "").length, 2);
  assert.deepEqual(filterPaletteCommands(commands, "SEARCH").map((c) => c.title), ["搜索"]);
  assert.deepEqual(filterPaletteCommands(commands, "不存在"), []);
});

test("defaultDockCollapsed：无持久值时窄屏收起/桌面展开；持久值优先", () => {
  assert.equal(defaultDockCollapsed(null, true), true);
  assert.equal(defaultDockCollapsed(null, false), false);
  assert.equal(defaultDockCollapsed("0", true), false);
  assert.equal(defaultDockCollapsed("1", false), true);
});
