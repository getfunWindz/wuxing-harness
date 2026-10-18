import { test } from "node:test";
import assert from "node:assert/strict";

import { createCommandBus } from "../src/runtime/commands.ts";
import type { WritableRestClient } from "../src/runtime/connection/rest.ts";
import { createContextService } from "../src/runtime/services/context.ts";
import type { ContextPreviewDto } from "../src/protocol/generated.ts";

const EMPTY_PREVIEW = {
  session: "conversation-1.jsonl", unit_id: "", window: 200000,
  est_tokens: 108, percent: 0.0005, segments: [], rounds: [],
  anchor_tokens: null, anchor_ts: null, anchor_unit: "",
  unknown: [], available: true, reason: "",
} as unknown as ContextPreviewDto;

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

test("context 服务：预览（session/unit）/ 列表 / 编辑（omit 不带 content）", async () => {
  const { rest, calls } = fakeRest((method, path) => {
    if (method === "GET" && path.includes("context-previews")) {
      return { items: [] };
    }
    if (method === "POST") return { ok: true, preview: EMPTY_PREVIEW };
    return EMPTY_PREVIEW;
  });
  const svc = createContextService({ rest, commands: createCommandBus() });
  await svc.preview("w1", { session: "conversation-1.jsonl" });
  assert.equal(calls[0]?.path,
    "/api/v1/workspaces/w1/context-preview?session=conversation-1.jsonl");
  await svc.preview("w1", { unit: "P-a" });
  assert.equal(calls[1]?.path,
    "/api/v1/workspaces/w1/context-preview?unit=P-a");
  await svc.previews("w1");
  assert.equal(calls[2]?.path, "/api/v1/workspaces/w1/context-previews");
  await svc.edit("w1", "conversation-1.jsonl", { round: 2, op: "omit" });
  assert.equal(calls[3]?.path,
    "/api/v1/workspaces/w1/conversations/conversation-1.jsonl/context-edits");
  assert.deepEqual(calls[3]?.body, { round: 2, op: "omit" });
  await svc.edit("w1", "conversation-1.jsonl",
    { round: 1, op: "replace", content: "改写" });
  assert.deepEqual(calls[4]?.body, { round: 1, op: "replace", content: "改写" });
  // A1：来源开关读取/写入
  await svc.sources("w1", { session: "conversation-1.jsonl" });
  assert.equal(calls[5]?.path,
    "/api/v1/workspaces/w1/context-sources?session=conversation-1.jsonl");
  await svc.setSources("w1", { unit: "P-a" },
    { history: false, budget_tokens: 5000 });
  assert.equal(calls[6]?.path,
    "/api/v1/workspaces/w1/context-sources?unit=P-a");
  assert.deepEqual(calls[6]?.body, { history: false, budget_tokens: 5000 });
  // A2：碎片消息三键编辑
  await svc.editUnit("w1", "P-a",
    { index: 3, fp_in: "aa", fp_out: "bb", op: "omit" });
  assert.equal(calls[7]?.path,
    "/api/v1/workspaces/w1/unit-sessions/P-a/context-edits");
  assert.deepEqual(calls[7]?.body,
    { index: 3, fp_in: "aa", fp_out: "bb", op: "omit" });
});

test("context 服务：承接简报读取（只读直连——批 4）", async () => {
  const { rest, calls } = fakeRest(() => ({
    available: true, source_session: "c1.jsonl", rounds: 2, brief: "简报",
  }));
  const svc = createContextService({ rest, commands: createCommandBus() });
  await svc.handoffBrief("w1", "c1.jsonl");
  assert.equal(calls[0]?.method, "GET");
  assert.equal(calls[0]?.path,
    "/api/v1/workspaces/w1/handoff-brief?session=c1.jsonl");
});

test("context 服务：restore 不带 content（G3）", async () => {
  const { rest, calls } = fakeRest((method) => {
    if (method === "POST") return { ok: true, preview: EMPTY_PREVIEW };
    return EMPTY_PREVIEW;
  });
  const svc = createContextService({ rest, commands: createCommandBus() });
  await svc.edit("w1", "conversation-1.jsonl", { round: 2, op: "restore" });
  assert.equal(calls[0]?.path,
    "/api/v1/workspaces/w1/conversations/conversation-1.jsonl/context-edits");
  assert.deepEqual(calls[0]?.body, { round: 2, op: "restore" });
  await svc.editUnit("w1", "P-a",
    { index: 1, fp_in: "a", fp_out: "b", op: "restore" });
  assert.equal(calls[1]?.path,
    "/api/v1/workspaces/w1/unit-sessions/P-a/context-edits");
  assert.deepEqual(calls[1]?.body,
    { index: 1, fp_in: "a", fp_out: "b", op: "restore" });
});
