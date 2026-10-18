import { test } from "node:test";
import assert from "node:assert/strict";

import { loadSessionChat } from "../src/views/session-load.ts";

type Ref = { wsId: string | null; name: string | null };

/** 可切换的当前会话引用（模拟 openSession 改状态）。 */
function switcher(init: Ref): { ref: Ref; current(): Ref } {
  const ref = { ...init };
  return { ref, current: () => ({ ...ref }) };
}

function deferred<T>(): { promise: Promise<T>; resolve: (v: T) => void } {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((res) => { resolve = res; });
  return { promise, resolve };
}

test("loadSessionChat：正常路径 onApply（rows + rounds）", async () => {
  const s = switcher({ wsId: "w1", name: "A" });
  const applied: unknown[] = [];
  await loadSessionChat({
    current: s.current,
    fetchMessages: async () => ({ rows: [{ round: 1 }] }),
    fetchRounds: async () => ({ rounds: [{ round: 1 }] }) as never,
    onApply: (rows, rounds) => applied.push([rows, rounds]),
    onClear: () => applied.push("clear"),
  });
  assert.equal(applied.length, 1);
  const [rows, rounds] = applied[0] as [unknown[], unknown];
  assert.equal((rows as unknown[]).length, 1);
  assert.notEqual(rounds, null);
});

test("loadSessionChat：切换即 onStart（先清后填，杜绝旧会话内容残留）", async () => {
  const calls: string[] = [];
  await loadSessionChat({
    current: () => ({ wsId: "w1", name: "b" }),
    fetchMessages: async () => {
      calls.push("fetch");
      return { rows: [{ round: 1, user_text: "B" }] };
    },
    fetchRounds: async () => ({ rounds: [] } as never),
    onStart: () => { calls.push("start"); },          // ← 新钩子（Wave-2 T2）
    onApply: () => { calls.push("apply"); },
    onClear: () => { calls.push("clear"); },
  });
  assert.deepEqual(calls, ["start", "fetch", "apply"]);
});

test("loadSessionChat：messages 返回前切走 → 丢弃（防旧会话/空会话覆盖当前视图）", async () => {
  const s = switcher({ wsId: "w1", name: "A" });
  const applied: unknown[] = [];
  const d = deferred<{ rows: Record<string, unknown>[] }>();
  const p = loadSessionChat({
    current: s.current,
    fetchMessages: () => d.promise,
    fetchRounds: async () => ({ rounds: [] }) as never,
    onApply: (...args) => applied.push(args),
    onClear: () => applied.push("clear"),
  });
  s.ref.name = "B"; // 用户在等待期间切换会话
  d.resolve({ rows: [{ round: 9 }] }); // 旧会话响应迟到
  await p;
  assert.deepEqual(applied, [], "陈旧响应不得回填");
});

test("loadSessionChat：rounds 返回前切走 → 丢弃（二次校验）", async () => {
  const s = switcher({ wsId: "w1", name: "A" });
  const applied: unknown[] = [];
  const d = deferred<never>();
  const p = loadSessionChat({
    current: s.current,
    fetchMessages: async () => ({ rows: [{ round: 1 }] }),
    fetchRounds: () => d.promise,
    onApply: (...args) => applied.push(args),
    onClear: () => applied.push("clear"),
  });
  await Promise.resolve(); // 让 messages 先完成
  await Promise.resolve();
  s.ref.name = "B";
  d.resolve(undefined as never);
  await p;
  assert.deepEqual(applied, [], "rounds 迟到 + 已切走 → 不得回填");
});

test("loadSessionChat：空会话 → onClear 且不请求", async () => {
  let fetched = 0;
  const applied: unknown[] = [];
  await loadSessionChat({
    current: () => ({ wsId: "w1", name: null }),
    fetchMessages: async () => { fetched += 1; return { rows: [] }; },
    fetchRounds: async () => ({ rounds: [] }) as never,
    onApply: (...args) => applied.push(args),
    onClear: () => applied.push("clear"),
  });
  assert.deepEqual(applied, ["clear"]);
  assert.equal(fetched, 0, "无会话不得发请求");
});

test("loadSessionChat：读取失败保留旧数据（不回填、不清空）", async () => {
  const s = switcher({ wsId: "w1", name: "A" });
  const applied: unknown[] = [];
  await loadSessionChat({
    current: s.current,
    fetchMessages: async () => { throw new Error("boom"); },
    fetchRounds: async () => ({ rounds: [] }) as never,
    onApply: (...args) => applied.push(args),
    onClear: () => applied.push("clear"),
  });
  assert.deepEqual(applied, [], "失败必须保留旧数据");
});

test("loadSessionChat：会话不变期间正常刷新（rounds 失败不阻塞展示）", async () => {
  const s = switcher({ wsId: "w1", name: "A" });
  const applied: unknown[][] = [];
  await loadSessionChat({
    current: s.current,
    fetchMessages: async () => ({ rows: [{ round: 2 }] }),
    fetchRounds: async () => { throw new Error("rounds down"); },
    onApply: (rows, rounds) => applied.push([rows, rounds]),
    onClear: () => applied.push(["clear"]),
  });
  assert.equal(applied.length, 1);
  assert.equal(applied[0]?.[1], null, "rounds 失败 → null 不阻塞");
});
