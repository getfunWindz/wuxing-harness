import { test } from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const CHECKER = path.join(path.dirname(fileURLToPath(import.meta.url)), "check-arch.mjs");

function fixture(files) {
  const root = mkdtempSync(path.join(tmpdir(), "arch-"));
  for (const [rel, content] of Object.entries(files)) {
    const full = path.join(root, rel);
    mkdirSync(path.dirname(full), { recursive: true });
    writeFileSync(full, content);
  }
  return root;
}

function run(root) {
  try {
    const stdout = execFileSync(process.execPath, [CHECKER, root], { encoding: "utf8" });
    return { code: 0, output: stdout };
  } catch (error) {
    return { code: error.status ?? 1, output: `${error.stdout ?? ""}${error.stderr ?? ""}` };
  }
}

test("干净代码通过", () => {
  const root = fixture({
    "web/src/runtime/services/a.ts": "export const a = 1;\n",
  });
  const result = run(root);
  assert.equal(result.code, 0);
  assert.match(result.output, /检查通过/);
});

test("runtime 导入 UI 层被拦截", () => {
  const root = fixture({
    "web/src/runtime/services/bad.ts": 'import { h } from "../../render/dom.ts";\nexport const b = h;\n',
  });
  const result = run(root);
  assert.equal(result.code, 1);
  assert.match(result.output, /runtime-no-ui/);
});

test("runtime 触碰 DOM 被拦截；connection 例外", () => {
  const root = fixture({
    "web/src/runtime/services/bad.ts": "export const t = document.title;\n",
    "web/src/runtime/connection/ok.ts": 'export const f = () => fetch("/x");\n',
  });
  const result = run(root);
  assert.equal(result.code, 1);
  assert.match(result.output, /runtime-no-dom/);
  assert.doesNotMatch(result.output, /connection\/ok\.ts/);
});

test("静默吞错被拦截（注释中的示例不误伤）", () => {
  const bad = fixture({
    "web/src/services/bad.ts": "export const p = doThing().catch(() => null);\n",
  });
  assert.equal(run(bad).code, 1);
  const commented = fixture({
    "web/src/services/ok.ts": "// 反例：.catch(() => null) 是禁用的\n// catch 空块也不允许\nexport const ok = 1;\n",
  });
  assert.equal(run(commented).code, 0);
});

test("折叠动画必须单源令牌（CSS）", () => {
  const bad = fixture({
    "web/static/theme/bad.css": ".x { transition: grid-template-rows 300ms ease; }\n",
  });
  const r = run(bad);
  assert.equal(r.code, 1);
  assert.match(r.output, /fold-motion-token/);

  const bad2 = fixture({
    "web/static/theme/bad2.css": ".y { transition: max-height 200ms ease; }\n",
  });
  const r2 = run(bad2);
  assert.equal(r2.code, 1);
  assert.match(r2.output, /no-height-collapse/);

  const ok = fixture({
    "web/static/theme/ok.css": ".z { transition: grid-template-rows var(--motion-structural); }\n",
  });
  assert.equal(run(ok).code, 0);
});
