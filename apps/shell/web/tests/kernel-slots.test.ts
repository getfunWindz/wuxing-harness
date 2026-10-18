import { test } from "node:test";
import assert from "node:assert/strict";

import { SlotRegistry } from "../src/runtime/kernel/slots.ts";

const host = {} as HTMLElement;

test("注册/重复拒绝/撤销", () => {
  const slots = new SlotRegistry();
  const dispose = slots.register("task.card", { id: "a", render: () => {} });
  assert.deepEqual(slots.entryIds("task.card"), ["a"]);
  assert.throws(
    () => slots.register("task.card", { id: "a", render: () => {} }),
    /重复/,
  );
  dispose();
  assert.deepEqual(slots.entryIds("task.card"), []);
});

test("未声明渲染失败；声明后可渲染，撤销声明后再次失败", () => {
  const slots = new SlotRegistry();
  slots.register("hero.after", { id: "a", render: () => {} });
  assert.throws(() => slots.render("hero.after", "composer", host, {}), /未声明/);
  const undeclare = slots.declare("hero.after", "composer");
  slots.render("hero.after", "composer", host, {});
  undeclare();
  assert.throws(() => slots.render("hero.after", "composer", host, {}), /未声明/);
});

test("重复声明失败 + 渲染逆序释放", () => {
  const slots = new SlotRegistry();
  slots.declare("s", "o");
  assert.throws(() => slots.declare("s", "o"), /重复声明/);
  const log: string[] = [];
  slots.register("s", { id: "1", render: () => () => { log.push("1"); } });
  slots.register("s", { id: "2", render: () => () => { log.push("2"); } });
  const dispose = slots.render("s", "o", host, {});
  dispose();
  assert.deepEqual(log, ["2", "1"]);
});
