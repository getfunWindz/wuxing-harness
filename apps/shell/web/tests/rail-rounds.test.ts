import { test } from "node:test";
import assert from "node:assert/strict";

import { deriveRailRounds, deriveRoundChips, deriveFragmentConversation } from "../src/views/view-model.ts";

test("deriveRailRounds：仅并行碎片出小字行；线性轮不出现；label 截断", () => {
  const rounds = [
    {
      round: 1, user_text: "线性任务", parallel: false,
      fragments: [{ unit_id: "L-1", domain: "execute", goal: "线性步骤", status: "ok", parallel: false }],
    },
    {
      round: 2, user_text: "并行任务示例文本很长", parallel: true,
      fragments: [
        { unit_id: "P-a", domain: "execute", goal: "分支A目标", status: "ok", parallel: true },
        { unit_id: "P-b", domain: "plan", goal: "分支B目标", status: "failed", parallel: false },
      ],
    },
  ];
  const tree = deriveRailRounds(rounds);
  assert.equal(tree.length, 1, "线性轮不出树");
  assert.equal(tree[0]?.round, 2);
  assert.deepEqual(tree[0]?.fragments.map((f) => f.unitId), ["P-a"], "非并行碎片不入树");
  assert.ok((tree[0]?.label.length ?? 99) <= 13, "轮标签截断");
});

test("deriveRoundChips：并行轮返回 摘要+chips（含状态）；线性轮 null", () => {
  const rounds = [
    { round: 1, fragments: [
      { unit_id: "L-1", domain: "execute", goal: "线性", status: "ok", parallel: false, duration_ms: 1000 }] },
    { round: 2, fragments: [
      { unit_id: "P-a", domain: "execute", goal: "撰写变更摘要", status: "ok", parallel: true, duration_ms: 15000 },
      { unit_id: "P-b", domain: "execute", goal: "撰写使用说明", status: "ok", parallel: true, duration_ms: 18000 }] },
  ];
  assert.equal(deriveRoundChips(rounds, 1), null, "线性轮不上富化");
  const e = deriveRoundChips(rounds, 2);
  assert.ok(e !== null);
  assert.equal(e?.chips.length, 2);
  assert.equal(e?.chips[0]?.unitId, "P-a");
  assert.equal(e?.chips[0]?.status, "ok");
  assert.ok(e?.summary.includes("2"));
});

test("deriveFragmentConversation：thinking→折叠思维链块；done→状态行", () => {
  const items = deriveFragmentConversation([
    { state: "seed", messages: [{ role: "system", content: "sys" }, { role: "user", content: "任务" }] },
    { state: "thinking", messages: [{ role: "user", content: "推理文本\n第二行" }, { role: "user", content: "[tool] write_artifact: ok" }] },
    { state: "done", messages: [] },
  ]);
  assert.deepEqual(items.map((i) => i.kind), ["system", "user", "think", "tool", "status"]);
  assert.equal(items[2]?.text, "推理文本\n第二行");
});
