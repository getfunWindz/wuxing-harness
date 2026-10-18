import { test } from "node:test";
import assert from "node:assert/strict";

import {
  deriveLiveChips,
  deriveRoundViews,
  deriveThinkingSummary,
} from "../src/views/view-model.ts";
import type { TaskRow, ThoughtRow } from "../src/runtime/services/tasks.ts";

function row(unitId: string, status: string, detail = "", domainId = "execute"): TaskRow {
  return {
    unitId, domainId, status: status as TaskRow["status"], detail, eta: "",
    failureClass: "", autoRetryKind: "", autoRetryN: 0,
  };
}

test("deriveLiveChips：≥2 个 running 才出现（线性不出现）；label 截断", () => {
  assert.deepEqual(deriveLiveChips([row("F-1", "running", "写报告")]), []);
  const chips = deriveLiveChips([
    row("F-1", "running", "写报告"),
    row("F-2", "running", "出方案", "plan"),
    row("F-3", "ok", "已完成"),
  ]);
  assert.equal(chips.length, 2);
  assert.equal(chips[1]?.domain, "plan");
  assert.equal(chips[1]?.label, "出方案");
  const long = deriveLiveChips([
    row("A", "running", "这是一段超过十二个字的碎片目标描述"),
    row("B", "running", "x"),
  ]);
  assert.ok(long[0]?.label.endsWith("…"));
  assert.ok((long[0]?.label.length ?? 0) <= 13);
});

test("deriveThinkingSummary：运行=末行、完成=首行（剥 **）；空=null", () => {
  const thoughts: ThoughtRow[] = [
    { unitId: "F-1", round: 1, text: "**方案**\n先查看仓库结构" },
    { unitId: "F-2", round: 1, text: "继续\n校对两处边界" },
  ];
  assert.equal(deriveThinkingSummary(thoughts, true), "校对两处边界");
  assert.equal(deriveThinkingSummary(thoughts, false), "方案");
  assert.equal(deriveThinkingSummary([], true), null);
});

test("deriveRoundViews：历史轮摘要（步骤数）+ 实时轮（thinking/chips）；终态产摘要", () => {
  const views = deriveRoundViews({
    transcript: [
      { kind: "user", text: "任务一", artifacts: [], round: 1 },
      { kind: "assistant", text: "结果一", artifacts: [], round: 1 },
    ],
    rounds: [{ round: 1, fragments: [{ duration_ms: 1500 }, { duration_ms: 2500 }] }],
    live: {
      taskText: "任务二",
      status: "running",
      rows: [row("F-9", "running", "写报告")],
      thoughts: [{ unitId: "F-9", round: 2, text: "先看结构" }],
    },
  });
  assert.equal(views.length, 2);
  assert.equal(views[0]?.answer, "结果一");
  assert.equal(views[0]?.chips.length, 0);
  assert.ok(views[0]?.summary?.includes("2"));
  assert.ok(views[0]?.summary?.includes("4s"));
  assert.equal(views[1]?.live, true);
  assert.equal(views[1]?.thinking, "先看结构");
  assert.equal(views[1]?.summary, null);

  const done = deriveRoundViews({
    transcript: [],
    live: {
      taskText: "任务三", status: "done",
      rows: [row("A", "ok"), row("B", "ok")], thoughts: [],
    },
  });
  assert.equal(done.length, 1);
  assert.equal(done[0]?.live, true);
  assert.ok(done[0]?.summary?.includes("2"));

  const merged = deriveRoundViews({
    transcript: [{ kind: "user", text: "任务四", artifacts: [], round: 1 }],
    live: {
      taskText: "任务四", status: "running",
      rows: [row("A", "running"), row("B", "running")], thoughts: [],
    },
  });
  assert.equal(merged.length, 1, "同一文本的实时轮不重复");
  assert.equal(merged[0]?.live, true);
  assert.equal(merged[0]?.chips.length, 2);
});
