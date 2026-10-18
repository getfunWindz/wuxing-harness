/** 双模式批 3（Task 5）：设计服务 + needs_design 状态映射 + i18n 键在场。 */
import { test } from "node:test";
import assert from "node:assert/strict";

import { createCommandBus } from "../src/runtime/commands.ts";
import type { WritableRestClient } from "../src/runtime/connection/rest.ts";
import { createTaskService } from "../src/runtime/services/tasks.ts";
import { createDesignService } from "../src/runtime/services/design.ts";
import type { AnyEvent, DesignStateDto } from "../src/protocol/generated.ts";
import { statusLabel } from "../src/views/view-model.ts";
import { setLang, t } from "../src/views/i18n.ts";

const DTO: DesignStateDto = {
  session: "c1.jsonl", phase: "grilling", round: 2,
  questions: [{ q: "范围？", recommend: "最小可用" }],
  tickets: [{ id: "Q-1", statement: "范围？", recommend: "最小可用",
              blocked_by: [], status: "open", resolution: "", frontier: true }],
  facts: ["仅 docs/"], map_path: "WUXING.md", map_hash: "",
  map_changed: false, map_ready: false, available: true,
  spec: null,
  drift: [],
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

function event(seq: number, type: string, data: Record<string, unknown>): AnyEvent {
  return {
    v: 1, epoch: "e", seq, ts: 0, workspace_id: "w1",
    run_id: "r1", type, data,
  } as unknown as AnyEvent;
}

test("design 服务：GET 设计态 / PUT 交接（命令总线）/ GET 地图", async () => {
  const { rest, calls } = fakeRest((method, path) => {
    if (path.endsWith("/map")) {
      return { available: true, project: "P", destination: "D", route: [],
               decisions: [], fog: [], out_of_scope: [], hash: "h" };
    }
    return DTO;
  });
  const svc = createDesignService({ rest, commands: createCommandBus() });
  await svc.get("w1", "c1.jsonl");
  assert.equal(calls[0]?.method, "GET");
  assert.equal(calls[0]?.path,
    "/api/v1/workspaces/w1/design-state?session=c1.jsonl");
  await svc.handoff("w1", "c1.jsonl");
  assert.equal(calls[1]?.method, "PUT");
  assert.deepEqual(calls[1]?.body, { phase: "ready" });
  await svc.map("w1");
  assert.equal(calls[2]?.path, "/api/v1/workspaces/w1/map");
});

test("needs_design：task_done 映射 + 状态标签 + i18n 键在场", () => {
  const svc = createTaskService({
    rest: fakeRest(() => ({})) as unknown as WritableRestClient,
    commands: createCommandBus(),
    workspaceId: () => "w1",
  });
  svc.applyEvent(event(99, "task_done", { status: "needs_design" }));
  assert.equal(svc.state().status, "needs_design");
  setLang("zh");
  assert.equal(statusLabel("needs_design"), t("status.needs_design"));
  assert.equal(t("status.needs_design"), "待设计");
  // 设计卡片/地图文案键在场（zh/en 字典守卫由 i18n.test.ts 全量覆盖）
  for (const key of ["design.title", "design.phase.grilling", "design.handoff",
                     "design.viewMap", "map.title", "map.destination",
                     "design.specReady", "design.viewSpec",
                     "design.ticketRunning", "design.ticketDone",
                     "design.ticketFailed", "design.ticketCancelled"]) {
    assert.notEqual(t(key), key, key);
  }
});

test("票据服务：GET 列表 / 发布走命令总线（POST /publish）", async () => {
  const { createDesignService } = await import("../src/runtime/services/design.ts");
  const calls: Array<{ method: string; path: string; body?: unknown }> = [];
  const rest = {
    async get<T>(path: string): Promise<T> {
      calls.push({ method: "GET", path });
      return { tickets: [], spec: "" } as T;
    },
    async put<T>(_path: string, _body?: unknown): Promise<T> { return {} as T; },
    async post<T>(path: string, body?: unknown): Promise<T> {
      calls.push({ method: "POST", path, body });
      return { tickets: [], spec: "" } as T;
    },
  };
  const svc = createDesignService({ rest: rest as never, commands: createCommandBus() });
  await svc.tickets("w1");
  await svc.publishTickets("w1");
  assert.equal(calls[0]?.path, "/api/v1/workspaces/w1/tickets");
  assert.equal(calls[1]?.path, "/api/v1/workspaces/w1/tickets/publish");
  assert.deepEqual(calls[1]?.body, {});
});

test("规格文件 URL：逐段编码（.wuxing/specs 路径可用）", async () => {
  const { createDesignService } = await import("../src/runtime/services/design.ts");
  const svc = createDesignService({ rest: fakeRest(() => ({})) as unknown as WritableRestClient,
                                    commands: createCommandBus() });
  assert.equal(svc.specFileUrl("w1", ".wuxing/specs/s-a.md"),
    "/api/v1/workspaces/w1/artifacts/.wuxing/specs/s-a.md");
});
