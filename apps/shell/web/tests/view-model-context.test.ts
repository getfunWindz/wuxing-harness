import { test } from "node:test";
import assert from "node:assert/strict";

import {
  contextBandView,
  contextBarSegments,
  ctxEditActions,
  deriveContextRounds,
  deriveContextRows,
  deriveTopbarAttrs,
  formatContextPercent,
  formatTokenCount,
} from "../src/views/view-model.ts";
import { INITIAL_TASK_STATE } from "../src/runtime/services/tasks.ts";
import type { ContextPreviewDto, ContextPreviewListDto } from "../src/protocol/generated.ts";

function seg(key: string, est: number) {
  return { key, label: key, chars: est, est_tokens: est, reference: false, detail: "" };
}

test("formatContextPercent：~NN%（估算标记）/ 无数据 —", () => {
  assert.equal(formatContextPercent(0.423), "~42%");
  assert.equal(formatContextPercent(0), "~0%");
  assert.equal(formatContextPercent(null), "—");
});

test("deriveTopbarAttrs：ctx 极简 ~NN% 且默认向后兼容（null → —）", () => {
  const a = deriveTopbarAttrs([], INITIAL_TASK_STATE, null, 0.423);
  assert.equal(a.find((x) => x.key === "ctx")?.value, "~42%");
  const b = deriveTopbarAttrs([], INITIAL_TASK_STATE, null);
  assert.equal(b.find((x) => x.key === "ctx")?.value, "—");
  const c = deriveTopbarAttrs([], INITIAL_TASK_STATE, null, null);
  assert.equal(c.find((x) => x.key === "ctx")?.value, "—");
  // 其他属性不受影响
  assert.equal(a.find((x) => x.key === "conc")?.value, "0");
});

test("contextBarSegments：固定段/会话历史/回退/碎片前缀分桶占比；全 0 → 空", () => {
  const parts = contextBarSegments([
    seg("system", 10), seg("skills", 10), seg("history", 60), seg("digest", 20),
  ]);
  assert.deepEqual(parts.map((p) => p.key), ["fixed", "history", "digest"]);
  assert.equal(parts[0]?.est_tokens, 20);
  assert.ok(Math.abs((parts[1]?.percent ?? 0) - 60) < 0.01);
  assert.ok(Math.abs((parts[2]?.percent ?? 0) - 20) < 0.01);
  const sum = parts.reduce((s, p) => s + p.percent, 0);
  assert.ok(Math.abs(sum - 100) < 0.01);
  assert.deepEqual(contextBarSegments([seg("history", 0)]), []);
});

test("deriveContextRounds：轮次行 + 省略/替换/隔离标志（空 → 空）", () => {
  const preview = {
    rounds: [
      { round: 1, summary: "完成1", chars: 10, est_tokens: 12, omitted: false, replaced: false },
      { round: 2, summary: "完成2", chars: 10, est_tokens: 12, omitted: true, replaced: false },
      { round: 3, summary: "完成3", chars: 10, est_tokens: 12, omitted: false, replaced: true },
      { round: 4, summary: "碎片轮", chars: 10, est_tokens: 12, omitted: false, replaced: false, unit_marked: true },
    ],
  } as unknown as ContextPreviewDto;
  const rows = deriveContextRounds(preview);
  assert.deepEqual(rows.map((r) => r.round), [1, 2, 3, 4]);
  assert.deepEqual(rows.map((r) => r.status),
    ["context", "omitted", "replaced", "isolated"]);
  assert.equal(rows[0]?.summary, "完成1");
  assert.deepEqual(deriveContextRounds(null), []);
});

test("deriveContextRows：列表行（不可用 → percent null）", () => {
  const rows = deriveContextRows({
    items: [
      { session: "conversation-1.jsonl", window: 200000, est_tokens: 100, percent: 0.3, available: true },
      { session: "conversation-2.jsonl", window: 0, est_tokens: 0, percent: 0, available: false },
    ],
  } as unknown as ContextPreviewListDto);
  assert.equal(rows.length, 2);
  assert.equal(rows[0]?.percent, 0.3);
  assert.equal(rows[1]?.percent, null);
  assert.deepEqual(deriveContextRows(null), []);
});

test("formatTokenCount：k/M 紧凑格式（不造假）", () => {
  assert.equal(formatTokenCount(512), "512");
  assert.equal(formatTokenCount(5400), "5.4k");
  assert.equal(formatTokenCount(200000), "200k");
  assert.equal(formatTokenCount(2_400_000), "2.4M");
  assert.equal(formatTokenCount(Number.NaN), "—");
});

test("contextBandView：三档映射（golden/managed 有提示；normal 无提示；未知 → null）", () => {
  const g = contextBandView("golden");
  assert.equal(g?.cls, "golden");
  assert.ok((g?.label ?? "").length > 0 && (g?.hint ?? "").length > 0);
  const n = contextBandView("normal");
  assert.equal(n?.hint, "");
  const m = contextBandView("managed");
  assert.ok((m?.hint ?? "").length > 0);
  assert.equal(contextBandView(""), null);
});

test("deriveTopbarAttrs：ctx 档位徽标数据（不破坏既有 ~NN% 格式）", () => {
  const a = deriveTopbarAttrs([], INITIAL_TASK_STATE, null, 0.1, "golden");
  const ctx = a.find((x) => x.key === "ctx");
  assert.equal(ctx?.value, "~10%");
  assert.equal(ctx?.band, "golden");
  const b = deriveTopbarAttrs([], INITIAL_TASK_STATE, null, 0.1);
  assert.equal(b.find((x) => x.key === "ctx")?.band, undefined);
});

test("routeProgress：- [x]/- [ ] 计数（无标记 → null）——批 4", async () => {
  const { routeProgress } = await import("../src/views/view-model.ts");
  assert.deepEqual(routeProgress(["- [x] A", "- [ ] B", "- A", "- [ ] C"]),
    { done: 1, total: 3 });
  assert.equal(routeProgress(["- A", "- B"]), null);
  assert.equal(routeProgress([]), null);
});


test("ctxEditActions：已编辑 → 可恢复；isolated → 无动作（G3）", () => {
  assert.deepEqual(ctxEditActions("context"),
    { omit: true, replace: true, restore: false });
  assert.deepEqual(ctxEditActions("omitted"),
    { omit: true, replace: true, restore: true });
  assert.deepEqual(ctxEditActions("replaced"),
    { omit: true, replace: true, restore: true });
  assert.deepEqual(ctxEditActions("isolated"),
    { omit: false, replace: false, restore: false });
});

test("deriveContextRounds：compacted → 已压缩状态（G7）", () => {
  const preview = {
    rounds: [
      { round: 1, summary: "旧轮", chars: 10, est_tokens: 12, omitted: false, replaced: false, compacted: true },
      { round: 2, summary: "新轮", chars: 10, est_tokens: 12, omitted: false, replaced: false, compacted: false },
    ],
  } as unknown as ContextPreviewDto;
  assert.deepEqual(deriveContextRounds(preview).map((r) => r.status),
    ["compacted", "context"]);
  assert.deepEqual(ctxEditActions("compacted"),
    { omit: false, replace: false, restore: false });
});
