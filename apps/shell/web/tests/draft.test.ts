import { test } from "node:test";
import assert from "node:assert/strict";

import { loadDraft, saveDraft } from "../src/views/draft.ts";

function stubStorage(): Map<string, string> {
  const store = new Map<string, string>();
  (globalThis as { localStorage?: unknown }).localStorage = {
    getItem: (k: string): string | null => store.get(k) ?? null,
    setItem: (k: string, v: string): void => { store.set(k, v); },
    removeItem: (k: string): void => { store.delete(k); },
  };
  return store;
}

test("draft：按工作区读写 + 空串删键（隔离）", () => {
  const store = stubStorage();
  saveDraft("w1", "第一稿");
  saveDraft("w2", "第二稿");
  assert.equal(loadDraft("w1"), "第一稿");
  assert.equal(loadDraft("w2"), "第二稿");
  assert.equal(loadDraft("w3"), "");
  saveDraft("w1", "   "); // 全空白 → 视为清空
  assert.equal(loadDraft("w1"), "");
  assert.equal(store.has("wuxing.draft.v1:w1"), false);
});

test("draft：存储不可用时降级不抛", () => {
  (globalThis as { localStorage?: unknown }).localStorage = {
    getItem: (): string | null => { throw new Error("unavailable"); },
    setItem: (): void => { throw new Error("unavailable"); },
    removeItem: (): void => { throw new Error("unavailable"); },
  };
  assert.equal(loadDraft("w1"), "");
  saveDraft("w1", "x"); // 不抛
});
