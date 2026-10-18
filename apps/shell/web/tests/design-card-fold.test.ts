/** TDD · Wave-2 T9：设计卡折叠策略解析（记忆 > 默认策略）。
 *
 * 用户裁决 2026-10-01：有待答票据展开 / 只读态收起；开合记忆=会话内内存；
 * 换会话记忆独立。
 */
import { test } from "node:test";
import assert from "node:assert/strict";

import { resolveDesignCardOpen } from "../src/components/design-card.ts";

test("resolveDesignCardOpen：默认策略（有待答展开 / 只读收起）", () => {
  const empty = new Map<string, boolean>();
  assert.equal(resolveDesignCardOpen("s1", true, empty), true, "有待答 → 展开");
  assert.equal(resolveDesignCardOpen("s1", false, empty), false, "只读 → 收起");
});

test("resolveDesignCardOpen：记忆优先（用户手动开合不被默认策略覆盖）", () => {
  const memo = new Map<string, boolean>([["s1", false]]);
  assert.equal(resolveDesignCardOpen("s1", true, memo), false, "用户收过 → 保持收");
  const memo2 = new Map<string, boolean>([["s1", true]]);
  assert.equal(resolveDesignCardOpen("s1", false, memo2), true, "用户开过 → 保持开");
});

test("resolveDesignCardOpen：换会话记忆独立", () => {
  const memo = new Map<string, boolean>([["s1", true], ["s2", false]]);
  assert.equal(resolveDesignCardOpen("s1", false, memo), true);
  assert.equal(resolveDesignCardOpen("s2", true, memo), false);
  assert.equal(resolveDesignCardOpen("s3", true, memo), true, "无记忆 → 默认策略");
});

test("pendingCount：frontier 票据计数（头部徽标）", async () => {
  const { pendingCount } = await import("../src/components/design-card.ts");
  const row = (id: string, frontier: boolean) => ({
    id, statement: id, recommend: "", blockedBy: [] as string[], frontier,
  });
  assert.equal(pendingCount([row("Q-1", true), row("Q-2", false), row("Q-3", true)]), 2);
  assert.equal(pendingCount([]), 0);
});
