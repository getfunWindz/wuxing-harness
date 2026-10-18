import { test } from "node:test";
import assert from "node:assert/strict";

import { deriveChatMessages, deriveSessionRows } from "../src/views/view-model.ts";

const SESSIONS = [
  {
    name: "conversation-1.jsonl", size: 100, mtime: 0, path: "/w/.wuxing/c1",
    title: "源会话", branched_from: null,
  },
  {
    name: "conversation-2.jsonl", size: 120, mtime: 0, path: "/w/.wuxing/c2",
    title: "分支会话",
    branched_from: { source: "conversation-1.jsonl", from_round: 3, mode: "redo", summary_mode: "mech" },
  },
] as const;

test("deriveSessionRows：分支血缘 → 徽标数据（源/轮次；无血缘 → null）", () => {
  const rows = deriveSessionRows([...SESSIONS] as never);
  assert.equal(rows.length, 2);
  assert.equal(rows[0]!.branchedFrom, null);
  assert.deepEqual(rows[1]!.branchedFrom,
    { source: "conversation-1", fromRound: 3 });
});

test("deriveSessionRows：血缘缺失/畸形 → 不渲染徽标", () => {
  const rows = deriveSessionRows([
    { name: "conversation-3.jsonl", size: 1, mtime: 0, path: "/x", title: "",
      branched_from: { source: "", from_round: 0 } },
    { name: "conversation-4.jsonl", size: 1, mtime: 0, path: "/x", title: "",
      branched_from: { source: "conversation-1.jsonl" } },
  ] as never);
  assert.equal(rows[0]!.branchedFrom, null);
  assert.equal(rows[1]!.branchedFrom, null);
});

test("deriveChatMessages：承接行不产生聊天消息（G1）", () => {
  const rows = [
    { round: 1, user_text: "第一轮", summary: "done", artifacts: [] },
    { type: "branch", source: "conversation-o.jsonl", from_round: 1,
      mode: "redo", summary_mode: "mech", summary: "旧路径小结", ts: 2 },
    { round: 2, user_text: "第二轮", summary: "done", artifacts: ["a.txt"] },
  ];
  const msgs = deriveChatMessages(rows);
  assert.deepEqual(msgs.map((m) => [m.kind, m.text]),
    [["user", "第一轮"], ["assistant", "done"],
     ["user", "第二轮"], ["assistant", "done"]]);
});
