/** TDD：设计卡「采用推荐」可加可退（纯函数——行级精确匹配）。 */
import { test } from "node:test";
import assert from "node:assert/strict";

import {
  hasRecommendLine,
  recommendLine,
  toggleRecommendText,
} from "../src/views/view-model.ts";

const LINE = recommendLine("回答：", "Windows 桌面");

test("recommendLine：前缀拼接", () => {
  assert.equal(LINE, "回答：Windows 桌面");
});

test("hasRecommendLine：整行匹配（首尾空白容错）", () => {
  assert.equal(hasRecommendLine("", LINE), false);
  assert.equal(hasRecommendLine("草稿", LINE), false);
  assert.equal(hasRecommendLine("草稿\n回答：Windows 桌面", LINE), true);
  assert.equal(hasRecommendLine("草稿\n  回答：Windows 桌面  ", LINE), true);
  assert.equal(hasRecommendLine("回答：Windows 桌面（补充）", LINE), false);
});

test("toggleRecommendText：空文本 → 追加行", () => {
  assert.equal(toggleRecommendText("", LINE), LINE);
});

test("toggleRecommendText：已有文本 → 末尾追加（不动原文）", () => {
  assert.equal(toggleRecommendText("我的草稿", LINE), `我的草稿\n${LINE}`);
  // 尾随空白先 trim（不产生双空行）
  assert.equal(toggleRecommendText("我的草稿\n\n", LINE), `我的草稿\n${LINE}`);
});

test("toggleRecommendText：已含该行 → 精确移除（其余文本一字不动）", () => {
  const text = `第一行\n${LINE}\n第三行`;
  assert.equal(toggleRecommendText(text, LINE), "第一行\n第三行");
  // 移除后 trimEnd（不留尾随空行）
  assert.equal(toggleRecommendText(`第一行\n${LINE}`, LINE), "第一行");
  assert.equal(toggleRecommendText(LINE, LINE), "");
});

test("toggleRecommendText：重复行 → 每次仅移除首个（残留则仍算已采用）", () => {
  const dup = `${LINE}\n${LINE}`;
  const once = toggleRecommendText(dup, LINE);
  assert.equal(once, LINE);
  assert.equal(hasRecommendLine(once, LINE), true);
  assert.equal(toggleRecommendText(once, LINE), "");
});
