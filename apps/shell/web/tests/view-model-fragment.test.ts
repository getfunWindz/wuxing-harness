import { test } from "node:test";
import assert from "node:assert/strict";

import {
  deriveBoundRoundItems,
  deriveFragmentLive,
} from "../src/views/view-model.ts";
import type { TaskRow, ThoughtRow } from "../src/runtime/services/tasks.ts";

function row(unitId: string, status: string, detail = "", domainId = "execute"): TaskRow {
  return {
    unitId, domainId, status: status as TaskRow["status"], detail, eta: "",
    failureClass: "", autoRetryKind: "", autoRetryN: 0,
  };
}

function thought(unitId: string, text: string): ThoughtRow {
  return { unitId, round: 1, text };
}

const base = {
  unitId: "P-a",
  boundRunId: null,
  runId: "r1",
  status: "running",
  taskText: "主会话任务",
  rows: [row("P-a", "running", "分支A"), row("P-b", "running", "分支B", "plan")],
  thoughts: [thought("P-a", "分支A 思路"), thought("P-b", "分支B 思路")],
  boundUserTexts: [] as string[],
};

test("deriveFragmentLive：非绑定 run 按 unit 过滤（维度隔离）", () => {
  const live = deriveFragmentLive(base);
  assert.ok(live !== null);
  assert.deepEqual(live.rows.map((r) => r.unitId), ["P-a"]);
  assert.deepEqual(live.thoughts.map((t) => t.unitId), ["P-a"]);
  assert.equal(live.running, true);
  assert.equal(live.showUser, false, "主会话任务的用户气泡不在碎片视图显示");
  assert.equal(live.steps, 1);
});

test("deriveFragmentLive：绑定 run 全量（该轮=碎片自己的任务）+ showUser", () => {
  const live = deriveFragmentLive({
    ...base,
    boundRunId: "r1",
    taskText: "碎片内提交",
  });
  assert.ok(live !== null);
  assert.deepEqual(live.rows.map((r) => r.unitId), ["P-a", "P-b"]);
  assert.deepEqual(live.thoughts.map((t) => t.unitId), ["P-a", "P-b"]);
  assert.equal(live.showUser, true);
  assert.equal(live.chips.length, 2, "≥2 running → chips");
});

test("deriveFragmentLive：已入绑定轮次后不再重复显示实时用户气泡", () => {
  const live = deriveFragmentLive({
    ...base,
    boundRunId: "r1",
    taskText: "碎片内提交",
    boundUserTexts: ["碎片内提交"],
  });
  assert.ok(live !== null);
  assert.equal(live.showUser, false);
});

test("deriveFragmentLive：idle → null；非绑定且无该 unit 数据 → null", () => {
  assert.equal(deriveFragmentLive({ ...base, status: "idle" }), null);
  assert.equal(deriveFragmentLive({
    ...base, rows: [row("X-1", "running", "别的")], thoughts: [],
  }), null);
});

test("deriveFragmentLive：终态 running=false 且思维链折叠（open=false）", () => {
  const live = deriveFragmentLive({ ...base, status: "done" });
  assert.ok(live !== null);
  assert.equal(live.running, false);
  assert.ok(live.thoughts.every((t) => t.open === false), "完成即折叠");
});

test("deriveBoundRoundItems：轮次排序 + 用户/助手成对 + artifacts 附加", () => {
  const items = deriveBoundRoundItems([
    { round: 3, user_text: "第三轮", summary: "完成3", ts: 30, artifacts: [] },
    { round: 2, user_text: "第二轮", summary: "完成2", ts: 20, artifacts: ["a.md"] },
    { round: 1, user_text: "", summary: "空用户跳过", ts: 10, artifacts: [] },
  ]);
  assert.deepEqual(items.map((i) => i.kind), ["user", "assistant", "user", "assistant"]);
  assert.equal(items[0]?.text, "第二轮");
  assert.equal(items[1]?.text, "完成2");
  assert.deepEqual(items[1]?.artifacts, ["a.md"]);
  assert.equal(items[2]?.text, "第三轮");
});

test("deriveBoundRoundItems：空摘要且无产物 → 不生成助手项", () => {
  const items = deriveBoundRoundItems([
    { round: 1, user_text: "只有用户", summary: "", ts: 1, artifacts: [] },
  ]);
  assert.deepEqual(items.map((i) => i.kind), ["user"]);
});
