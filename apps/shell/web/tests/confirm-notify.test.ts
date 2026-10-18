import { test } from "node:test";
import assert from "node:assert/strict";

import { createConfirmNotify, notifyBody, notifyCandidates }
  from "../src/views/confirm-notify.ts";
import { setLang } from "../src/views/i18n.ts";

const card = (id: string, label = `步骤 ${id}`) => ({ id, label });

test("notifyCandidates：守卫矩阵（enabled/hidden/permission/已通知）", () => {
  setLang("zh");
  const cards = [card("A"), card("B")];
  const base = { cards, notified: new Set<string>(), hidden: true,
                 enabled: true, permission: "granted" };
  assert.deepEqual(notifyCandidates(base).map((c) => c.id), ["A", "B"]);
  assert.deepEqual(notifyCandidates({ ...base, enabled: false }), []);
  assert.deepEqual(notifyCandidates({ ...base, hidden: false }), []);
  assert.deepEqual(notifyCandidates({ ...base, permission: "denied" }), []);
  assert.deepEqual(notifyCandidates({ ...base, permission: "default" }), []);
  assert.deepEqual(notifyCandidates({ ...base, permission: "unsupported" }), []);
  assert.deepEqual(
    notifyCandidates({ ...base, notified: new Set(["A"]) }).map((c) => c.id),
    ["B"]);
  assert.deepEqual(notifyCandidates({ ...base, cards: [] }), []);
});

test("notifyBody：单条截断 80 字符 / 多条「首条 等 N 个」", () => {
  setLang("zh");
  assert.equal(notifyBody([card("A", "short")]), "short");
  const clipped = notifyBody([card("A", "x".repeat(120))]);
  assert.equal(clipped.length, 80);
  assert.ok(clipped.endsWith("…"));
  const multi = notifyBody([card("A", "第一条"), card("B"), card("C")]);
  assert.ok(multi.includes("第一条"));
  assert.ok(multi.includes("2"));
});

test("createConfirmNotify：首发/去重/新挂起再发/解决后再发", () => {
  setLang("zh");
  const sent: { title: string; body: string }[] = [];
  let cards = [card("A"), card("B")];
  const notifier = createConfirmNotify({
    cards: () => cards,
    enabled: () => true,
    permission: () => "granted",
    isHidden: () => true,
    create: (title, body) => { sent.push({ title, body }); },
  });
  notifier.sync();
  assert.equal(sent.length, 1);
  assert.ok(sent[0]!.title.includes("2"));
  notifier.sync();
  assert.equal(sent.length, 1, "重复 sync 不重发");
  cards = [card("A"), card("B"), card("C")];
  notifier.sync();
  assert.equal(sent.length, 2, "新挂起 → 再发");
  assert.ok(sent[1]!.title.includes("1"), "本次仅未通知的 1 条");
  cards = [];
  notifier.sync();                       // 全部解决 → 账本剪枝
  cards = [card("A")];
  notifier.sync();
  assert.equal(sent.length, 3, "同 id 再现可再发");
  notifier.sync();
  assert.equal(sent.length, 3);
});

test("createConfirmNotify：可见/关闭/权限不足时静默", () => {
  const sent: unknown[] = [];
  const mk = (over: Partial<{
    enabled: boolean; permission: string; hidden: boolean;
  }>) => createConfirmNotify({
    cards: () => [card("A")],
    enabled: () => over.enabled ?? true,
    permission: () => over.permission ?? "granted",
    isHidden: () => over.hidden ?? true,
    create: (title, body) => { sent.push([title, body]); },
  });
  mk({ hidden: false }).sync();
  mk({ enabled: false }).sync();
  mk({ permission: "denied" }).sync();
  mk({ permission: "unsupported" }).sync();
  assert.equal(sent.length, 0);
});
