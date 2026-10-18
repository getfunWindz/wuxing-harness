// E2-1（B5）：技能调用策略壳侧纯逻辑测试。
// 设计权威：docs/WUXING_技能专项设计_2026-10-03.md §3。
import { test } from "node:test";
import assert from "node:assert/strict";
import { skillContentBlock, userSelectableSkills } from "../src/components/skill-picker.ts";

test("userSelectableSkills：停用与仅模型技能不出现在选择器", () => {
  const rows: Array<{ name: string; description: string; enabled?: boolean;
                      user_invocable?: boolean }> = [
    { name: "a", description: "", enabled: true, user_invocable: true },
    { name: "b", description: "", enabled: false, user_invocable: true },
    { name: "c", description: "", enabled: true, user_invocable: false },
    { name: "d", description: "" }, // 缺字段 → 默认可用
  ];
  assert.deepEqual(userSelectableSkills(rows).map((s) => s.name), ["a", "d"]);
});

test("skillContentBlock：剥离 frontmatter 并包装技能名", () => {
  const md = "---\nname: x\ndescription: d\n---\n## 用法\n步骤。";
  assert.equal(skillContentBlock("x", md), "【技能：x】\n## 用法\n步骤。");
});
