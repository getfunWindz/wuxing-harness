import { test } from "node:test";
import assert from "node:assert/strict";

import { createCommandBus } from "../src/runtime/commands.ts";
import type { WritableRestClient } from "../src/runtime/connection/rest.ts";
import { createSettingsService } from "../src/runtime/services/settings.ts";

type Call = [string, string, unknown?];

function fakeRest(responses: Record<string, unknown>): WritableRestClient & { calls: Call[] } {
  const calls: Call[] = [];
  const pick = (path: string): unknown => responses[path] ?? {};
  return {
    calls,
    async get<T>(path: string): Promise<T> {
      calls.push(["GET", path]);
      return pick(path) as T;
    },
    async post<T>(path: string, body?: unknown): Promise<T> {
      calls.push(["POST", path, body]);
      return pick(path) as T;
    },
    async put<T>(path: string, body?: unknown): Promise<T> {
      calls.push(["PUT", path, body]);
      return pick(path) as T;
    },
    async patch<T>(path: string, body?: unknown): Promise<T> {
      calls.push(["PATCH", path, body]);
      return pick(path) as T;
    },
    async del<T>(path: string): Promise<T> {
      calls.push(["DELETE", path]);
      return pick(path) as T;
    },
  };
}

test("readConfig：GET /api/v1/config（revision 透传）", async () => {
  const rest = fakeRest({
    "/api/v1/config": { values: { sandbox_enabled: true }, sources: {}, revision: "r1" },
  });
  const service = createSettingsService({ rest, commands: createCommandBus() });
  const cfg = await service.readConfig();
  assert.equal(cfg.revision, "r1");
  assert.deepEqual(rest.calls, [["GET", "/api/v1/config"]]);
});

test("writeConfig：user 层 + replace + revision（写回新 revision）", async () => {
  const rest = fakeRest({
    "/api/v1/config?scope=user": { ok: true, scope: "user", path: "p", written: ["providers"], revision: "r2" },
  });
  const service = createSettingsService({ rest, commands: createCommandBus() });
  const out = await service.writeConfig(
    { providers: { a: { type: "openai" } } },
    { replace: ["providers"], revision: "r1" },
  );
  assert.equal(out.revision, "r2");
  const [method, path, body] = rest.calls[0]!;
  assert.equal(method, "PUT");
  assert.equal(path, "/api/v1/config?scope=user");
  assert.deepEqual(body, {
    values: { providers: { a: { type: "openai" } } },
    replace: ["providers"],
    revision: "r1",
  });
});

test("凭据：ref 编码 + 写只读（请求体仅 value）", async () => {
  const rest = fakeRest({
    "/api/v1/credentials/DEMO_PROVIDER_API_KEY": { configured: true, ref: "DEMO_PROVIDER_API_KEY" },
  });
  const service = createSettingsService({ rest, commands: createCommandBus() });
  await service.credentialSet("DEMO_PROVIDER_API_KEY", "sk-x");
  assert.deepEqual(rest.calls[0], ["PUT", "/api/v1/credentials/DEMO_PROVIDER_API_KEY", { value: "sk-x" }]);
  await service.credentialDelete("DEMO_PROVIDER_API_KEY");
  assert.deepEqual(rest.calls[1], ["DELETE", "/api/v1/credentials/DEMO_PROVIDER_API_KEY"]);
});

test("catalog/discover：路径正确 + 一次性凭据透传", async () => {
  const rest = fakeRest({
    "/api/v1/providers/catalog": { providers: [{ id: "deepseek" }] },
    "/api/v1/providers/discover": { models: [{ id: "m1" }] },
  });
  const service = createSettingsService({ rest, commands: createCommandBus() });
  const catalog = await service.catalog();
  assert.equal(catalog.providers.length, 1);
  const out = await service.discover({
    base_url: "https://api.deepseek.com",
    type: "deepseek",
    key: "sk-draft",
  });
  assert.equal(out.models[0]!.id, "m1");
  assert.deepEqual(rest.calls[1], [
    "POST",
    "/api/v1/providers/discover",
    { base_url: "https://api.deepseek.com", type: "deepseek", key: "sk-draft" },
  ]);
});

test("失败不吞：底层错误经命令总线重抛", async () => {
  const rest = fakeRest({});
  rest.put = async () => {
    throw new Error("配置已被外部编辑（HTTP 409）");
  };
  const service = createSettingsService({ rest, commands: createCommandBus() });
  await assert.rejects(() => service.writeConfig({}, { revision: "stale" }), /409/);
});
