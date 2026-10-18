import { test } from "node:test";
import assert from "node:assert/strict";

import { autoRetryKey, failureLabelKey } from "../src/views/view-model.ts";

test("failureLabelKey：失败分类 → i18n 键（未知/空回落空串）", () => {
  assert.equal(failureLabelKey("provider"), "failure.provider");
  assert.equal(failureLabelKey("budget"), "failure.budget");
  assert.equal(failureLabelKey("stalled"), "failure.stalled");
  assert.equal(failureLabelKey(""), "");
  assert.equal(failureLabelKey("unknown"), "");
});

test("autoRetryKey：自动恢复类型 → i18n 键", () => {
  assert.equal(autoRetryKey("retry"), "failure.autoRetry");
  assert.equal(autoRetryKey("fallback"), "failure.fallback");
  assert.equal(autoRetryKey(""), "");
});
