/** 双模式批 1（Task 6）：模式服务层 + id 映射 + 设置分区模型（纯函数可单测）。 */
import { test } from "node:test";
import assert from "node:assert/strict";

import { createCommandBus } from "../src/runtime/commands.ts";
import type { WritableRestClient } from "../src/runtime/connection/rest.ts";
import {
  createModesService,
  joinModeId,
  splitModeId,
} from "../src/runtime/services/modes.ts";
import type { SessionModeDto } from "../src/protocol/generated.ts";

const DTO: SessionModeDto = {
  mode: "minimal",
  variant: "standard",
  source: "default",
  editable: true,
  picker_enabled: true,
  default_mode: "minimal-standard",
};

function fakeRest(handler: (method: string, path: string, body?: unknown) => unknown) {
  const calls: { method: string; path: string; body?: unknown }[] = [];
  const rest: WritableRestClient = {
    async get<T>(path: string): Promise<T> {
      calls.push({ method: "GET", path });
      return handler("GET", path) as T;
    },
    async post<T>(path: string, body?: unknown): Promise<T> {
      calls.push({ method: "POST", path, body });
      return handler("POST", path, body) as T;
    },
    async put<T>(path: string, body?: unknown): Promise<T> {
      calls.push({ method: "PUT", path, body });
      return handler("PUT", path, body) as T;
    },
    async patch<T>(path: string, body?: unknown): Promise<T> {
      calls.push({ method: "PATCH", path, body });
      return handler("PATCH", path, body) as T;
    },
    async del<T>(path: string): Promise<T> {
      calls.push({ method: "DELETE", path });
      return handler("DELETE", path) as T;
    },
  };
  return { rest, calls };
}

test("模式 id 映射：split/join（theroad 无变体；旧值 wayfinder 兼容读）", () => {
  assert.deepEqual(splitModeId("minimal-pure"), { mode: "minimal", variant: "pure" });
  assert.deepEqual(splitModeId("minimal-standard"), { mode: "minimal", variant: "standard" });
  assert.deepEqual(splitModeId("theroad"), { mode: "theroad", variant: "" });
  assert.deepEqual(splitModeId("wayfinder"), { mode: "theroad", variant: "" });
  assert.equal(joinModeId("minimal", "pure"), "minimal-pure");
  assert.equal(joinModeId("minimal", "standard"), "minimal-standard");
  assert.equal(joinModeId("theroad", ""), "theroad");
});

test("modes 服务：GET/PUT 路径与体（session 编码；写入走命令总线）", async () => {
  const { rest, calls } = fakeRest(() => DTO);
  const svc = createModesService({ rest, commands: createCommandBus() });
  await svc.get("w1", "conversation-1.jsonl");
  assert.equal(calls[0]?.method, "GET");
  assert.equal(calls[0]?.path,
    "/api/v1/workspaces/w1/session-modes?session=conversation-1.jsonl");
  await svc.set("w1", "conversation-1.jsonl", splitModeId("minimal-pure"));
  assert.equal(calls[1]?.method, "PUT");
  assert.equal(calls[1]?.path,
    "/api/v1/workspaces/w1/session-modes?session=conversation-1.jsonl");
  assert.deepEqual(calls[1]?.body, { mode: "minimal", variant: "pure" });
  // 会话名编码（防注入路径分隔符）
  await svc.get("w1", "a b.jsonl");
  assert.equal(calls[2]?.path,
    "/api/v1/workspaces/w1/session-modes?session=a%20b.jsonl");
});

test("设置分区：模式分区存在 + 字段（默认/显隐/pure 自动确认）", async () => {
  const { deriveFields, SETTINGS_SECTIONS } = await import("../src/views/settings/model.ts");
  assert.ok(SETTINGS_SECTIONS.some((s) => s.id === "modes"),
    "设置导航必须含 modes 分区");
  const schema = [
    { name: "mode_default", type: "str", enum: ["minimal-pure", "minimal-standard", "theroad"], default: "minimal-standard" },
    { name: "mode_picker_enabled", type: "bool", default: true },
    { name: "minimal_pure_auto_confirm", type: "bool", default: true },
  ];
  const fields = deriveFields("modes", schema, {
    values: { mode_default: "minimal-standard", mode_picker_enabled: true },
    sources: { mode_default: "default" },
  });
  const names = fields.map((f) => f.name);
  assert.deepEqual(names, ["mode_default", "mode_picker_enabled", "minimal_pure_auto_confirm"]);
  const first = fields[0];
  assert.equal(first?.control, "select");
  assert.deepEqual(first?.options, ["minimal-pure", "minimal-standard", "theroad"]);
});
