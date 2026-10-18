/** 设置视图模型（P2-S3 纯函数层——可单测；DOM 装配由视图/E2E 覆盖）。 */
import type { ConfigDto } from "../../protocol/generated.ts";
import { t } from "../i18n.ts";

/** 字段标签（i18n 优先；缺键回退参数名——B5 全量中文化）。 */
export function fieldLabel(name: string): string {
  const key = `settings.field.${name}.label`;
  const label = t(key);
  return label === key ? name : label;
}

/** 配置来源 → 本地化键（U10；未知来源回退「默认」）。 */
export function fieldSourceKey(source: string): string {
  if (source === "user") return "settings.field.sourceUser";
  if (source === "workspace") return "settings.field.sourceWorkspace";
  return "settings.field.sourceDefault";
}

/** 字段说明（i18n；缺键 → 空串——不造假）。 */
export function fieldDesc(name: string): string {
  const key = `settings.field.${name}.desc`;
  const desc = t(key);
  return desc === key ? "" : desc;
}

export interface SettingsSection {
  readonly id: string;
  readonly titleKey: string;
}

/** 分区导航（模型与供应商 + 机制调优 + 外观与语言）。 */
export const SETTINGS_SECTIONS: readonly SettingsSection[] = [
  { id: "model", titleKey: "settings.section.model" },
  { id: "modes", titleKey: "settings.section.modes" },
  { id: "assembly", titleKey: "settings.section.assembly" },
  { id: "prompts", titleKey: "settings.section.prompts" },
  { id: "interaction", titleKey: "settings.section.interaction" },
  { id: "mechanism", titleKey: "settings.section.mechanism" },
  { id: "appearance", titleKey: "settings.section.appearance" },
  { id: "workspace", titleKey: "settings.section.workspace" },
  { id: "data", titleKey: "settings.section.data" },
  { id: "decisions", titleKey: "settings.section.decisions" },
  { id: "about", titleKey: "settings.section.about" },
];

/** 模型区字段（默认模型 = provider/model 引用；域路由 = 同清单选择）。 */
export const MODEL_FIELDS: readonly string[] = [
  "llm", "router", "llm_max_retries", "llm_timeout",
];

/** 机制调优字段白名单（17 项 + 沙箱开关——与旧壳 GROUPS 对齐）。 */
export const MECHANISM_FIELDS: readonly string[] = [
  "max_parallel_units", "max_parallel_tools",
  "tool_concurrency_soft", "tool_concurrency_hard", "tool_throttle_delay_ms",
  "fsc_enabled", "fsc_retention_rounds", "fsc_max_reuse", "fsc_fallback_digest",
  "fsc_audit_ratio", "fsc_switch_ratio", "cache_similar_threshold",
  "use_real_shape", "brain_enabled", "skill_evolution_enabled",
  "progress_heartbeat_enabled", "confirm_threshold", "sandbox_enabled",
  "sandbox_mode", "sandbox_container_template",
  "permission_profile", "content_trust_sanitize",
  "context_golden_pct", "context_managed_pct",
];

/** 模式分区字段（双模式批 1——默认模式 / 选择器显隐 / 纯净自动确认）。 */
export const MODES_FIELDS: readonly string[] = [
  "mode_default", "mode_picker_enabled", "minimal_pure_auto_confirm",
];

export type ControlKind = "toggle" | "number" | "text" | "select" | "composite";

/** 字段类型 → 控件种类（schema 驱动渲染的唯一裁决点）。 */
export function controlKind(type: string, hasEnum: boolean): ControlKind {
  if (type === "bool") return "toggle";
  if (type === "int" || type === "float") return "number";
  if (hasEnum) return "select";
  if (type === "dict" || type === "list" || type === "tuple") return "composite";
  return "text";
}

export interface FieldSpecLike {
  readonly name: string;
  readonly type: string;
  readonly enum?: readonly string[] | null;
  readonly default?: unknown;
}

export interface FieldView {
  readonly name: string;
  readonly label: string; // 暂用字段名（i18n 字典迁移随 P2 后续批）
  readonly type: string;
  readonly control: ControlKind;
  readonly value: unknown;
  readonly defaultValue: unknown;
  readonly source: string; // default | user | workspace
  /** 枚举字段的合法值集（select 控件用；双模式 mode_default 为首个使用者）。 */
  readonly options?: readonly string[];
}

export interface ProviderEntryLike {
  readonly type?: string;
  readonly credential_ref?: string;
}

/** 供应商凭据引用派生（与 view.ts refOf 同规则——单源）。
    credential_ref 优先；否则 `${id 大写规范化}_API_KEY`。 */
export function providerCredentialRef(id: string, entry: ProviderEntryLike): string {
  return entry.credential_ref || `${id.toUpperCase().replace(/[^A-Z0-9]+/g, "_")}_API_KEY`;
}

/** 默认模型的凭据引用派生（2026-09-19：形状化用默认模型——非供应商专用）。

    支持 spec 形状："provider/model"（R5-1）· "type:model" · 字典
    {provider|type, credential_ref?/api_key_env?}；无可用引用 → 空数组
    （调用方提示「默认模型不可用」）。 */
export function realShapeCredentialRefs(values: Record<string, unknown> | null | undefined): readonly string[] {
  const refs: string[] = [];
  const push = (ref: unknown): void => {
    if (typeof ref === "string" && ref.trim() !== "" && !refs.includes(ref)) refs.push(ref);
  };
  const providers = (values?.providers as Record<string, ProviderEntryLike> | undefined) ?? {};
  const derived = (typeName: string): string =>
    `${typeName.toUpperCase().replace(/[^A-Z0-9]+/g, "_")}_API_KEY`;
  const spec = values?.llm;
  if (typeof spec === "string") {
    const text = spec.trim();
    if (text === "" || text === "mock") return [];
    if (text.includes("/")) {
      const pid = text.split("/")[0] ?? "";
      const entry = providers[pid];
      if (entry) push(providerCredentialRef(pid, entry));
      else if (entry === undefined && pid !== "") push(derived(pid));
    } else if (text.includes(":")) {
      push(derived(text.split(":")[0] ?? ""));
    }
    return refs;
  }
  if (spec && typeof spec === "object") {
    const s = spec as { provider?: unknown; type?: unknown; credential_ref?: unknown; api_key_env?: unknown };
    const pid = typeof s.provider === "string" ? s.provider : "";
    const entry = pid !== "" ? providers[pid] : undefined;
    if (entry) push(providerCredentialRef(pid, entry));
    push(s.credential_ref);
    push(s.api_key_env);
    if (refs.length === 0 && typeof s.type === "string" && s.type !== "mock") push(derived(s.type));
  }
  return refs;
}

/** 分区字段视图：白名单顺序 + schema 声明取类型 + 生效值与来源。 */
export function deriveFields(
  sectionId: string,
  schema: readonly FieldSpecLike[],
  config: Pick<ConfigDto, "values" | "sources">,
): FieldView[] {
  const names = sectionId === "model"
    ? MODEL_FIELDS
    : sectionId === "mechanism"
      ? MECHANISM_FIELDS
      : sectionId === "modes"
        ? MODES_FIELDS
        : [];
  const byName = new Map(schema.map((spec) => [spec.name, spec]));
  const out: FieldView[] = [];
  for (const name of names) {
    const spec = byName.get(name);
    if (!spec) continue; // schema 未声明 → 不渲染（防漂移）
    const source = config.sources[name];
    const hasEnum = Array.isArray(spec.enum) && spec.enum.length > 0;
    out.push({
      name,
      label: fieldLabel(name),
      type: spec.type,
      control: controlKind(spec.type, hasEnum),
      value: config.values[name],
      defaultValue: spec.default,
      source: typeof source === "string" ? source : "default",
      ...(hasEnum ? { options: spec.enum } : {}),
    });
  }
  return out;
}
