import { test } from "node:test";
import assert from "node:assert/strict";

import {
  createSseClient,
  parseSseChunk,
  type SseConnectOptions,
} from "../src/runtime/connection/sse.ts";

test("parseSseChunk：id/event/data、多行 data、注释心跳、CRLF、半帧", () => {
  const first = parseSseChunk("id: 3\ndata: {\"seq\":3}\n\n: ping\n\ndata: a\ndata: b\n\n");
  assert.equal(first.frames.length, 2);
  assert.equal(first.frames[0]?.id, "3");
  assert.equal(first.frames[0]?.data, "{\"seq\":3}");
  assert.equal(first.frames[1]?.data, "a\nb");
  assert.equal(first.rest, "");

  const crlf = parseSseChunk("event: hello\r\ndata: {}\r\n\r\n");
  assert.equal(crlf.frames[0]?.event, "hello");

  const partial = parseSseChunk("id: 9\ndata: {\"seq\"");
  assert.equal(partial.frames.length, 0);
  assert.equal(partial.rest, "id: 9\ndata: {\"seq\"");
});

test("客户端：seq 推进、控制帧路由、错误重连（含 since）", async () => {
  const connects: SseConnectOptions[] = [];
  const statuses: string[] = [];
  const events: number[] = [];
  const controls: string[] = [];
  const client = createSseClient({
    baseUrl: "http://x",
    reconnectDelayMs: 5,
    onStatus: (status) => { statuses.push(status); },
    onEvent: (envelope) => { events.push((envelope as { seq: number }).seq); },
    onControl: (frame) => { controls.push(frame.type); },
    transport: (opts) => {
      connects.push(opts);
      return { close() {} };
    },
  });
  client.start();
  assert.equal(connects.length, 1);
  connects[0]?.onOpen();
  connects[0]?.onMessage("{\"seq\": 7}", "hello");
  connects[0]?.onMessage("{\"seq\": 7, \"type\": \"unit_started\"}");
  connects[0]?.onMessage("{\"seq\": 6, \"type\": \"unit_started\"}");
  connects[0]?.onMessage("{\"seq\": 8, \"type\": \"unit_done\"}");
  assert.deepEqual(controls, ["hello"]);
  assert.deepEqual(events, [7, 8]);
  assert.equal(client.lastSeq(), 8);

  connects[0]?.onError();
  await new Promise((resolve) => setTimeout(resolve, 30));
  assert.equal(connects.length, 2);
  assert.match(connects[1]?.url ?? "", /since=8$/);
  client.stop();
  assert.equal(statuses.includes("open"), true);
});

test("reconnectNow：立即断开重连并保持 since（未启动无副作用）", () => {
  const connects: SseConnectOptions[] = [];
  const client = createSseClient({
    baseUrl: "http://x",
    transport: (opts) => { connects.push(opts); return { close() {} }; },
    onEvent() {}, onControl() {}, onStatus() {},
  });
  client.reconnectNow();               // 未启动：无副作用
  assert.equal(connects.length, 0);
  client.start();
  connects[0]?.onOpen();
  connects[0]?.onMessage("{\"seq\": 9, \"type\": \"x\"}");
  client.reconnectNow();
  assert.equal(connects.length, 2);
  assert.match(connects[1]?.url ?? "", /since=9$/);
  client.stop();
});
