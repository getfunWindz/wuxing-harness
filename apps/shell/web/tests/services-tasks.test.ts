import { test } from "node:test";
import assert from "node:assert/strict";

import { createCommandBus } from "../src/runtime/commands.ts";
import type { RestClient } from "../src/runtime/connection/rest.ts";
import {
  createTaskService,
  INITIAL_TASK_STATE,
  taskViewForSession,
} from "../src/runtime/services/tasks.ts";
import type { AnyEvent } from "../src/protocol/generated.ts";

function event(
  seq: number,
  type: string,
  data: Record<string, unknown>,
  workspaceId = "w1",
  runId = "r1",
): AnyEvent {
  return {
    v: 1, epoch: "e", seq, ts: 0, workspace_id: workspaceId,
    run_id: runId, type, data,
  } as unknown as AnyEvent;
}

function fakeRest(
  handler: (method: string, path: string, body?: unknown) => unknown,
): RestClient {
  return {
    async get<T>(path: string): Promise<T> { return handler("GET", path) as T; },
    async post<T>(path: string, body?: unknown): Promise<T> {
      return handler("POST", path, body) as T;
    },
  };
}

test("事件归约：提交→单元→进度原位→完成", () => {
  const service = createTaskService({
    rest: fakeRest(() => ({})),
    commands: createCommandBus(),
    workspaceId: () => "w1",
  });
  service.applyEvent(event(1, "task_submitted", { task_text: "跑" }));
  assert.equal(service.state().runId, "r1", "run_id 应从事件采纳");
  service.applyEvent(event(2, "unit_started", { unit_id: "u1", domain_id: "execute" }));
  service.applyEvent(event(3, "progress", {
    unit_id: "u1", domain_id: "execute", stage: "写代码", eta: "1m",
  }));
  service.applyEvent(event(4, "unit_done", { unit_id: "u1", domain_id: "execute", status: "ok" }));
  service.applyEvent(event(99, "task_done", { status: "done" }));
  const state = service.state();
  assert.equal(state.status, "done");
  assert.equal(state.rows.length, 1);
  assert.equal(state.rows[0]?.detail, "写代码");
  assert.equal(state.rows[0]?.eta, "1m");
  assert.equal(state.rows[0]?.status, "ok");
});

test("确认门：挂起 → 待确认列表；done 后清空", () => {
  const service = createTaskService({
    rest: fakeRest(() => ({})),
    commands: createCommandBus(),
    workspaceId: () => "w1",
  });
  service.applyEvent(event(1, "task_submitted", { task_text: "跑" }));
  service.applyEvent(event(2, "unit_needs_confirm", {
    unit_id: "u9", domain_id: "plan", reason: "风险",
  }));
  assert.equal(service.state().status, "pending");
  assert.equal(service.state().pendingConfirms[0]?.unit_id, "u9");
  service.applyEvent(event(3, "task_done", { status: "pending" }));
  assert.equal(service.state().pendingConfirms.length, 1);
  service.applyEvent(event(4, "task_done", { status: "done" }));
  assert.equal(service.state().pendingConfirms.length, 0);
});

test("终态后自动刷新快照（结果落库可见）", async () => {
  let snapshotCalls = 0;
  const service = createTaskService({
    rest: fakeRest((method, path) => {
      if (method === "GET" && path.endsWith("/snapshot")) {
        snapshotCalls += 1;
        return {
          workspace: {
            id: "w1", path: "/a", name: "a",
            auto_confirm: false, status: "idle", folder: null,
          },
          active_run: null,
          result: { status: "done", report: "完成", artifacts: [], metrics: {} },
          task_text: "跑", run_id: "r1", units: [], pending_confirms: [], last_seq: 99,
        };
      }
      return {};
    }),
    commands: createCommandBus(),
    workspaceId: () => "w1",
  });
  await service.setWorkspace("w1");
  service.applyEvent(event(100, "task_done", { status: "done" }));
  await new Promise((resolve) => setTimeout(resolve, 20));
  assert.equal(snapshotCalls, 2);
  assert.equal(service.state().result?.report, "完成");
});

test("快照刷新：快照未覆盖的事件行保留（含详情）", async () => {
  const service = createTaskService({
    rest: fakeRest((method, path) => {
      if (method === "GET" && path.endsWith("/snapshot")) {
        return {
          workspace: {
            id: "w1", path: "/a", name: "a",
            auto_confirm: false, status: "idle", folder: null,
          },
          active_run: null,
          result: { status: "done", report: "完成", artifacts: [], metrics: {} },
          task_text: "跑", run_id: "r1",
          units: [{ unit_id: "u2", domain_id: "verify", status: "ok" }],
          pending_confirms: [], last_seq: 99,
        };
      }
      return {};
    }),
    commands: createCommandBus(),
    workspaceId: () => "w1",
  });
  await service.setWorkspace("w1");
  service.applyEvent(event(100, "task_submitted", { task_text: "跑" }));
  service.applyEvent(event(101, "unit_started", { unit_id: "u1", domain_id: "execute" }));
  service.applyEvent(event(102, "progress", {
    unit_id: "u1", domain_id: "execute", stage: "写", eta: "",
  }));
  service.applyEvent(event(103, "task_done", { status: "done" }));
  await new Promise((resolve) => setTimeout(resolve, 20));
  const rows = service.state().rows;
  const u1 = rows.find((row) => row.unitId === "u1");
  const u2 = rows.find((row) => row.unitId === "u2");
  assert.equal(u1?.detail, "写", "事件行应保留（含详情）");
  assert.equal(u2?.status, "ok", "快照行应纳入");
  assert.equal(service.state().result?.report, "完成");
});

test("引擎失败的错误在快照刷新后仍可见（不被 seed 清除）", async () => {
  const service = createTaskService({
    rest: fakeRest((method, path) => {
      if (method === "GET" && path.endsWith("/snapshot")) {
        return {
          workspace: {
            id: "w1", path: "/a", name: "a",
            auto_confirm: false, status: "idle", folder: null,
          },
          active_run: null,
          result: null,
          task_text: "跑", run_id: "r1", units: [], pending_confirms: [], last_seq: 99,
        };
      }
      return {};
    }),
    commands: createCommandBus(),
    workspaceId: () => "w1",
  });
  await service.setWorkspace("w1");
  service.applyEvent(event(100, "task_submitted", { task_text: "跑" }));
  service.applyEvent(event(101, "task_failed", { error: "模拟引擎失败" }));
  await new Promise((resolve) => setTimeout(resolve, 20));
  assert.equal(service.state().status, "error");
  assert.equal(service.state().error, "模拟引擎失败");
});

test("第二个任务：runId 随 task_submitted 更新（确认不得打到旧 run）", async () => {
  const posts: string[] = [];
  const service = createTaskService({
    rest: {
      async get<T>(): Promise<T> { throw new Error("unused"); },
      async post<T>(path: string): Promise<T> { posts.push(path); return {} as T; },
    },
    commands: createCommandBus(),
    workspaceId: () => "w1",
  });
  service.applyEvent(event(1, "task_submitted", { task_text: "任务一" }));
  assert.equal(service.state().runId, "r1");
  service.applyEvent(event(2, "task_done", { status: "done" }));
  service.applyEvent(event(3, "task_submitted", { task_text: "任务二" }, "w1", "r2"));
  assert.equal(service.state().runId, "r2", "新任务必须接管新 run");
  service.applyEvent(event(4, "unit_needs_confirm", {
    unit_id: "u9", domain_id: "plan", reason: "风险",
  }, "w1", "r2"));
  await service.confirm([["u9", true]]);
  assert.ok(posts[0]?.includes("/tasks/r2/confirm"), `确认须打到新 run：${posts[0]}`);
});

test("新任务提交：清除上一轮结果但保留待确认（用户裁决 2026-10-01：跨轮记录不丢）", async () => {
  const service = createTaskService({
    rest: fakeRest((method, path) => {
      if (method === "GET" && path.endsWith("/snapshot")) {
        return {
          workspace: {
            id: "w1", path: "/a", name: "a",
            auto_confirm: false, status: "idle", folder: null,
          },
          active_run: null,
          result: { status: "failed", report: "旧结果", artifacts: [], metrics: {} },
          task_text: "旧任务", run_id: "r0",
          units: [],
          pending_confirms: [{ unit_id: "u0", domain_id: "plan", reason: "旧待确认" }],
          last_seq: 5,
        };
      }
      return {};
    }),
    commands: createCommandBus(),
    workspaceId: () => "w1",
  });
  await service.setWorkspace("w1");
  assert.equal(service.state().result?.report, "旧结果");
  service.applyEvent(event(6, "task_submitted", { task_text: "新任务" }));
  assert.equal(service.state().result, null, "新任务不得继承旧结果");
  assert.equal(service.state().pendingConfirms.length, 1,
    "新任务不得清除上一轮待确认（否则旧轮确认永久丢失）");
  assert.equal(service.state().pendingConfirms[0]?.runId, "r0", "确认须携带原 run 身份");
  assert.equal(service.state().error, "");
});

test("终态仅清理本 run 的待确认（跨轮确认保留可路由）", () => {
  const service = createTaskService({
    rest: fakeRest(() => ({})),
    commands: createCommandBus(),
    workspaceId: () => "w1",
  });
  service.applyEvent(event(1, "task_submitted", { task_text: "第一轮" }, "w1", "r1"));
  service.applyEvent(event(2, "unit_needs_confirm", {
    unit_id: "u1", domain_id: "verify", reason: "旧确认", impact: {},
  }, "w1", "r1"));
  service.applyEvent(event(3, "task_submitted", { task_text: "第二轮" }, "w1", "r2"));
  service.applyEvent(event(4, "unit_needs_confirm", {
    unit_id: "u2", domain_id: "verify", reason: "新确认", impact: {},
  }, "w1", "r2"));
  service.applyEvent(event(5, "task_done", { status: "done" }, "w1", "r2"));
  const left = service.state().pendingConfirms;
  assert.equal(left.length, 1, "只清理本 run 的待确认");
  assert.equal(left[0]?.unit_id, "u1");
  assert.equal(left[0]?.runId, "r1");
});

test("confirm 按待确认项所属 run 路由（跨轮确认回打原 run）", async () => {
  const posts: string[] = [];
  const service = createTaskService({
    rest: {
      async get<T>(path: string): Promise<T> {
        if (path.endsWith("/snapshot")) {
          return {
            workspace: {
              id: "w1", path: "/a", name: "a",
              auto_confirm: false, status: "idle", folder: null,
            },
            active_run: null, result: null,
            task_text: "旧任务", run_id: "r0", units: [],
            pending_confirms: [{ unit_id: "u0", domain_id: "verify", reason: "旧确认" }],
            last_seq: 3,
          } as T;
        }
        throw new Error("unused");
      },
      async post<T>(path: string): Promise<T> {
        posts.push(path);
        return {} as T;
      },
    },
    commands: createCommandBus(),
    workspaceId: () => "w1",
  });
  await service.setWorkspace("w1");
  service.applyEvent(event(4, "task_submitted", { task_text: "新任务" }, "w1", "r1"));
  await service.confirm([["u0", true]]);
  assert.ok(posts[0]?.includes("/tasks/r0/confirm"),
    `旧轮确认必须回打原 run：${posts[0]}`);
  assert.equal(service.state().pendingConfirms.length, 0, "已处理的确认本地移除");
});

test("confirm 请求携带 [unit_id, approve] 对 + 理由（服务端契约）", async () => {
  const posts: Array<{ path: string; body: unknown }> = [];
  const service = createTaskService({
    rest: {
      async get<T>(path: string): Promise<T> {
        if (path.endsWith("/snapshot")) {
          return {
            workspace: {
              id: "w1", path: "/a", name: "a",
              auto_confirm: false, status: "idle", folder: null,
            },
            active_run: null,
            result: null,
            task_text: "跑", run_id: "r1", units: [], pending_confirms: [], last_seq: 99,
          } as T;
        }
        throw new Error("unused");
      },
      async post<T>(path: string, body?: unknown): Promise<T> {
        posts.push({ path, body });
        return {} as T;
      },
    },
    commands: createCommandBus(),
    workspaceId: () => "w1",
  });
  await service.setWorkspace("w1");
  await service.confirm([["u1", true], ["u2", false]], "不完整");
  assert.deepEqual(posts[0]?.body, {
    items: [["u1", true], ["u2", false]],
    reason: "不完整",
  });
});

test("confirm 成功后本地移除已处理待确认（其余保留）", async () => {
  const service = createTaskService({
    rest: fakeRest(() => ({})),
    commands: createCommandBus(),
    workspaceId: () => "w1",
  });
  service.applyEvent(event(1, "task_submitted", { task_text: "跑" }));
  service.applyEvent(event(2, "unit_needs_confirm", {
    unit_id: "u1", domain_id: "plan", reason: "风险",
  }));
  service.applyEvent(event(3, "unit_needs_confirm", {
    unit_id: "u2", domain_id: "execute", reason: "风险",
  }));
  assert.equal(service.state().pendingConfirms.length, 2);
  await service.confirm([["u1", true]]);
  assert.deepEqual(
    service.state().pendingConfirms.map((p) => p.unit_id),
    ["u2"],
    "已处理单元即时收敛，其余保留",
  );
});

test("confirm 失败：投影不动 + 命令总线失败可见", async () => {
  const failures: string[] = [];
  const service = createTaskService({
    rest: fakeRest(() => { throw new Error("未知或已处理的待确认单元"); }),
    commands: createCommandBus((e) => { failures.push(e.name); }),
    workspaceId: () => "w1",
  });
  service.applyEvent(event(1, "task_submitted", { task_text: "跑" }));
  service.applyEvent(event(2, "unit_needs_confirm", {
    unit_id: "u1", domain_id: "plan", reason: "风险",
  }));
  await assert.rejects(() => service.confirm([["u1", true]]));
  assert.deepEqual(
    service.state().pendingConfirms.map((p) => p.unit_id),
    ["u1"],
    "失败不得移除待确认",
  );
  assert.deepEqual(failures, ["task.confirm"], "失败必可见（命令总线）");
});

test("旧序事件被拒绝；跨工作区事件被忽略", () => {
  const service = createTaskService({
    rest: fakeRest(() => ({})),
    commands: createCommandBus(),
    workspaceId: () => "w1",
  });
  service.applyEvent(event(1, "task_submitted", { task_text: "跑" }));
  service.applyEvent(event(1, "unit_started", { unit_id: "u1", domain_id: "execute" }));
  assert.equal(service.state().rows.length, 0);
  service.applyEvent(event(5, "unit_started", { unit_id: "u2", domain_id: "execute" }, "other"));
  assert.equal(service.state().rows.length, 0);
  assert.deepEqual(INITIAL_TASK_STATE.rows, []);
});

test("submit：携带参考文件（references）；无参考不携带键", async () => {
  const posts: Array<{ path: string; body: unknown }> = [];
  const service = createTaskService({
    rest: {
      async get<T>(): Promise<T> { throw new Error("unused"); },
      async post<T>(path: string, body?: unknown): Promise<T> {
        posts.push({ path, body });
        return {} as T;
      },
    },
    commands: createCommandBus(),
    workspaceId: () => "w1",
  });
  await service.submit("跑", ["/abs/a.md", "/abs/b.md"]);
  await service.submit("跑2");
  assert.deepEqual(posts[0]?.body, { text: "跑", references: ["/abs/a.md", "/abs/b.md"] });
  assert.deepEqual(posts[1]?.body, { text: "跑2" });
});

test("rollback：回滚 run（可携带删除产物标志）", async () => {
  const posts: Array<{ path: string; body: unknown }> = [];
  const service = createTaskService({
    rest: {
      async get<T>(): Promise<T> { throw new Error("unused"); },
      async post<T>(path: string, body?: unknown): Promise<T> {
        posts.push({ path, body });
        return {} as T;
      },
    },
    commands: createCommandBus(),
    workspaceId: () => "w1",
  });
  await service.rollback("r9", true);
  await service.rollback("r9");
  assert.deepEqual(posts, [
    { path: "/api/v1/workspaces/w1/tasks/r9/rollback", body: { delete_artifacts: true } },
    { path: "/api/v1/workspaces/w1/tasks/r9/rollback", body: { delete_artifacts: false } },
  ]);
});

test("思维链/单元产物归约：追加 + 去重 + 上限 + 新任务清空", () => {
  const service = createTaskService({
    rest: fakeRest(() => ({})),
    commands: createCommandBus(),
    workspaceId: () => "w1",
  });
  service.applyEvent(event(1, "task_submitted", { task_text: "跑" }));
  service.applyEvent(event(2, "unit_reasoning", {
    unit_id: "u1", domain_id: "execute", round: 1, text: "先看仓库",
  }));
  service.applyEvent(event(3, "artifact_written", { unit_id: "u1", path: "a.md", kind: "md" }));
  service.applyEvent(event(4, "artifact_written", { unit_id: "u1", path: "a.md", kind: "md" }));
  assert.deepEqual(service.state().thoughts, [{ unitId: "u1", round: 1, text: "先看仓库" }]);
  assert.deepEqual(service.state().unitArtifacts, [{ unitId: "u1", path: "a.md", kind: "md" }]);
  for (let i = 0; i < 35; i += 1) {
    service.applyEvent(event(10 + i, "unit_reasoning", {
      unit_id: "u1", domain_id: "execute", round: i, text: `t${i}`,
    }));
  }
  assert.equal(service.state().thoughts.length, 30, "思维链容量上限 30");
  assert.equal(service.state().thoughts.at(-1)?.text, "t34");
  service.applyEvent(event(100, "task_submitted", { task_text: "跑2" }, "w1", "r2"));
  assert.deepEqual(service.state().thoughts, [], "新任务清空思维链");
  assert.deepEqual(service.state().unitArtifacts, [], "新任务清空单元产物");
});

test("思维链增量归约（Task 3-1）：delta 追加建行 / 整段幂等合并 / 单条截断", () => {
  const service = createTaskService({
    rest: fakeRest(() => ({})),
    commands: createCommandBus(),
    workspaceId: () => "w1",
  });
  service.applyEvent(event(1, "task_submitted", { task_text: "跑" }));
  // 首个 delta 建行；后续 delta 追尾（同一 unit+round）
  service.applyEvent(event(2, "unit_reasoning_delta", {
    unit_id: "u1", domain_id: "execute", round: 1, text: "先看",
  }));
  service.applyEvent(event(3, "unit_reasoning_delta", {
    unit_id: "u1", domain_id: "execute", round: 1, text: "仓库",
  }));
  assert.deepEqual(service.state().thoughts, [
    { unitId: "u1", round: 1, text: "先看仓库", streaming: true },
  ]);
  // 整段到达：以整段为准替换（不重复追加一行）
  service.applyEvent(event(4, "unit_reasoning", {
    unit_id: "u1", domain_id: "execute", round: 1, text: "先看仓库再说",
  }));
  assert.deepEqual(service.state().thoughts, [
    { unitId: "u1", round: 1, text: "先看仓库再说", streaming: false },
  ]);
  // 重复整段（无 delta 流）：保持“追加”旧行为（不同调用各自成行）
  service.applyEvent(event(5, "unit_reasoning", {
    unit_id: "u1", domain_id: "execute", round: 1, text: "先看仓库再说",
  }));
  assert.equal(service.state().thoughts.length, 2, "无 delta 流的整段各自成行");
  // 不同轮次：新行（不串轮）
  service.applyEvent(event(6, "unit_reasoning_delta", {
    unit_id: "u1", domain_id: "execute", round: 2, text: "第二轮",
  }));
  assert.equal(service.state().thoughts.length, 3);
  assert.equal(service.state().thoughts[2]?.text, "第二轮");
  // 单条截断 4000：delta 流累积封顶
  service.applyEvent(event(7, "unit_reasoning_delta", {
    unit_id: "u2", domain_id: "execute", round: 1, text: "x".repeat(3000),
  }));
  service.applyEvent(event(8, "unit_reasoning_delta", {
    unit_id: "u2", domain_id: "execute", round: 1, text: "y".repeat(3000),
  }));
  const thought = service.state().thoughts.find((t) => t.unitId === "u2");
  assert.equal(thought?.text.length, 4000, "单条累计截断 4000");
  // 空 delta 不建行
  service.applyEvent(event(9, "unit_reasoning_delta", {
    unit_id: "u3", domain_id: "execute", round: 1, text: "",
  }));
  assert.equal(service.state().thoughts.some((t) => t.unitId === "u3"), false);
});

test("思维链跨运行不串行（Task 3 回归修复）：整段只合并本次 delta 流，不覆盖旧行", () => {
  // 现场：确认续跑重跑同一 (unit, round)——旧实现整段替换命中间同行，
  // 新流文本较短→旧思考被覆盖（真机采样文本回缩）。
  const service = createTaskService({
    rest: fakeRest(() => ({})),
    commands: createCommandBus(),
    workspaceId: () => "w1",
  });
  service.applyEvent(event(1, "task_submitted", { task_text: "跑" }));
  service.applyEvent(event(2, "unit_reasoning_delta", {
    unit_id: "u1", domain_id: "execute", round: 1, text: "第一轮长文本",
  }));
  service.applyEvent(event(3, "unit_reasoning", {
    unit_id: "u1", domain_id: "execute", round: 1, text: "第一轮长文本",
  }));
  // 续跑：同 unit+round 的新 delta 流（短）——必须建新行，不得覆盖旧行
  service.applyEvent(event(4, "unit_reasoning_delta", {
    unit_id: "u1", domain_id: "execute", round: 1, text: "短",
  }));
  service.applyEvent(event(5, "unit_reasoning", {
    unit_id: "u1", domain_id: "execute", round: 1, text: "短",
  }));
  const thoughts = service.state().thoughts;
  assert.equal(thoughts.length, 2, "新流必须建新行（不覆盖旧行）");
  assert.equal(thoughts[0]?.text, "第一轮长文本");
  assert.equal(thoughts[1]?.text, "短");
  // 新流已收口（streaming=false）后再来整段：无开放流 → 保持追加旧行为（成新行）
  service.applyEvent(event(6, "unit_reasoning", {
    unit_id: "u1", domain_id: "execute", round: 1, text: "短",
  }));
  assert.equal(service.state().thoughts.length, 3);
});

test("快照刷新（同 run）保留流内思维链/单元产物", async () => {
  const service = createTaskService({
    rest: fakeRest((method, path) => {
      if (method === "GET" && path.endsWith("/snapshot")) {
        return {
          workspace: {
            id: "w1", path: "/a", name: "a",
            auto_confirm: false, status: "idle", folder: null,
          },
          active_run: null,
          result: { status: "done", report: "", artifacts: [], metrics: {} },
          task_text: "跑", run_id: "r1", units: [], pending_confirms: [], last_seq: 50,
        };
      }
      return {};
    }),
    commands: createCommandBus(),
    workspaceId: () => "w1",
  });
  service.applyEvent(event(1, "task_submitted", { task_text: "跑" }));
  service.applyEvent(event(2, "unit_reasoning", {
    unit_id: "u1", domain_id: "execute", round: 1, text: "思路",
  }));
  await service.setWorkspace("w1");
  assert.equal(service.state().thoughts.length, 1, "同 run 的流内思维链不被快照清空");
});

test("碎片提交：submit 携带 unit（空串不落键——字节稳定）", async () => {
  const bodies: Record<string, unknown>[] = [];
  const service = createTaskService({
    rest: fakeRest((method, path, body) => {
      if (method === "POST" && path.endsWith("/tasks")) {
        bodies.push({ ...(body as Record<string, unknown>) });
        return { run_id: "r1", workspace_id: "w1", session: "conversation-1.jsonl", unit: "" };
      }
      return {};
    }),
    commands: createCommandBus(),
    workspaceId: () => "w1",
  });
  await service.submit("碎片任务", [], "conversation-1.jsonl", "P-a");
  assert.equal(bodies[0]?.unit, "P-a");
  assert.equal(bodies[0]?.session, "conversation-1.jsonl");
  await service.submit("普通任务");
  assert.ok(!("unit" in (bodies[1] ?? {})), "空 unit 不携带（与空 references 同口径）");
  assert.ok(!("session" in (bodies[1] ?? {})), "空 session 不携带");
});

test("提交 override：非空写入 body（空串不携带——字节稳定）", async () => {
  const bodies: Record<string, unknown>[] = [];
  const service = createTaskService({
    rest: fakeRest((method, path, body) => {
      if (method === "POST" && path.endsWith("/tasks")) {
        bodies.push({ ...(body as Record<string, unknown>) });
        return { run_id: "r1", workspace_id: "w1", session: "conversation-1.jsonl", unit: "" };
      }
      return {};
    }),
    commands: createCommandBus(),
    workspaceId: () => "w1",
  });
  await service.submit("任务", [], "conversation-1.jsonl", "", "no_map");
  assert.equal(bodies[0]?.override, "no_map");
  await service.submit("任务2");
  assert.ok(!("override" in (bodies[1] ?? {})), "空 override 不携带");
});

test("会话串台修复：快照装载 run 会话；任务视图按会话隔离", async () => {
  const service = createTaskService({
    rest: fakeRest((method, path) => {
      if (method === "GET" && path.endsWith("/snapshot")) {
        return {
          workspace: {
            id: "w1", path: "/a", name: "a",
            auto_confirm: false, status: "idle", folder: null,
          },
          active_run: null,
          result: { status: "done", report: "会话A结果", artifacts: [], metrics: {} },
          task_text: "会话A任务", run_id: "r1",
          session: "conversation-a.jsonl",
          units: [], pending_confirms: [], last_seq: 99,
        };
      }
      return {};
    }),
    commands: createCommandBus(),
    workspaceId: () => "w1",
  });
  await service.setWorkspace("w1");
  assert.equal(service.state().session, "conversation-a.jsonl", "快照会话应装载");
  // 同会话 / 未指定会话（首页未选择）：原样返回（不回归）
  assert.equal(taskViewForSession(service.state(), "conversation-a.jsonl").taskText,
    "会话A任务");
  assert.equal(taskViewForSession(service.state(), null).taskText, "会话A任务");
  // 其他会话：任务流内容（历史/结果/确认）不得跨会话显示
  const other = taskViewForSession(service.state(), "conversation-b.jsonl");
  assert.equal(other.taskText, "");
  assert.equal(other.result, null);
  assert.equal(other.rows.length, 0);
  assert.equal(other.pendingConfirms.length, 0);
  assert.equal(other.status, "idle");
});

test("task_submitted 事件带 session：提交即建立会话归属", () => {
  const service = createTaskService({
    rest: fakeRest(() => ({})),
    commands: createCommandBus(),
    workspaceId: () => "w1",
  });
  service.applyEvent(event(1, "task_submitted", {
    task_text: "跑", session: "conversation-c.jsonl",
  }));
  assert.equal(service.state().session, "conversation-c.jsonl");
});

test("submit 响应带 session：归属写入投影（响应链路兜底）", async () => {
  const service = createTaskService({
    rest: fakeRest((method, path) => {
      if (method === "POST" && path.endsWith("/tasks")) {
        return { run_id: "r9", workspace_id: "w1", session: "conversation-b.jsonl", unit: "" };
      }
      return {};
    }),
    commands: createCommandBus(),
    workspaceId: () => "w1",
  });
  await service.submit("任务", [], "conversation-b.jsonl");
  assert.equal(service.state().session, "conversation-b.jsonl");
});

test("setWorkspace：快照缺 pending_confirms 字段不得崩溃（夹具兼容）", async () => {
  const service = createTaskService({
    rest: fakeRest((method, path) => {
      if (method === "GET" && path.endsWith("/snapshot")) {
        return {
          workspace: {
            id: "w1", path: "/a", name: "a",
            auto_confirm: false, status: "idle", folder: null,
          },
          active_run: null, result: null,
          task_text: "跑", run_id: "r1", units: [], last_seq: 9,
          // 注意：无 pending_confirms 字段（旧夹具形状）
        };
      }
      return {};
    }),
    commands: createCommandBus(),
    workspaceId: () => "w1",
  });
  await service.setWorkspace("w1");   // 不得抛 TypeError
  assert.equal(service.state().pendingConfirms.length, 0);
  assert.equal(service.state().workspaceId, "w1");
});

test("A10 提问：挂起登记 → 答复命令（run 路由 + 本地收敛）；回执清除", async () => {
  const posts: { path: string; body: unknown }[] = [];
  const service = createTaskService({
    rest: {
      async get<T>(): Promise<T> { throw new Error("unused"); },
      async post<T>(path: string, body?: unknown): Promise<T> {
        posts.push({ path, body });
        return {} as T;
      },
    },
    commands: createCommandBus(),
    workspaceId: () => "w1",
  });
  service.applyEvent(event(1, "task_submitted", { task_text: "提问任务" }));
  service.applyEvent(event(2, "unit_needs_answer", {
    unit_id: "A-1", domain_id: "execute", question_id: "ask-A-1-1",
    questions: [{ title: "格式？", options: ["md", "txt"], multi: false }],
  }));
  assert.equal(service.state().status, "pending");
  assert.equal(service.state().pendingAnswers[0]?.question_id, "ask-A-1-1");
  assert.equal(service.state().rows[0]?.status, "answer");
  await service.answer("A-1", "ask-A-1-1", "Q1 格式？：md", "option");
  assert.ok(posts[0]?.path.includes("/tasks/r1/answer"), String(posts[0]?.path));
  assert.equal((posts[0]?.body as Record<string, unknown>).question_id, "ask-A-1-1");
  assert.equal(service.state().pendingAnswers.length, 0, "POST 200 本地即时收敛");
  // 回执事件重复到达无害（先到为准）
  service.applyEvent(event(3, "question_answered", {
    unit_id: "A-1", question_id: "ask-A-1-1", answer: "md", source: "option",
  }));
  assert.equal(service.state().pendingAnswers.length, 0);
  // 再次提问（unit_done needs_answer）→ 行态不得显示 failed
  service.applyEvent(event(4, "unit_done", {
    unit_id: "A-1", domain_id: "execute", status: "needs_answer",
  }));
  assert.equal(service.state().rows[0]?.status, "answer");
  service.applyEvent(event(5, "task_done", { status: "done" }));
  assert.equal(service.state().status, "done");
});

test("worktree：ready 归约 + review/apply/discard 服务链路（E3-1/R5）", async () => {
  const posts: { path: string; body?: unknown }[] = [];
  const gets: string[] = [];
  const service = createTaskService({
    rest: {
      async get<T>(path: string): Promise<T> {
        gets.push(path);
        return {
          run_id: "r1", path: "C:/ws/.wuxing/worktrees/r1", status: "done",
          files: [{ status: "??", path: "mock-plan.md" }],
          diff: "diff --git a/mock-plan.md b/mock-plan.md",
        } as unknown as T;
      },
      async post<T>(path: string, body?: unknown): Promise<T> {
        posts.push({ path, body });
        return { ok: true, files: 2,
                 path: "C:/ws/.wuxing/worktrees/r1" } as unknown as T;
      },
    },
    commands: createCommandBus(),
    workspaceId: () => "w1",
  });
  service.applyEvent(event(1, "task_submitted", { task_text: "隔离任务" }));
  service.applyEvent(event(2, "worktree_ready",
    { path: "C:/ws/.wuxing/worktrees/r1" }));
  const wt = service.state().worktree;
  assert.ok(wt, "worktree_ready 应建立卡片态");
  assert.equal(wt.runId, "r1");
  await service.reviewWorktree("r1");
  assert.ok(gets[0]?.includes("/tasks/r1/worktree"), String(gets[0]));
  assert.equal(service.state().worktree?.files.length, 1);
  assert.equal(service.state().worktree?.reviewed, true);
  await service.applyWorktree("r1");
  assert.ok(posts[0]?.path.includes("/tasks/r1/worktree/apply"),
            String(posts[0]?.path));
  assert.equal(service.state().worktree?.notice?.kind, "applied");
  assert.equal(service.state().worktree?.notice?.n, 2);
  await service.discardWorktree("r1");
  assert.ok(posts[1]?.path.includes("/tasks/r1/worktree/discard"),
            String(posts[1]?.path));
  assert.equal(service.state().worktree, null);
});
