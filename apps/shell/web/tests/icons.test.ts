import { test } from "node:test";
import assert from "node:assert/strict";

import { ICON_NAMES, ICON_REGISTRY } from "../src/views/icons.ts";

test("图标注册表 ≥31 枚且路径非空（外观复现 A12）", () => {
  assert.ok(ICON_NAMES.length >= 31, `icons=${ICON_NAMES.length}`);
  for (const [name, paths] of Object.entries(ICON_REGISTRY)) {
    assert.ok(paths.length >= 1, `${name} 无路径`);
    for (const d of paths) {
      assert.ok(d.length > 4, `${name} 路径过短：${d}`);
    }
  }
});

test("图标为纯 path 数据（无 emoji/无内联 fill）", () => {
  for (const [name, paths] of Object.entries(ICON_REGISTRY)) {
    for (const d of paths) {
      // eslint-disable-next-line no-control-regex
      assert.ok(/^[\x20-\x7E]+$/.test(d), `${name} 含非 ASCII 字符`);
    }
  }
});
