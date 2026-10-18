/** TDD · O2-2 §11.5-①：partition 命名 + 身份注册表读写（fail-closed）。
 *
 * 同其它 desktop 测试：经编译产物（dist/*.js，CJS）驱动；`npm test` 前置构建。
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const {
  partitionFor,
  readRegistry,
  upsertRegistry,
  removeRegistry,
  registryPath,
} = require("../dist/browser-identity.js") as
  typeof import("../src/browser-identity.ts");

const IDENT = {
  key: "wuxing-browser-abc",
  mode: "memory" as const,
  workspace: "C:/p",
};

test("partitionFor：memory 裸名 / persist 前缀", () => {
  assert.equal(partitionFor({ ...IDENT, mode: "memory" }), "wuxing-browser-abc");
  assert.equal(partitionFor({ ...IDENT, mode: "persist" }),
    "persist:wuxing-browser-abc");
});

test("注册表：upsert 保留 first_used/刷新 last_used；remove；损坏 fail-closed", () => {
  const file = path.join(mkdtempSync(path.join(tmpdir(), "wuxing-id-")),
    "reg.json");
  assert.deepEqual(readRegistry(file), []);
  upsertRegistry({ ...IDENT, mode: "persist" }, "2026-10-13T00:00:00Z", file);
  upsertRegistry({ ...IDENT, mode: "persist" }, "2026-10-13T01:00:00Z", file);
  const rows = readRegistry(file);
  assert.equal(rows.length, 1);
  assert.equal(rows[0].first_used_at, "2026-10-13T00:00:00Z");
  assert.equal(rows[0].last_used_at, "2026-10-13T01:00:00Z");
  assert.equal(rows[0].workspace, "C:/p");
  assert.equal(removeRegistry(IDENT.key, file), true);
  assert.deepEqual(readRegistry(file), []);
  assert.equal(removeRegistry(IDENT.key, file), false);
  writeFileSync(file, "{bad", "utf-8");
  assert.deepEqual(readRegistry(file), []);
});

test("registryPath：默认 ~/.wuxing/browser_identities.json", () => {
  assert.ok(registryPath().endsWith(path.join(".wuxing",
    "browser_identities.json")));
});
