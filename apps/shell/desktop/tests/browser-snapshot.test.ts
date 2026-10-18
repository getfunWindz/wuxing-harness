/** TDD · O2-2 P1：AX 树 → 行式快照（纯函数）。 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { simplifyAxTree } = require("../dist/browser-snapshot.js") as
  typeof import("../src/browser-snapshot.ts");

const NODES = [
  { nodeId: "1", role: { value: "RootWebArea" }, name: { value: "Example" } },
  { nodeId: "2", role: { value: "generic" }, name: { value: "" } },
  { nodeId: "3", role: { value: "button" }, name: { value: "提交" }, backendDOMNodeId: 101 },
  { nodeId: "4", role: { value: "textbox" }, name: { value: "Email" }, backendDOMNodeId: 102 },
  { nodeId: "5", role: { value: "StaticText" }, name: { value: "Welcome" } },
  { nodeId: "6", ignored: true, role: { value: "button" }, name: { value: "Hidden" } },
  { nodeId: "7" },
  { nodeId: "8", role: { value: "none" }, name: { value: "X" } },
];

test("simplifyAxTree：过滤（ignored/空 role/none）+ 交互元素 ref + 行格式", () => {
  const r = simplifyAxTree(NODES, { maxLines: 100 });
  assert.deepEqual(r.lines, [
    '- RootWebArea "Example"',
    '- button "提交" [ref=e1]',
    '- textbox "Email" [ref=e2]',
    '- StaticText "Welcome"',
  ]);
  assert.equal(r.truncated, false);
  assert.equal(r.refs.e1?.backendNodeId, 101);
  assert.equal(r.refs.e1?.role, "button");
  assert.equal(r.refs.e2?.nodeId, "4");
});

test("simplifyAxTree：maxLines 截断标记 + 无 ref 的无名交互元素也保留", () => {
  const cut = simplifyAxTree(NODES, { maxLines: 2 });
  assert.equal(cut.lines.length, 2);
  assert.equal(cut.truncated, true);
  const unnamed = simplifyAxTree([
    { nodeId: "9", role: { value: "button" }, name: { value: "" } },
  ]);
  assert.equal(unnamed.lines.length, 1);
  assert.equal(unnamed.lines[0], "- button [ref=e1]");
});

test("simplifyAxTree：超长名字截断（≤80）", () => {
  const long = "x".repeat(200);
  const r = simplifyAxTree([
    { nodeId: "1", role: { value: "StaticText" }, name: { value: long } },
  ]);
  assert.ok(r.lines[0].includes("…"));
  assert.ok(r.lines[0].length < 100);
});

test("P2：ref 单调世代——startRef 续编 + nextRef 游标", () => {
  const first = simplifyAxTree(NODES, { maxLines: 100 });
  assert.equal(first.refs.e1?.backendNodeId, 101);
  assert.equal(first.nextRef, 2);
  const second = simplifyAxTree(NODES, {
    maxLines: 100,
    startRef: first.nextRef,
  });
  assert.equal(second.refs.e3?.backendNodeId, 101, "编号不重置（旧 ref 自然失效）");
  assert.equal(second.refs.e4?.backendNodeId, 102);
  assert.equal(second.nextRef, 4);
  const jump = simplifyAxTree(NODES, { maxLines: 100, startRef: 5 });
  assert.ok(jump.refs.e6, "startRef=5 → 从 e6 起");
});
