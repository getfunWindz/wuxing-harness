import { test } from "node:test";
import assert from "node:assert/strict";

import {
  createSseClient,
  type SseConnectOptions,
} from "../src/runtime/connection/sse.ts";

test("epoch 变更：lastSeq 归零（服务重启后新事件不被去重丢弃）", async () => {
  const connects: SseConnectOptions[] = [];
  const events: number[] = [];
  const client = createSseClient({
    baseUrl: "http://x",
    reconnectDelayMs: 5,
    onStatus: () => {},
    onEvent: (envelope) => { events.push((envelope as { seq: number }).seq); },
    onControl: () => {},
    transport: (opts) => {
      connects.push(opts);
      return { close() {} };
    },
  });
  client.start();
  connects[0]?.onOpen();
  connects[0]?.onMessage(JSON.stringify({ epoch: "E1", last_seq: 100, gap: false }), "hello");
  connects[0]?.onMessage(JSON.stringify({ seq: 101 }));
  assert.equal(client.lastSeq(), 101);

  connects[0]?.onError();
  await new Promise((resolve) => setTimeout(resolve, 30));
  assert.equal(connects.length, 2, "错误后应重连");

  connects[1]?.onOpen();
  connects[1]?.onMessage(JSON.stringify({ epoch: "E2", last_seq: 3, gap: false }), "hello");
  connects[1]?.onMessage(JSON.stringify({ seq: 1 }));
  assert.equal(client.lastSeq(), 1, "新 epoch 的低 seq 应被采纳");
  assert.deepEqual(events, [101, 1]);
  client.stop();
});
