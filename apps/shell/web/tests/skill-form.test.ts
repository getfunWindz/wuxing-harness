import { test } from "node:test";
import assert from "node:assert/strict";

import {
  SKILL_DESC_MAX,
  SKILL_NAME_MAX,
  parseSkillFrontmatter,
  skillToolsRows,
  validateSkillDraft,
} from "../src/views/skill-form.ts";

const FM = (name: string, extra = "") =>
  `---\nname: ${name}\ndescription: 演示技能\n${extra}---\n正文内容`;

test("name 规则：kebab-case ≤40；空/大写/空格/路径分隔符拦截", () => {
  const errorsOf = (name: string, content: string) =>
    validateSkillDraft(name, content).errors.join("；");
  assert.ok(errorsOf("", FM("x")).includes("name 必填"));
  assert.ok(errorsOf("Bad-Name", FM("Bad-Name")).includes("kebab-case"));
  assert.ok(errorsOf("bad name", FM("bad name")).includes("kebab-case"));
  assert.ok(errorsOf("-bad", FM("-bad")).includes("kebab-case"));
  assert.ok(errorsOf("a".repeat(SKILL_NAME_MAX + 1), FM("x")).includes("kebab-case"));
  assert.ok(errorsOf("../escape", FM("x")).includes("路径分隔符"));
  assert.ok(errorsOf("a\\b", FM("x")).includes("路径分隔符"));
  assert.ok(errorsOf("..", FM("x")).includes("路径分隔符"));
  // 合法边界：40 字符可用
  const ok40 = "a".repeat(SKILL_NAME_MAX);
  assert.deepEqual(validateSkillDraft(ok40, FM(ok40)).errors, []);
});

test("SKILL.md：必填 + frontmatter 合法（缺/破损/非键值行均拦截）", () => {
  assert.ok(validateSkillDraft("demo", "").errors.join("；").includes("必填"));
  assert.ok(validateSkillDraft("demo", "无 frontmatter").errors
    .join("；").includes("frontmatter"));
  assert.ok(validateSkillDraft("demo", "---\nname: demo\n").errors
    .join("；").includes("frontmatter"));   // 缺闭合 ---
  assert.ok(validateSkillDraft("demo", "---\n不是键值行\ndescription: x\n---\n").errors
    .join("；").includes("frontmatter"));   // 非简单键值
  assert.deepEqual(validateSkillDraft("demo", FM("demo")).errors, []);
});

test("frontmatter 字段：name/description 必填；name 与表单一致；level/超长仅告警", () => {
  const mismatch = validateSkillDraft("demo", FM("other-name"));
  assert.ok(mismatch.errors.join("；").includes("不一致"));
  assert.ok(mismatch.errors.join("；").includes("other-name"));

  const noDesc = validateSkillDraft("demo", "---\nname: demo\n---\n正文");
  assert.ok(noDesc.errors.join("；").includes("description 必填"));

  const longDesc = `---\nname: demo\ndescription: ${"d".repeat(SKILL_DESC_MAX + 1)}\n---\n正文`;
  const longCheck = validateSkillDraft("demo", longDesc);
  assert.deepEqual(longCheck.errors, []);
  assert.ok(longCheck.warnings.join("；").includes("超长"));

  const badLevel = validateSkillDraft("demo", FM("demo", "level: super\n"));
  assert.deepEqual(badLevel.errors, []);
  assert.ok(badLevel.warnings.join("；").includes("level 非法"));
});

test("parseSkillFrontmatter：注释/空行跳过；引号剥除；破损返回 null", () => {
  assert.deepEqual(parseSkillFrontmatter("---\n# 注释\nname: \"demo\"\n---\n"),
    { name: "demo" });
  assert.equal(parseSkillFrontmatter("没有 frontmatter"), null);
  assert.equal(parseSkillFrontmatter("---\nbroken line\n---\n"), null);
});

test("A14 依赖工具行（声明/缺失 → 文本）", () => {
  assert.deepEqual(skillToolsRows({}), { tools: "", missing: "" });
  assert.deepEqual(
    skillToolsRows({ allowed_tools: ["read_file", "bash"] }),
    { tools: "read_file, bash", missing: "" });
  assert.deepEqual(
    skillToolsRows({ allowed_tools: ["read_file"], allowed_tools_missing: ["x_tool"] }),
    { tools: "read_file", missing: "x_tool" });
});
