/** TDD · O2-2 P1：控制通道协议纯函数（token/解析/URL/封包）。
 *
 * 说明：`desktop/` 作用域为 CommonJS（Electron 主进程约束），Node 不能直接以
 * ESM 加载 src/*.ts——本测试经**编译产物**（dist/*.js，CJS）驱动纯函数；
 * `npm test` 前置 `pretest` 构建 desktop（见 package.json）。
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const {
  checkToken,
  failEnvelope,
  okEnvelope,
  parseRequest,
  validateUrl,
  validateClickArgs,
  validateTypeArgs,
  validateWaitArgs,
  validateEvaluateArgs,
  validateIdentityArgs,
  validateIdentityClearArgs,
  validateCloseArgs,
  DEFAULT_BROWSER_HOST,
  COMMANDS,
  PROTOCOL_VERSION,
} = require("../dist/browser-protocol.js") as typeof import("../src/browser-protocol.ts");

test("默认主机 = 127.0.0.61（专用回环别名，与壳 127.0.0.60 相邻）", () => {
  assert.equal(DEFAULT_BROWSER_HOST, "127.0.0.61");
});

test("checkToken：正确/错误/缺失/长度差异（不抛）", () => {
  const token = "s3cret-token";
  assert.equal(checkToken(`Bearer ${token}`, token), true);
  assert.equal(checkToken("Bearer wrong", token), false);
  assert.equal(checkToken(undefined, token), false);
  assert.equal(checkToken(`Bearer ${token}x`, token), false);
  assert.equal(checkToken(token, token), false); // 缺 Bearer 前缀
  assert.equal(checkToken("bearer " + token, token), true); // 前缀大小写不敏感
});

test("parseRequest：合法请求/坏 JSON/未知命令/args 非对象", () => {
  const good = parseRequest(
    JSON.stringify({ cmd: "open", args: { url: "http://x" } }),
  );
  assert.equal(good.ok, true);
  if (good.ok) {
    assert.equal(good.request.cmd, "open");
    assert.equal(good.request.args.url, "http://x");
  }
  assert.equal(parseRequest("{").ok, false);
  assert.equal(parseRequest("[]").ok, false);
  const unknown = parseRequest(JSON.stringify({ cmd: "eval" }));
  assert.equal(unknown.ok, false);
  if (!unknown.ok) assert.equal(unknown.code, "unknown-command");
  const badArgs = parseRequest(JSON.stringify({ cmd: "open", args: [1] }));
  assert.equal(badArgs.ok, false);
  if (!badArgs.ok) assert.equal(badArgs.code, "bad-args");
});

test("parseRequest：缺省 args = 空对象", () => {
  const r = parseRequest(JSON.stringify({ cmd: "snapshot" }));
  assert.equal(r.ok, true);
  if (r.ok) assert.deepEqual(r.request.args, {});
});

test("validateUrl：http/https 通过；file/javascript/data 拒绝；非法拒绝", () => {
  assert.equal(validateUrl("http://127.0.0.1:8899/").ok, true);
  assert.equal(validateUrl("https://example.com/a").ok, true);
  assert.equal(validateUrl("file:///etc/passwd").ok, false);
  assert.equal(validateUrl("javascript:alert(1)").ok, false);
  assert.equal(validateUrl("data:text/html,x").ok, false);
  const empty = validateUrl("");
  assert.equal(empty.ok, false);
  if (!empty.ok) assert.equal(empty.code, "bad-url");
  const junk = validateUrl("not a url");
  assert.equal(junk.ok, false);
});

test("封包形状（含错误对象）", () => {
  assert.equal(okEnvelope({ a: 1 }), '{"ok":true,"data":{"a":1}}');
  assert.equal(
    failEnvelope("bad", "x"),
    '{"ok":false,"error":{"code":"bad","message":"x"}}',
  );
});

// ---- P2：click/type/wait 命令与参数校验 ----

test("COMMANDS：P2 三命令已入白名单", () => {
  for (const cmd of ["click", "type", "wait"]) {
    assert.ok((COMMANDS as readonly string[]).includes(cmd), cmd);
    assert.equal(parseRequest(JSON.stringify({ cmd })).ok, true);
  }
});

test("validateClickArgs：ref|selector 恰一", () => {
  const okRef = validateClickArgs({ ref: "e1" });
  assert.equal(okRef.ok, true);
  if (okRef.ok) assert.equal(okRef.args.ref, "e1");
  assert.equal(validateClickArgs({ selector: "#a" }).ok, true);
  assert.equal(validateClickArgs({}).ok, false);
  const both = validateClickArgs({ ref: "e1", selector: "#a" });
  assert.equal(both.ok, false);
  if (!both.ok) assert.equal(both.code, "bad-args");
  assert.equal(validateClickArgs({ ref: "  " }).ok, false);
});

test("validateTypeArgs：text 契约 + submit 布尔", () => {
  assert.equal(validateTypeArgs({ ref: "e1", text: "hi" }).ok, true);
  assert.equal(
    validateTypeArgs({ ref: "e1", text: "", submit: true }).ok,
    true,
  );
  assert.equal(validateTypeArgs({ ref: "e1", text: "" }).ok, false);
  assert.equal(validateTypeArgs({ ref: "e1", text: 5 }).ok, false);
  assert.equal(validateTypeArgs({ text: "hi" }).ok, false);
  assert.equal(
    validateTypeArgs({ ref: "e1", text: "hi", submit: "yes" }).ok,
    false,
  );
});

test("validateWaitArgs：selector|text|ms 恰一 + 越界 loud", () => {
  assert.equal(validateWaitArgs({ selector: "#a" }).ok, true);
  assert.equal(validateWaitArgs({ text: "完成" }).ok, true);
  assert.equal(validateWaitArgs({ ms: 100 }).ok, true);
  assert.equal(validateWaitArgs({}).ok, false);
  assert.equal(validateWaitArgs({ selector: "#a", ms: 100 }).ok, false);
  assert.equal(validateWaitArgs({ ms: 0 }).ok, false);
  assert.equal(validateWaitArgs({ ms: 60001 }).ok, false);
  assert.equal(
    validateWaitArgs({ selector: "#a", timeout_ms: 50000 }).ok,
    false,
  );
  assert.equal(
    validateWaitArgs({ selector: "#a", timeout_ms: 3000 }).ok,
    true,
  );
});

// ---- P3：evaluate 显式档（默认关由 Python 双闸控制；协议层从严校验） ----

test("P3：evaluate 命令与 expression 校验", () => {
  assert.ok((COMMANDS as readonly string[]).includes("evaluate"));
  assert.equal(parseRequest(JSON.stringify({ cmd: "evaluate" })).ok, true);
  const ok = validateEvaluateArgs({ expression: "document.title" });
  assert.equal(ok.ok, true);
  if (ok.ok) assert.equal(ok.args.expression, "document.title");
  assert.equal(validateEvaluateArgs({}).ok, false);
  assert.equal(validateEvaluateArgs({ expression: "   " }).ok, false);
  assert.equal(validateEvaluateArgs({ expression: 5 }).ok, false);
  assert.equal(
    validateEvaluateArgs({ expression: "x".repeat(4001) }).ok,
    false,
  );
  assert.equal(
    validateEvaluateArgs({ expression: "x".repeat(4000) }).ok,
    true,
  );
});

test("v4：identity_clear/views 命令 + identity 校验（fail-closed）", () => {
  assert.equal(PROTOCOL_VERSION, "4");
  assert.ok((COMMANDS as readonly string[]).includes("identity_clear"));
  assert.ok((COMMANDS as readonly string[]).includes("views"));
  assert.equal(parseRequest(JSON.stringify({ cmd: "views" })).ok, true);
  const ok = validateIdentityArgs({
    key: "wuxing-browser-abc", mode: "memory", workspace: "C:/p",
  });
  assert.ok(ok.ok);
  if (ok.ok) assert.equal(ok.identity.key, "wuxing-browser-abc");
  for (const bad of [
    undefined,
    {},
    { key: "UPPER", mode: "memory", workspace: "x" },
    { key: "k", mode: "wat", workspace: "x" },
    { key: "k", mode: "memory", workspace: "" },
  ]) {
    assert.ok(!validateIdentityArgs(bad).ok, `应拒绝：${JSON.stringify(bad)}`);
  }
  assert.ok(!validateIdentityClearArgs({ key: "" }).ok);
  assert.ok(validateIdentityClearArgs({ key: "wuxing-browser-abc" }).ok);
});

test("v4：mode 第三值 storage-state + state_path 校验", () => {
  const ok = validateIdentityArgs({
    key: "wuxing-browser-a-11111111-22222222", mode: "storage-state",
    workspace: "C:/p", state_path: "C:/state.json",
  });
  assert.ok(ok.ok);
  if (ok.ok) assert.equal(ok.identity.state_path, "C:/state.json");
  assert.ok(!validateIdentityArgs({
    key: "k-1", mode: "storage-state", workspace: "x",
  }).ok);                                   // 缺 state_path
  assert.ok(!validateIdentityArgs({
    key: "k-1", mode: "storage-state", workspace: "x", state_path: "",
  }).ok);
  assert.ok(!validateIdentityArgs({
    key: "k-1", mode: "storage-state", workspace: "x",
    state_path: "x".repeat(4097),
  }).ok);
  const mem = validateIdentityArgs({
    key: "k-1", mode: "memory", workspace: "x", state_path: "ignored",
  });
  assert.ok(mem.ok);
  if (mem.ok) assert.equal(mem.identity.state_path, undefined);
});

test("v3：close 必带目标身份（复合键字符集合法）", () => {
  assert.ok(!validateCloseArgs({}).ok);
  assert.ok(!validateCloseArgs({ identity: undefined }).ok);
  const ok = validateCloseArgs({
    identity: {
      key: "wuxing-browser-abc12345678901ab-0a1b2c3d",
      mode: "memory",
      workspace: "C:/p",
    },
  });
  assert.ok(ok.ok);
  if (ok.ok) assert.equal(ok.identity.key, "wuxing-browser-abc12345678901ab-0a1b2c3d");
});
