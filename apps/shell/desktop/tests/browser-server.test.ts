/** TDD · O2-2 P1：控制通道 HTTP 主机（真 127.0.0.1 + 假驱动）。
 *
 * 同 browser-protocol.test.ts：经编译产物（dist/*.js，CJS）驱动——desktop 作用域
 * 为 CommonJS（Electron 主进程约束）；`npm test` 前置 `pretest` 构建。
 * v2（§11.5-①）：页面命令必带 identity；identity_clear 分发。
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

import type { BrowserDriver } from "../src/browser-server.ts";
import type { BrowserIdentity } from "../src/browser-protocol.ts";

const require = createRequire(import.meta.url);
const { startBrowserServer } =
  require("../dist/browser-server.js") as typeof import("../src/browser-server.ts");

const IDENTITY: BrowserIdentity = {
  key: "wuxing-browser-test",
  mode: "memory",
  workspace: "C:/p",
};

class FakeDriver implements BrowserDriver {
  public calls: Array<{ cmd: string; value?: unknown }> = [];
  public lastOpenIdentity: BrowserIdentity | null = null;
  status(): Promise<Record<string, unknown>> | Record<string, unknown> {
    return { app: "fake", commands: ["status", "open"] };
  }
  open(
    url: string,
    identity: BrowserIdentity,
  ): Promise<Record<string, unknown>> | Record<string, unknown> {
    this.calls.push({ cmd: "open", value: url });
    this.lastOpenIdentity = identity;
    return { title: "T", url };
  }
  snapshot(
    identity: BrowserIdentity,
  ): Promise<Record<string, unknown>> | Record<string, unknown> {
    void identity;
    return { snapshot: '- generic "x" [ref=e1]' };
  }
  screenshot(
    args: Record<string, unknown>,
    identity: BrowserIdentity,
  ): Promise<Record<string, unknown>> | Record<string, unknown> {
    void identity;
    this.calls.push({ cmd: "screenshot", value: args.path });
    return { path: "/tmp/x.png" };
  }
  close(
    identity: BrowserIdentity,
  ): Promise<Record<string, unknown>> | Record<string, unknown> {
    this.calls.push({ cmd: "close", value: identity });
    return { closed: true, active: null };
  }
  views(): Promise<Record<string, unknown>> | Record<string, unknown> {
    this.calls.push({ cmd: "views" });
    return { views: [], active: null };
  }
  click(
    args: Record<string, unknown>,
    identity: BrowserIdentity,
  ): Promise<Record<string, unknown>> | Record<string, unknown> {
    void identity;
    this.calls.push({ cmd: "click", value: args });
    return { clicked: true };
  }
  type(
    args: Record<string, unknown>,
    identity: BrowserIdentity,
  ): Promise<Record<string, unknown>> | Record<string, unknown> {
    void identity;
    this.calls.push({ cmd: "type", value: args });
    return { typed: true };
  }
  wait(
    args: Record<string, unknown>,
    identity: BrowserIdentity,
  ): Promise<Record<string, unknown>> | Record<string, unknown> {
    void identity;
    this.calls.push({ cmd: "wait", value: args });
    return { found: true };
  }
  evaluate(
    args: Record<string, unknown>,
    identity: BrowserIdentity,
  ): Promise<Record<string, unknown>> | Record<string, unknown> {
    void identity;
    this.calls.push({ cmd: "evaluate", value: args });
    return { value: "ok", exception: null };
  }
  identityClear(
    key: string,
  ): Promise<Record<string, unknown>> | Record<string, unknown> {
    this.calls.push({ cmd: "identity_clear", value: key });
    return { cleared: true, key };
  }
}

async function post(
  endpoint: string,
  body: unknown,
  token?: string,
): Promise<{ status: number; json: any }> {
  const headers: Record<string, string> = {
    "content-type": "application/json",
  };
  if (token !== undefined) headers.authorization = `Bearer ${token}`;
  const res = await fetch(`${endpoint}/cmd`, {
    method: "POST",
    headers,
    body: typeof body === "string" ? body : JSON.stringify(body),
  });
  return { status: res.status, json: await res.json() };
}

test("通路：token / status / open / 未知命令 / 非 POST 路径", async () => {
  const driver = new FakeDriver();
  const server = await startBrowserServer({
    token: "tok", driver, host: "127.0.0.1", requestTimeoutMs: 2000,
  });
  try {
    const unauth = await post(server.endpoint, { cmd: "status" });
    assert.equal(unauth.status, 401);
    assert.equal(unauth.json.error.code, "unauthorized");

    const status = await post(server.endpoint, { cmd: "status" }, "tok");
    assert.equal(status.status, 200);
    assert.equal(status.json.ok, true);
    assert.equal(status.json.data.protocol, "4");
    assert.equal(status.json.data.app, "fake");

    const open = await post(
      server.endpoint,
      { cmd: "open", args: { url: "http://127.0.0.1:9/", identity: IDENTITY } },
      "tok",
    );
    assert.equal(open.status, 200);
    assert.deepEqual(driver.calls, [{
      cmd: "open", value: "http://127.0.0.1:9/",
    }]);
    assert.deepEqual(driver.lastOpenIdentity, IDENTITY);

    const unknown = await post(server.endpoint, { cmd: "eval" }, "tok");
    assert.equal(unknown.status, 400);
    assert.equal(unknown.json.error.code, "unknown-command");

    const wrongPath = await fetch(server.endpoint, {
      method: "POST", headers: { authorization: "Bearer tok" }, body: "{}",
    });
    assert.equal(wrongPath.status, 404);
  } finally {
    await server.close();
  }
});

test("v2 身份：页面命令缺 identity → 400 fail-closed；identity_clear 分发", async () => {
  const driver = new FakeDriver();
  const server = await startBrowserServer({
    token: "tok", driver, host: "127.0.0.1", requestTimeoutMs: 2000,
  });
  try {
    for (const cmd of ["open", "snapshot", "screenshot"]) {
      const res = await post(server.endpoint,
        { cmd, args: { url: "http://x/" } }, "tok");
      assert.equal(res.status, 400, `${cmd} 缺身份必须拒绝`);
      assert.equal(res.json.error.code, "bad-identity");
    }
    const clear = await post(
      server.endpoint,
      { cmd: "identity_clear", args: { key: "wuxing-browser-abc" } },
      "tok",
    );
    assert.equal(clear.status, 200);
    assert.deepEqual(driver.calls[driver.calls.length - 1], {
      cmd: "identity_clear", value: "wuxing-browser-abc",
    });
    const badClear = await post(
      server.endpoint, { cmd: "identity_clear", args: { key: "BAD KEY" } }, "tok",
    );
    assert.equal(badClear.status, 400);
    assert.equal(badClear.json.error.code, "bad-identity");
  } finally {
    await server.close();
  }
});

test("安全：坏 scheme 拒绝；请求体超限拒绝", async () => {
  const server = await startBrowserServer({
    token: "tok", driver: new FakeDriver(), host: "127.0.0.1", requestTimeoutMs: 2000,
  });
  try {
    const badScheme = await post(
      server.endpoint,
      { cmd: "open", args: { url: "file:///x", identity: IDENTITY } },
      "tok",
    );
    assert.equal(badScheme.status, 400);
    assert.equal(badScheme.json.error.code, "bad-scheme");

    const big = await post(
      server.endpoint,
      { cmd: "open", args: { url: "http://x/", pad: "a".repeat(70_000) } },
      "tok",
    );
    assert.equal(big.status, 413);
    assert.equal(big.json.error.code, "body-too-large");
  } finally {
    await server.close();
  }
});

test("驱动异常/超时 → 500 结构化错误（不泄栈）", async () => {
  const driver = new FakeDriver();
  driver.open = (): never => {
    throw new Error("view crashed");
  };
  const server = await startBrowserServer({
    token: "tok", driver, host: "127.0.0.1", requestTimeoutMs: 2000,
  });
  try {
    const res = await post(
      server.endpoint,
      { cmd: "open", args: { url: "http://x/", identity: IDENTITY } },
      "tok",
    );
    assert.equal(res.status, 500);
    assert.equal(res.json.ok, false);
    assert.equal(res.json.error.code, "command-failed");
    assert.ok(!String(res.json.error.message).includes("at "));
  } finally {
    await server.close();
  }

  const hanging = new FakeDriver();
  hanging.snapshot = (): Promise<Record<string, unknown>> =>
    new Promise<Record<string, unknown>>(() => undefined);
  const server2 = await startBrowserServer({
    token: "tok", driver: hanging, host: "127.0.0.1", requestTimeoutMs: 150,
  });
  try {
    const res = await post(
      server2.endpoint, { cmd: "snapshot", args: { identity: IDENTITY } }, "tok",
    );
    assert.equal(res.status, 500);
    assert.equal(res.json.error.code, "command-failed");
    assert.ok(String(res.json.error.message).includes("超时"));
  } finally {
    await server2.close();
  }
});

test("P2 分发：click/type/wait → 驱动；非法参数 400", async () => {
  const driver = new FakeDriver();
  const server = await startBrowserServer({
    token: "tok", driver, host: "127.0.0.1", requestTimeoutMs: 2000,
  });
  try {
    const click = await post(
      server.endpoint,
      { cmd: "click", args: { ref: "e2", identity: IDENTITY } },
      "tok",
    );
    assert.equal(click.status, 200);
    assert.deepEqual(driver.calls[driver.calls.length - 1], {
      cmd: "click", value: { ref: "e2" },
    });
    const typed = await post(
      server.endpoint,
      { cmd: "type", args: { ref: "e2", text: "中文", submit: true, identity: IDENTITY } },
      "tok",
    );
    assert.equal(typed.status, 200);
    assert.deepEqual(driver.calls[driver.calls.length - 1], {
      cmd: "type", value: { ref: "e2", text: "中文", submit: true },
    });
    const wait = await post(
      server.endpoint,
      { cmd: "wait", args: { selector: "#done", identity: IDENTITY } },
      "tok",
    );
    assert.equal(wait.status, 200);
    assert.deepEqual(driver.calls[driver.calls.length - 1], {
      cmd: "wait", value: { selector: "#done" },
    });
    const badClick = await post(
      server.endpoint, { cmd: "click", args: { identity: IDENTITY } }, "tok",
    );
    assert.equal(badClick.status, 400);
    assert.equal(badClick.json.error.code, "bad-args");
    const badWait = await post(
      server.endpoint,
      { cmd: "wait", args: { selector: "#a", ms: 5, identity: IDENTITY } },
      "tok",
    );
    assert.equal(badWait.status, 400);
  } finally {
    await server.close();
  }
});

test("P3 分发：evaluate → 驱动；非法参数 400", async () => {
  const driver = new FakeDriver();
  const server = await startBrowserServer({
    token: "tok", driver, host: "127.0.0.1", requestTimeoutMs: 2000,
  });
  try {
    const ok = await post(
      server.endpoint,
      { cmd: "evaluate", args: { expression: "document.title", identity: IDENTITY } },
      "tok",
    );
    assert.equal(ok.status, 200);
    assert.deepEqual(driver.calls[driver.calls.length - 1], {
      cmd: "evaluate", value: { expression: "document.title" },
    });
    const bad = await post(
      server.endpoint, { cmd: "evaluate", args: { identity: IDENTITY } }, "tok",
    );
    assert.equal(bad.status, 400);
    assert.equal(bad.json.error.code, "bad-args");
  } finally {
    await server.close();
  }
});

test("P3 串行化：并发命令按到达序执行（无交叠）+ 失败不阻断", async () => {
  const driver = new FakeDriver();
  const events: string[] = [];
  let active = 0;
  let maxActive = 0;
  driver.snapshot = async (): Promise<Record<string, unknown>> => {
    active += 1;
    maxActive = Math.max(maxActive, active);
    events.push("start");
    await new Promise((resolve) => setTimeout(resolve, 60));
    events.push("end");
    active -= 1;
    return { snapshot: "x" };
  };
  driver.open = async (url: string): Promise<Record<string, unknown>> => {
    events.push("open-start");
    await new Promise((resolve) => setTimeout(resolve, 20));
    events.push("open-end");
    return { url };
  };
  const server = await startBrowserServer({
    token: "tok", driver, host: "127.0.0.1", requestTimeoutMs: 3000,
  });
  try {
    const p1 = post(server.endpoint,
      { cmd: "snapshot", args: { identity: IDENTITY } }, "tok");
    await new Promise((resolve) => setTimeout(resolve, 10));
    const p2 = post(
      server.endpoint,
      { cmd: "open", args: { url: "http://x/", identity: IDENTITY } },
      "tok",
    );
    const [r1, r2] = await Promise.all([p1, p2]);
    assert.equal(r1.status, 200);
    assert.equal(r2.status, 200);
    assert.equal(maxActive, 1, "命令执行不得交叠");
    assert.deepEqual(events, ["start", "end", "open-start", "open-end"]);

    driver.close = (): never => {
      throw new Error("close boom");
    };
    const bad = await post(
      server.endpoint, { cmd: "close", args: { identity: IDENTITY } }, "tok",
    );
    assert.equal(bad.status, 500);
    const after = await post(server.endpoint,
      { cmd: "snapshot", args: { identity: IDENTITY } }, "tok");
    assert.equal(after.status, 200, "单体失败不得阻断后续命令");
  } finally {
    await server.close();
  }
});

test("v3 分片：同键串行、异键并行（Q3=A）", async () => {
  const driver = new FakeDriver();
  let active = 0;
  let maxActive = 0;
  driver.snapshot = async (): Promise<Record<string, unknown>> => {
    active += 1;
    maxActive = Math.max(maxActive, active);
    await new Promise((resolve) => setTimeout(resolve, 80));
    active -= 1;
    return { snapshot: "x" };
  };
  const server = await startBrowserServer({
    token: "tok", driver, host: "127.0.0.1", requestTimeoutMs: 3000,
  });
  const A: BrowserIdentity = {
    key: "wuxing-browser-a-11111111", mode: "memory", workspace: "C:/a",
  };
  const B: BrowserIdentity = {
    key: "wuxing-browser-b-22222222", mode: "memory", workspace: "C:/b",
  };
  try {
    await Promise.all([
      post(server.endpoint, { cmd: "snapshot", args: { identity: A } }, "tok"),
      post(server.endpoint, { cmd: "snapshot", args: { identity: B } }, "tok"),
    ]);
    assert.equal(maxActive, 2, "异键应并行");
    maxActive = 0;
    await Promise.all([
      post(server.endpoint, { cmd: "snapshot", args: { identity: A } }, "tok"),
      post(server.endpoint, { cmd: "snapshot", args: { identity: A } }, "tok"),
    ]);
    assert.equal(maxActive, 1, "同键应串行");
  } finally {
    await server.close();
  }
});

test("v3：views 查询分发；close 缺目标 400", async () => {
  const driver = new FakeDriver();
  const server = await startBrowserServer({
    token: "tok", driver, host: "127.0.0.1", requestTimeoutMs: 2000,
  });
  try {
    const views = await post(server.endpoint, { cmd: "views" }, "tok");
    assert.equal(views.status, 200);
    assert.deepEqual(views.json.data, { views: [], active: null });
    assert.deepEqual(driver.calls[driver.calls.length - 1], { cmd: "views" });
    const missing = await post(server.endpoint, { cmd: "close", args: {} }, "tok");
    assert.equal(missing.status, 400);
    assert.equal(missing.json.error.code, "bad-identity");
    const okClose = await post(
      server.endpoint, { cmd: "close", args: { identity: IDENTITY } }, "tok",
    );
    assert.equal(okClose.status, 200);
    assert.deepEqual(driver.calls[driver.calls.length - 1], {
      cmd: "close", value: IDENTITY,
    });
  } finally {
    await server.close();
  }
});
