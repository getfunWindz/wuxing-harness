import { test } from "node:test";
import assert from "node:assert/strict";

import {
  MECHANISM_FIELDS,
  MODEL_FIELDS,
  SETTINGS_SECTIONS,
  controlKind,
  deriveFields,
  fieldSourceKey,
  providerCredentialRef,
  realShapeCredentialRefs,
} from "../src/views/settings/model.ts";
import { DICTS } from "../src/views/i18n.ts";

const SCHEMA = [
  { name: "llm", type: "str", enum: null },
  { name: "router", type: "dict", enum: null },
  { name: "max_parallel_units", type: "int", enum: null },
  { name: "fsc_enabled", type: "bool", enum: null },
  { name: "cache_similar_threshold", type: "float", enum: null },
  { name: "sandbox_enabled", type: "bool", enum: null },
  { name: "not_in_whitelist", type: "str", enum: null },
];

test("分区导航：模型/模式/装配/域提示词/交互/机制/外观/工作区/数据/决策历史/关于（M7 C1/C2 + 双模式批 1 + E2-UI + #2 P1.5/T-5）", () => {
  assert.deepEqual(SETTINGS_SECTIONS.map((s) => s.id),
    ["model", "modes", "assembly", "prompts", "interaction", "mechanism", "appearance", "workspace", "data", "decisions", "about"]);
  assert.ok(SETTINGS_SECTIONS.every((s) => s.titleKey.startsWith("settings.section.")));
});

test("fieldSourceKey：配置来源本地化键（U10——未知回退默认）", () => {
  assert.equal(fieldSourceKey("user"), "settings.field.sourceUser");
  assert.equal(fieldSourceKey("workspace"), "settings.field.sourceWorkspace");
  assert.equal(fieldSourceKey("default"), "settings.field.sourceDefault");
  assert.equal(fieldSourceKey("whatever"), "settings.field.sourceDefault");
});

test("字段白名单：机制 24 项（含沙箱开关/档位/模板 + 权限剖面 + 内容信任 + 黄金期阈值对）；模型 4 项", () => {
  assert.equal(MECHANISM_FIELDS.length, 24);
  assert.ok(MECHANISM_FIELDS.includes("sandbox_enabled"));
  assert.ok(MECHANISM_FIELDS.includes("sandbox_mode"));
  assert.ok(MECHANISM_FIELDS.includes("sandbox_container_template"));
  assert.ok(MECHANISM_FIELDS.includes("permission_profile"));
  assert.ok(MECHANISM_FIELDS.includes("content_trust_sanitize"));
  assert.ok(MECHANISM_FIELDS.includes("fsc_enabled"));
  assert.ok(MECHANISM_FIELDS.includes("context_golden_pct"));
  assert.ok(MECHANISM_FIELDS.includes("context_managed_pct"));
  assert.deepEqual(MODEL_FIELDS, ["llm", "router", "llm_max_retries", "llm_timeout"]);
});

test("控件派生：bool→toggle / int,float→number / enum→select / 复合→composite / 其余 text", () => {
  assert.equal(controlKind("bool", false), "toggle");
  assert.equal(controlKind("int", false), "number");
  assert.equal(controlKind("float", false), "number");
  assert.equal(controlKind("str", true), "select");
  assert.equal(controlKind("dict", false), "composite");
  assert.equal(controlKind("list", false), "composite");
  assert.equal(controlKind("tuple", false), "composite");
  assert.equal(controlKind("str", false), "text");
});

test("deriveFields：白名单顺序 + 生效值与来源 + 未声明字段不渲染", () => {
  const fields = deriveFields("mechanism", SCHEMA, {
    values: { fsc_enabled: true, sandbox_enabled: false, not_in_whitelist: "x" },
    sources: { fsc_enabled: "user" },
  });
  const names = fields.map((f) => f.name);
  assert.deepEqual(names, ["max_parallel_units", "fsc_enabled", "cache_similar_threshold", "sandbox_enabled"]);
  const fsc = fields.find((f) => f.name === "fsc_enabled")!;
  assert.equal(fsc.control, "toggle");
  assert.equal(fsc.value, true);
  assert.equal(fsc.source, "user");
  const sandbox = fields.find((f) => f.name === "sandbox_enabled")!;
  assert.equal(sandbox.value, false);
  assert.equal(sandbox.source, "default");
});

test("deriveFields：模型区 llm 为文本/路由为复合（引用由 T4 选择器接管）", () => {
  const fields = deriveFields("model", SCHEMA, { values: { llm: "deepseek/m1" }, sources: {} });
  assert.deepEqual(fields.map((f) => f.name), ["llm", "router"]);
  assert.equal(fields[0]!.control, "text");
  assert.equal(fields[1]!.control, "composite");
  assert.equal(fields[0]!.value, "deepseek/m1");
});

test("providerCredentialRef：credential_ref 优先；否则 id 大写规范化派生", () => {
  assert.equal(providerCredentialRef("deepseek", { type: "deepseek" }), "DEEPSEEK_API_KEY");
  assert.equal(
    providerCredentialRef("my-deep", { type: "deepseek", credential_ref: "MY_KEY" }),
    "MY_KEY");
  assert.equal(providerCredentialRef("my-deep", {}), "MY_DEEP_API_KEY");
});

test("realShapeCredentialRefs：默认模型（llm）的凭据引用（非供应商专用）", () => {
  // 未配置默认模型 / mock → 无引用（设置提示「默认模型不可用」）
  assert.deepEqual(realShapeCredentialRefs(undefined), []);
  assert.deepEqual(realShapeCredentialRefs({}), []);
  assert.deepEqual(realShapeCredentialRefs({ llm: "mock" }), []);
  // type:model → 类型派生 ref
  assert.deepEqual(realShapeCredentialRefs({ llm: "deepseek:deepseek-flash" }),
    ["DEEPSEEK_API_KEY"]);
  // provider/model（R5-1）→ 供应商条目 credential_ref；缺省派生
  assert.deepEqual(realShapeCredentialRefs({
    llm: "myprov/some-model",
    providers: { myprov: { type: "openai", credential_ref: "MY_KEY" } },
  }), ["MY_KEY"]);
  assert.deepEqual(realShapeCredentialRefs({
    llm: "other/x",
    providers: { other: { type: "openai" } },
  }), ["OTHER_API_KEY"]);
  // 字典 spec：显式 credential_ref / api_key_env 优先；type 兜底
  assert.deepEqual(realShapeCredentialRefs({
    llm: { provider: "p1", credential_ref: "EXPLICIT" },
    providers: { p1: { type: "openai", credential_ref: "P1_KEY" } },
  }), ["P1_KEY", "EXPLICIT"]);
  assert.deepEqual(realShapeCredentialRefs({
    llm: { type: "anthropic", api_key_env: "CLAUDE_KEY" },
  }), ["CLAUDE_KEY"]);
});

test("设置项全量 i18n：模型+机制字段均有 label/desc（zh/en 双语）", () => {
  const names = [...MODEL_FIELDS, ...MECHANISM_FIELDS];
  const missing: string[] = [];
  for (const lang of ["zh", "en"] as const) {
    for (const name of names) {
      for (const suffix of ["label", "desc"]) {
        const key = `settings.field.${name}.${suffix}`;
        const dict = DICTS[lang] as Record<string, string>;
        if (!dict[key] || dict[key].trim() === "") missing.push(`${lang}:${key}`);
      }
    }
  }
  assert.deepEqual(missing, []);
});

test("deriveFields：标签走 i18n（非参数名原文）", () => {
  const schema = [
    { name: "max_parallel_units", type: "int", enum: null, default: 8 },
  ] as const;
  const fields = deriveFields("mechanism", [...schema], { values: { max_parallel_units: 8 }, sources: {} });
  assert.equal(fields.length, 1);
  assert.notEqual(fields[0]!.label, "max_parallel_units", "标签应为中文而非参数名");
  assert.ok(fields[0]!.label.length > 0);
});
