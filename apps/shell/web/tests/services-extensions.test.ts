/** E2-UI：扩展命令服务层（读直连 / 写走命令总线；路径与体断言）。 */
import { test } from "node:test";
import assert from "node:assert/strict";

import { createCommandBus } from "../src/runtime/commands.ts";
import type { WritableRestClient } from "../src/runtime/connection/rest.ts";
import { createExtensionsService } from "../src/runtime/services/extensions.ts";
import type {
  ExtCommandListDto,
  ExtCommandRunDto,
} from "../src/protocol/generated.ts";

function fakeRest(
  handler: (method: string, path: string, body?: unknown) => unknown,
): WritableRestClient {
  return {
    async get<T>(path: string): Promise<T> { return handler("GET", path) as T; },
    async post<T>(path: string, body?: unknown): Promise<T> { return handler("POST", path, body) as T; },
    async put<T>(path: string, body?: unknown): Promise<T> { return handler("PUT", path, body) as T; },
    async patch<T>(path: string, body?: unknown): Promise<T> { return handler("PATCH", path, body) as T; },
    async del<T>(path: string): Promise<T> { return handler("DELETE", path) as T; },
  };
}

const LIST: ExtCommandListDto = {
  commands: [{
    name: "greet", description: "问候", source: "ext-a",
    args: [{ name: "who", label: "对象", type: "str", required: true, default: null }],
  }],
};
const RUN: ExtCommandRunDto = { status: "ok", text: "你好，壳", error: "" };

test("extensions 服务：list 直连 GET；run POST 路径与体", async () => {
  const calls: Array<{ method: string; path: string; body?: unknown }> = [];
  const svc = createExtensionsService({
    rest: fakeRest((method, path, body) => {
      calls.push({ method, path, ...(body === undefined ? {} : { body }) });
      return method === "GET" ? LIST : RUN;
    }),
    commands: createCommandBus(),
  });
  const list = await svc.list("w1");
  assert.deepEqual(calls[0], {
    method: "GET", path: "/api/v1/workspaces/w1/extensions/commands",
  });
  assert.equal(list.commands[0]?.name, "greet");
  assert.equal(list.commands[0]?.args[0]?.required, true);

  const run = await svc.run("w1", "greet", { who: "壳" });
  assert.deepEqual(calls[1], {
    method: "POST",
    path: "/api/v1/workspaces/w1/extensions/commands/greet",
    body: { args: { who: "壳" } },
  });
  assert.equal(run.status, "ok");
});

test("extensions 服务：run 失败经命令总线可见（不静默）", async () => {
  const failures: string[] = [];
  const svc = createExtensionsService({
    rest: fakeRest(() => { throw new Error("引擎未就绪"); }),
    commands: createCommandBus((e) => { failures.push(e.name); }),
  });
  await assert.rejects(() => svc.run("w1", "greet", {}));
  assert.deepEqual(failures, ["extensions.run"]);
});
