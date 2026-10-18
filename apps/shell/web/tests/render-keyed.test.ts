import { test } from "node:test";
import assert from "node:assert/strict";

import { applyKeyed, planKeyed } from "../src/render/keyed.ts";

test("planKeyed：插入/移除/目标顺序", () => {
  const plan = planKeyed(["a", "b", "c"], ["b", "d", "a"]);
  assert.deepEqual(plan.order, ["b", "d", "a"]);
  assert.deepEqual(plan.inserts, ["d"]);
  assert.deepEqual(plan.removes, ["c"]);
});

interface FakeNode {
  dataset: Record<string, string>;
  remove(): void;
}

interface FakeHost {
  dataset: Record<string, string>;
  children: FakeNode[];
  appendChild(child: FakeNode): void;
}

function makeFake(keys: string[]) {
  const host: FakeHost = {
    dataset: {},
    children: [],
    appendChild(child) {
      const index = host.children.indexOf(child);
      if (index !== -1) host.children.splice(index, 1);
      host.children.push(child);
    },
  };
  const make = (key: string): FakeNode => {
    const node: FakeNode = {
      dataset: { key },
      remove() {
        const index = host.children.indexOf(node);
        if (index !== -1) host.children.splice(index, 1);
      },
    };
    return node;
  };
  for (const key of keys) host.appendChild(make(key));
  return { host, make };
}

test("applyKeyed：移除 + 复用 + 新增 + 目标顺序（append 即移动）", () => {
  const { host, make } = makeFake(["a", "b"]);
  const created: string[] = [];
  applyKeyed(
    host as unknown as HTMLElement,
    planKeyed(["a", "b"], ["b", "c"]),
    (key) => {
      created.push(key);
      return make(key) as unknown as HTMLElement;
    },
  );
  assert.deepEqual(created, ["c"]);
  assert.deepEqual(host.children.map((node) => node.dataset.key), ["b", "c"]);
});
