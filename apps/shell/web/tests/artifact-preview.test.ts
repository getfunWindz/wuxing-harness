import { test } from "node:test";
import assert from "node:assert/strict";

import type { ResultDto } from "../src/protocol/generated.ts";
import {
  ARTIFACT_PREVIEW_BYTES,
  artifactPreviewMode,
  deriveArtifactRows,
  truncateArtifactText,
} from "../src/views/view-model.ts";

test("artifactPreviewMode：扩展名分流（大小写不敏感；未知/无扩展 = binary 兜底）", () => {
  assert.equal(artifactPreviewMode("docs/报告.md"), "markdown");
  assert.equal(artifactPreviewMode("README.MARKDOWN"), "markdown");
  assert.equal(artifactPreviewMode("src/main.py"), "text");
  assert.equal(artifactPreviewMode("a/b.txt"), "text");
  assert.equal(artifactPreviewMode("data.json"), "text");
  assert.equal(artifactPreviewMode("index.html"), "text"); // HTML 只作纯文本渲染（不解释执行）
  assert.equal(artifactPreviewMode("image.png"), "binary");
  assert.equal(artifactPreviewMode("archive.tar.gz"), "binary");
  assert.equal(artifactPreviewMode("Makefile"), "binary");
  assert.equal(artifactPreviewMode(""), "binary");
});

test("truncateArtifactText：未超限原样；超限按字节截断并标记", () => {
  assert.deepEqual(truncateArtifactText("hello", 1024),
    { text: "hello", truncated: false });
  assert.deepEqual(truncateArtifactText("", 1024),
    { text: "", truncated: false });

  const big = truncateArtifactText("a".repeat(2048), 1024);
  assert.equal(big.truncated, true);
  assert.equal(big.text.length, 1024);

  // 多字节：上限是 UTF-8 字节而不是字符数（中文 3 字节/字）
  const cjk = truncateArtifactText("中".repeat(1000), 300);
  assert.equal(cjk.truncated, true);
  assert.equal(new TextEncoder().encode(cjk.text).length, 300);
  assert.equal(cjk.text, "中".repeat(100));

  // 代理对不得截出半个字符（不得产生 U+FFFD）
  const emoji = truncateArtifactText("😀".repeat(100), 6);
  assert.equal(emoji.truncated, true);
  assert.ok(new TextEncoder().encode(emoji.text).length <= 6);
  assert.equal(emoji.text.includes("\uFFFD"), false);

  const tooTight = truncateArtifactText("😀", 3); // 一个 emoji 也要 4 字节
  assert.equal(tooTight.truncated, true);
  assert.equal(tooTight.text, "");
});

test("ARTIFACT_PREVIEW_BYTES：v1 大小上限 = 512 KiB（W1-4 裁定）", () => {
  assert.equal(ARTIFACT_PREVIEW_BYTES, 512 * 1024);
});

test("deriveArtifactRows：mtime 透传；历史载荷缺 mtime → 0（兼容）", () => {
  const result = {
    status: "done", report: "", metrics: {},
    artifacts: [{ path: "a.md", kind: "md", mtime: 1735689600.5 },
                { path: "b.py", kind: "code" }],
  } as unknown as ResultDto;
  assert.deepEqual(deriveArtifactRows(result), [
    { path: "a.md", kind: "md", mtime: 1735689600.5 },
    { path: "b.py", kind: "code", mtime: 0 },
  ]);
  assert.deepEqual(deriveArtifactRows(null), []);
});
