import { test } from "node:test";
import assert from "node:assert/strict";

import { createRuntime } from "../src/app/boot.ts";
import type { SseConnectOptions } from "../src/runtime/connection/sse.ts";

function jsonResponse(payload: unknown): Response {
  return new Response(JSON.stringify(payload), { status: 200 });
}

const WORKSPACES = {
  workspaces: [{
    id: "w1", path: "/a", name: "a",
    auto_confirm: false, status: "idle", folder: null,
  }],
  folders: [],
};

const SNAPSHOT = {
  workspace: WORKSPACES.workspaces[0],
  active_run: null,
  result: null,
  task_text: "",
  run_id: "",
  units: [],
  pending_confirms: [],
  last_seq: 0,
};

test("两阶段启动：激活 → 刷新 → 切换工作区 → settle；事件驱动任务状态", async () => {
  const transports: SseConnectOptions[] = [];
  let settled = false;
  const runtime = createRuntime({
    baseUrl: "http://svc",
    fetchLike: async (input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/workspaces")) return jsonResponse(WORKSPACES);
      if (url.includes("/snapshot")) return jsonResponse(SNAPSHOT);
      return jsonResponse({ run_id: "r1", workspace_id: "w1" });
    },
    transport: (opts) => {
      transports.push(opts);
      return { close() {} };
    },
    onStatus: () => {},
    onSettle: () => { settled = true; },
  });
  await runtime.start();
  assert.equal(settled, true);
  assert.deepEqual(runtime.workspaces.list().map((w) => w.id), ["w1"]);
  assert.equal(runtime.workspaces.activeId(), "w1");
  assert.equal(transports.length, 1);
  assert.match(transports[0]?.url ?? "", /\/api\/v1\/events\?since=0$/);

  transports[0]?.onMessage(JSON.stringify({
    v: 1, epoch: "E", seq: 1, ts: 0, workspace_id: "w1", run_id: "r1",
    type: "task_submitted", data: { task_text: "跑" },
  }));
  assert.equal(runtime.tasks.state().status, "running");
  assert.equal(runtime.tasks.state().taskText, "跑");

  runtime.stop();
});

test("resync_required：投影重置 + 全量重拉（工作区刷新两次）", async () => {
  const transports: SseConnectOptions[] = [];
  let workspaceFetches = 0;
  const runtime = createRuntime({
    baseUrl: "http://svc",
    fetchLike: async (input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/workspaces")) {
        workspaceFetches += 1;
        return jsonResponse(WORKSPACES);
      }
      if (url.includes("/snapshot")) return jsonResponse(SNAPSHOT);
      return jsonResponse({});
    },
    transport: (opts) => {
      transports.push(opts);
      return { close() {} };
    },
    onStatus: () => {},
  });
  await runtime.start();
  assert.equal(workspaceFetches, 1);
  transports[0]?.onMessage(JSON.stringify({ epoch: "E", last_seq: 5 }), "resync_required");
  await new Promise((resolve) => setTimeout(resolve, 10));
  assert.equal(workspaceFetches, 2);
  runtime.stop();
});

test("epoch 变更（hello）：全量重拉", async () => {
  const transports: SseConnectOptions[] = [];
  let workspaceFetches = 0;
  const runtime = createRuntime({
    baseUrl: "http://svc",
    fetchLike: async (input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/workspaces")) {
        workspaceFetches += 1;
        return jsonResponse(WORKSPACES);
      }
      if (url.includes("/snapshot")) return jsonResponse(SNAPSHOT);
      return jsonResponse({});
    },
    transport: (opts) => {
      transports.push(opts);
      return { close() {} };
    },
    onStatus: () => {},
  });
  await runtime.start();
  transports[0]?.onMessage(JSON.stringify({ epoch: "E1", last_seq: 1, gap: false }), "hello");
  await new Promise((resolve) => setTimeout(resolve, 10));
  assert.equal(workspaceFetches, 1, "首个 hello 不应触发重拉");
  transports[0]?.onMessage(JSON.stringify({ epoch: "E2", last_seq: 0, gap: false }), "hello");
  await new Promise((resolve) => setTimeout(resolve, 10));
  assert.equal(workspaceFetches, 2, "epoch 变更应触发重拉");
  runtime.stop();
});

test("启动失败（refresh 抛错）→ start 拒绝（错误边界）", async () => {
  const runtime = createRuntime({
    baseUrl: "http://svc",
    fetchLike: async () => { throw new Error("boom"); },
    transport: () => ({ close() {} }),
    onStatus: () => {},
  });
  await assert.rejects(runtime.start(), /boom/);
  runtime.stop();
});
