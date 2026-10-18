/** E2-UI：装配预设服务层（清单/会话绑定读直连；绑定写走命令总线）。 */
import { test } from "node:test";
import assert from "node:assert/strict";

import { createCommandBus } from "../src/runtime/commands.ts";
import type { WritableRestClient } from "../src/runtime/connection/rest.ts";
import { createPresetsService } from "../src/runtime/services/presets.ts";
import type {
  AssemblyPresetListDto,
  SessionPresetDto,
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

const LIST: AssemblyPresetListDto = {
  presets: [{
    name: "lean", description: "精简装配", builtin: true,
    chain: ["lean", "standard"], hash: "abc123", error: "",
  }],
};

test("presets 服务：list/session GET（session 编码）；setSession PUT body", async () => {
  const calls: Array<{ method: string; path: string; body?: unknown }> = [];
  const svc = createPresetsService({
    rest: fakeRest((method, path, body) => {
      calls.push({ method, path, ...(body === undefined ? {} : { body }) });
      if (method === "PUT") return { session: "a b.jsonl", name: "lean" } satisfies SessionPresetDto;
      if (path.endsWith("/presets")) return LIST;
      return { session: "a b.jsonl", name: "" } satisfies SessionPresetDto;
    }),
    commands: createCommandBus(),
  });
  const list = await svc.list("w1");
  assert.deepEqual(calls[0], { method: "GET", path: "/api/v1/workspaces/w1/presets" });
  assert.equal(list.presets[0]?.chain.length, 2);

  const current = await svc.session("w1", "a b.jsonl");
  assert.deepEqual(calls[1], {
    method: "GET",
    path: "/api/v1/workspaces/w1/session-preset?session=a%20b.jsonl",
  });
  assert.equal(current.name, "");

  const bound = await svc.setSession("w1", "a b.jsonl", "lean");
  assert.deepEqual(calls[2], {
    method: "PUT",
    path: "/api/v1/workspaces/w1/session-preset?session=a%20b.jsonl",
    body: { session: "a b.jsonl", name: "lean" },
  });
  assert.equal(bound.name, "lean");
});

test("presets 服务：setSession 失败经命令总线可见（不静默）", async () => {
  const failures: string[] = [];
  const svc = createPresetsService({
    rest: fakeRest(() => { throw new Error("未知预设"); }),
    commands: createCommandBus((e) => { failures.push(e.name); }),
  });
  await assert.rejects(() => svc.setSession("w1", "s.jsonl", "nope"));
  assert.deepEqual(failures, ["presets.bind"]);
});
