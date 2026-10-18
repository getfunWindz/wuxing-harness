import { test } from "node:test";
import assert from "node:assert/strict";

import { createRestClient, RestError } from "../src/runtime/connection/rest.ts";

test("GET 成功：返回 JSON 且不带变更头", async () => {
  const captured: Array<{ url: string; init: RequestInit | undefined }> = [];
  const fetchLike: typeof fetch = async (input, init) => {
    captured.push({ url: String(input), init });
    return new Response(JSON.stringify({ ok: 1 }), { status: 200 });
  };
  const client = createRestClient({ baseUrl: "http://x", fetchLike });
  const data = await client.get<{ ok: number }>("/api/v1/ping");
  assert.deepEqual(data, { ok: 1 });
  const headers = captured[0]?.init?.headers as Record<string, string> | undefined;
  assert.equal(headers?.["X-Wuxing"], undefined);
});

test("POST 带 X-Wuxing 与 JSON 体；错误映射 code/status", async () => {
  const captured: RequestInit[] = [];
  const fetchLike: typeof fetch = async (_input, init) => {
    if (init) captured.push(init);
    return new Response(JSON.stringify({ error: { code: "busy", message: "忙" } }), { status: 409 });
  };
  const client = createRestClient({ baseUrl: "http://x", fetchLike });
  await assert.rejects(
    client.post("/api/v1/workspaces/1/tasks", { text: "hi" }),
    (error: unknown) => {
      assert.ok(error instanceof RestError);
      assert.equal(error.kind, "http");
      assert.equal(error.status, 409);
      assert.equal(error.code, "busy");
      return true;
    },
  );
  const init = captured[0];
  const headers = init?.headers as Record<string, string> | undefined;
  assert.equal(headers?.["X-Wuxing"], "1");
  assert.equal(init?.body, JSON.stringify({ text: "hi" }));
});

test("超时 → timeout 类错误", async () => {
  const fetchLike: typeof fetch = (_input, init) =>
    new Promise((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () => {
        reject(new DOMException("Aborted", "AbortError"));
      });
    });
  const client = createRestClient({ baseUrl: "http://x", fetchLike, timeoutMs: 10 });
  await assert.rejects(client.get("/slow"), (error: unknown) => {
    assert.ok(error instanceof RestError);
    assert.equal(error.kind, "timeout");
    return true;
  });
});
