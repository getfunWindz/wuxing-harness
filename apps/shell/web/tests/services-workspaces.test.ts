import { test } from "node:test";
import assert from "node:assert/strict";

import { createCommandBus } from "../src/runtime/commands.ts";
import type { WritableRestClient } from "../src/runtime/connection/rest.ts";
import { createWorkspacesService } from "../src/runtime/services/workspaces.ts";

function fakeRest(payload: unknown): WritableRestClient & { paths: string[] } {
  const paths: string[] = [];
  return {
    paths,
    async get<T>(path: string): Promise<T> {
      paths.push(path);
      return payload as T;
    },
    async post<T>(): Promise<T> {
      throw new Error("unused");
    },
    async put<T>(): Promise<T> {
      throw new Error("unused");
    },
    async patch<T>(): Promise<T> {
      throw new Error("unused");
    },
    async del<T>(): Promise<T> {
      throw new Error("unused");
    },
  };
}

test("refresh：投影播种 + 默认激活第一个工作区 + 通知", async () => {
  const rest = fakeRest({
    workspaces: [
      { id: "w1", path: "/a", name: "a", auto_confirm: false, status: "idle", folder: null },
    ],
    folders: [],
  });
  const service = createWorkspacesService({ rest, commands: createCommandBus() });
  const notices: number[] = [];
  service.subscribe(() => { notices.push(service.list().length); });
  await service.refresh();
  assert.equal(service.list().length, 1);
  assert.equal(service.activeId(), "w1");
  assert.deepEqual(notices, [1]);
  assert.deepEqual(rest.paths, ["/api/v1/workspaces"]);
});

test("create：POST 创建 → 刷新列表 → 激活新工作区", async () => {
  const calls: string[] = [];
  const rest = {
    async get<T>(path: string): Promise<T> {
      calls.push(`GET ${path}`);
      return {
        workspaces: [{ id: "w9", path: "/x", name: "x", auto_confirm: false, status: "idle", folder: null }],
        folders: [],
      } as T;
    },
    async post<T>(path: string, body?: unknown): Promise<T> {
      calls.push(`POST ${path} ${JSON.stringify(body)}`);
      return { id: "w9" } as T;
    },
    async put<T>(): Promise<T> {
      throw new Error("unused");
    },
    async patch<T>(): Promise<T> {
      throw new Error("unused");
    },
    async del<T>(): Promise<T> {
      throw new Error("unused");
    },
  } as WritableRestClient;
  const service = createWorkspacesService({ rest, commands: createCommandBus() });
  const id = await service.create("C:/tmp/ws");
  assert.equal(id, "w9");
  assert.equal(service.activeId(), "w9");
  assert.equal(service.list().length, 1);
  assert.deepEqual(calls, [
    'POST /api/v1/workspaces {"path":"C:/tmp/ws"}',
    "GET /api/v1/workspaces",
  ]);
});
