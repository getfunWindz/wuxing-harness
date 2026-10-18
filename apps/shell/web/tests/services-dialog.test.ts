import { test } from "node:test";
import assert from "node:assert/strict";

import { createCommandBus } from "../src/runtime/commands.ts";
import type { WritableRestClient } from "../src/runtime/connection/rest.ts";
import { createDialogService } from "../src/runtime/services/dialog.ts";

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

test("dialog：系统对话框桥（files → 绝对路径列表）", async () => {
  const calls: Array<{ method: string; path: string; body?: unknown }> = [];
  const service = createDialogService({
    rest: fakeRest((method, path, body) => {
      calls.push({ method, path, ...(body === undefined ? {} : { body }) });
      return { paths: ["/abs/a.md", "/abs/b.md"] };
    }),
    commands: createCommandBus(),
  });
  const out = await service.pickFiles();
  assert.deepEqual(calls, [{
    method: "POST", path: "/api/v1/dialog/pick", body: { kind: "files" },
  }]);
  assert.deepEqual(out.paths, ["/abs/a.md", "/abs/b.md"]);
});

test("dialog：失败经命令总线可见（不静默）", async () => {
  const failures: string[] = [];
  const service = createDialogService({
    rest: fakeRest(() => { throw new Error("对话框不可用"); }),
    commands: createCommandBus((e) => { failures.push(e.name); }),
  });
  await assert.rejects(() => service.pickFiles());
  assert.deepEqual(failures, ["dialog.pick"]);
});
