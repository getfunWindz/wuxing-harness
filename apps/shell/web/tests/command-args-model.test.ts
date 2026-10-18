/** E2-UI：命令参数表单模型（纯函数——逐字段输入；不出现 JSON 裸输入）。 */
import { test } from "node:test";
import assert from "node:assert/strict";

import {
  collectArgValues,
  initialArgDraft,
} from "../src/views/command-args-model.ts";
import type { ExtCommandArgDto } from "../src/protocol/generated.ts";

const SCHEMA: ExtCommandArgDto[] = [
  { name: "text", label: "文本", type: "str", required: true, default: null },
  { name: "count", label: "次数", type: "int", required: false, default: 3 },
  { name: "ratio", label: "比例", type: "float", required: false, default: null },
  { name: "verbose", label: "详细", type: "bool", required: false, default: true },
];

test("initialArgDraft：默认值预填（bool→勾选态；数值→字符串草稿）", () => {
  const draft = initialArgDraft(SCHEMA);
  assert.equal(draft.text, "");
  assert.equal(draft.count, "3");
  assert.equal(draft.ratio, "");
  assert.equal(draft.verbose, true);
});

test("collectArgValues：逐字段类型转换 + 必填/数值校验", () => {
  // 合法：str/int 显式 + float 空（可选省略）+ bool
  const ok = collectArgValues(SCHEMA, {
    text: "你好", count: "5", ratio: "", verbose: false,
  });
  assert.deepEqual(ok.errors, {});
  assert.deepEqual(ok.values, { text: "你好", count: 5, verbose: false });
  // 必填缺失
  const miss = collectArgValues(SCHEMA, { text: "  ", count: "5", ratio: "", verbose: true });
  assert.deepEqual(miss.errors, { text: "required" });
  // 数值非法
  const bad = collectArgValues(SCHEMA, { text: "x", count: "5.5a", ratio: "1.5", verbose: true });
  assert.deepEqual(bad.errors, { count: "type" });
  // float 合法
  const flt = collectArgValues(SCHEMA, { text: "x", count: "", ratio: "-0.5", verbose: true });
  assert.deepEqual(flt.errors, {});
  assert.equal(flt.values.ratio, -0.5);
  assert.equal("count" in flt.values, false);   // 可选空值省略（服务端补默认）
});

test("collectArgValues：默认值兜底（草稿为空且可选 → 省略；bool 恒收集）", () => {
  const out = collectArgValues(SCHEMA, initialArgDraft(SCHEMA));
  // count 默认 3 已在草稿里；ratio 空且无默认 → 省略
  assert.deepEqual(out.values, { count: 3, verbose: true });
  assert.equal("ratio" in out.values, false);
});
