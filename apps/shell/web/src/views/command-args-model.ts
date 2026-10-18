/** E2-UI：命令参数表单模型（纯函数——逐字段输入；UI 只做接线）。
    —— 用户裁决 Q1：不出现「整段 JSON 交给用户写」；字段来自命令声明的 args。 */
import type { ExtCommandArgDto } from "../protocol/generated.ts";

/** 草稿值：bool → 勾选态；其余 → 输入框字符串。 */
export type ArgDraft = Record<string, string | boolean>;

/** 行内错误码（视图层映射 i18n 文案）。 */
export type ArgError = "required" | "type";

export interface CollectResult {
  readonly values: Record<string, unknown>;
  readonly errors: Record<string, ArgError>;
}

/** 初始草稿：默认值预填（bool→勾选态；其余→字符串）。 */
export function initialArgDraft(schema: readonly ExtCommandArgDto[]): ArgDraft {
  const out: ArgDraft = {};
  for (const arg of schema) {
    if (arg.type === "bool") {
      out[arg.name] = arg.default === true;
    } else {
      out[arg.name] = arg.default === null || arg.default === undefined
        ? "" : String(arg.default);
    }
  }
  return out;
}

/** 收集提交值：类型转换 + 校验；in = 草稿 + 错误集（有错不提交）。 */
export function collectArgValues(
  schema: readonly ExtCommandArgDto[],
  draft: ArgDraft,
): CollectResult {
  const values: Record<string, unknown> = {};
  const errors: Record<string, ArgError> = {};
  for (const arg of schema) {
    const raw = draft[arg.name];
    if (arg.type === "bool") {
      values[arg.name] = raw === true;   // bool 恒收集（勾选态即值）
      continue;
    }
    const text = typeof raw === "string" ? raw : String(raw ?? "");
    if (text.trim() === "") {
      if (arg.required) errors[arg.name] = "required";
      continue;   // 可选空值省略（服务端按声明补默认）
    }
    if (arg.type === "int") {
      if (!/^-?\d+$/.test(text.trim())) { errors[arg.name] = "type"; continue; }
      values[arg.name] = parseInt(text.trim(), 10);
    } else if (arg.type === "float") {
      const n = Number(text.trim());
      if (!Number.isFinite(n)) { errors[arg.name] = "type"; continue; }
      values[arg.name] = n;
    } else {
      values[arg.name] = text;   // str：原文（仅必填判定用 trim）
    }
  }
  return { values, errors };
}
