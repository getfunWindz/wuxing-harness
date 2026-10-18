import { test } from "node:test";
import assert from "node:assert/strict";

import { loadSessionRail } from "../src/views/session-rail.ts";

const S = (name: string, title = "") => ({
  name,
  path: "",
  size: 2048,
  mtime: 0,
  title,
  branched_from: null,
});

function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => { resolve = r; });
  return { promise, resolve };
}

test("loadSessionRail：列表立即就位，LLM 标题后台补齐（不阻塞）", async () => {
  const gate = deferred<void>();
  const titleCalls: string[] = [];
  const applied: { readonly name: string; readonly title: string }[][] = [];
  const updates: [string, string][] = [];
  await loadSessionRail({
    list: async () => [S("conversation-1.jsonl"), S("conversation-2.jsonl")],
    title: async (name) => {
      titleCalls.push(name);
      await gate.promise;
      return "标题";
    },
    apply: (rows) => {
      applied.push(rows.map((r) => ({ name: r.name, title: r.title })));
    },
    onTitle: (name, title) => { updates.push([name, title]); },
    isStale: () => false,
  });
  // 标题未完成也必须已返回（列表先上屏）——回归：旧实现串行等标题才更新
  assert.equal(applied.length, 1);
  assert.deepEqual(applied[0]!.map((r) => r.name),
                   ["conversation-1.jsonl", "conversation-2.jsonl"]);
  // 有界并发（默认 2）：返回时前两条均已发起（限流而非串行）
  assert.deepEqual(titleCalls,
                   ["conversation-1.jsonl", "conversation-2.jsonl"]);
  assert.equal(updates.length, 0, "标题未完成不得回调");
  gate.resolve();
  await new Promise((r) => setTimeout(r, 10));
  assert.deepEqual(titleCalls,
                   ["conversation-1.jsonl", "conversation-2.jsonl"]);
  assert.deepEqual(updates, [
    ["conversation-1.jsonl", "标题"],
    ["conversation-2.jsonl", "标题"],
  ]);
});

test("loadSessionRail：标题补齐并发有界（峰值 ≤2，不串行不洪泛）", async () => {
  let active = 0;
  let peak = 0;
  const gates: ReturnType<typeof deferred<void>>[] = [];
  const names = ["a.jsonl", "b.jsonl", "c.jsonl", "d.jsonl", "e.jsonl"];
  await loadSessionRail({
    list: async () => names.map((n) => S(n)),
    title: async () => {
      active += 1;
      peak = Math.max(peak, active);
      const g = deferred<void>();
      gates.push(g);
      await g.promise;
      active -= 1;
      return "t";
    },
    apply: () => {},
    onTitle: () => {},
    isStale: () => false,
  });
  assert.equal(gates.length, 2, "首批并发=2（既非串行 1、也非全量 5）");
  while (gates.length > 0) {
    gates.shift()!.resolve();
    await new Promise((r) => setTimeout(r, 5));
  }
  await new Promise((r) => setTimeout(r, 20));
  assert.equal(peak, 2, `并发峰值应为 2（实际 ${peak}）`);
});

test("loadSessionRail：titleConcurrency 可显式收紧为串行", async () => {
  const gates: ReturnType<typeof deferred<void>>[] = [];
  await loadSessionRail({
    list: async () => [S("a.jsonl"), S("b.jsonl")],
    title: async () => { const g = deferred<void>(); gates.push(g); await g.promise; return "t"; },
    apply: () => {},
    onTitle: () => {},
    isStale: () => false,
    titleConcurrency: 1,
  });
  assert.equal(gates.length, 1, "并发=1 时仅首条发起");
  gates.shift()!.resolve();
  await new Promise((r) => setTimeout(r, 10));
  assert.equal(gates.length, 1, "首条完成后才发起第二条");
  gates.shift()!.resolve();
});

test("loadSessionRail：已有标题不重复请求、空标题才后台补", async () => {
  const titleCalls: string[] = [];
  await loadSessionRail({
    list: async () => [S("a.jsonl", "既有标题"), S("b.jsonl")],
    title: async (name) => { titleCalls.push(name); return "新标题"; },
    apply: () => {},
    onTitle: () => {},
    isStale: () => false,
  });
  await new Promise((r) => setTimeout(r, 10));
  assert.deepEqual(titleCalls, ["b.jsonl"]);
});

test("loadSessionRail：切走后（陈旧）标题回填丢弃", async () => {
  let stale = false;
  const updates: [string, string][] = [];
  await loadSessionRail({
    list: async () => [S("a.jsonl")],
    title: async () => "t",
    apply: () => { stale = true; }, // 列表中工作区已切走
    onTitle: (name, title) => { updates.push([name, title]); },
    isStale: () => stale,
  });
  await new Promise((r) => setTimeout(r, 10));
  assert.equal(updates.length, 0, "陈旧回填必须丢弃");
});

test("loadSessionRail：单条标题失败不阻断后续", async () => {
  const updates: [string, string][] = [];
  await loadSessionRail({
    list: async () => [S("a.jsonl"), S("b.jsonl")],
    title: async (name) => {
      if (name === "a.jsonl") throw new Error("boom");
      return "ok";
    },
    apply: () => {},
    onTitle: (name, title) => { updates.push([name, title]); },
    isStale: () => false,
  });
  await new Promise((r) => setTimeout(r, 10));
  assert.deepEqual(updates, [["b.jsonl", "ok"]]);
});

test("loadSessionRail：apply 携带列表发起时刻（T3 陈旧快照判据）", async () => {
  // Wave-2 T3：列表请求发起时刻须随 apply 传出——调用方以
  // 「发起时刻 vs 选择时刻」判定陈旧快照（陈旧快照不得反清 activeSession）。
  const calls: Array<{ startedAt: number }> = [];
  const t0 = Date.now();
  await loadSessionRail({
    list: async () => [S("a.jsonl")],
    title: async () => "",
    apply: (_rows, startedAt) => { calls.push({ startedAt }); },
    onTitle: () => { /* 无标题 */ },
    isStale: () => false,
  });
  assert.equal(calls.length, 1);
  assert.ok(calls[0]!.startedAt >= t0 && calls[0]!.startedAt <= Date.now(),
    `startedAt 必须在 [${t0}, now] 间：${calls[0]!.startedAt}`);
});
