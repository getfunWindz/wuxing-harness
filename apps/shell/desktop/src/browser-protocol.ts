/** 内置浏览器控制通道 · 协议纯函数（O2-2 P1；零 Electron 依赖——可单测）。
 *
 * 协议版本：4。命令白名单与 envelope 形状是本文件唯一事实来源；
 * Python 客户端（wuxing/browser_channel.py docstring）与之对拍。
 * v2（O2-2 §11.5-①）：identity 参数 + identity_clear（页面命令缺身份 fail-closed）。
 * v3（O2-2 §11.5-②）：close 必带目标身份；新增 views（视图清单）；每视图队列分片。
 * v4（O2-2 §11.5-③）：mode 第三值 storage-state + identity state_path（登录态档）。
 */
import { createHash, timingSafeEqual } from "node:crypto";

export const PROTOCOL_VERSION = "4";
export const MAX_BODY_BYTES = 64 * 1024;

/** 控制通道默认主机：与壳服务 127.0.0.60 相邻的专用回环别名（用户定案 2026-10-07）。
 * ——避免与通用 127.0.0.1 上大量本地服务混淆；127.0.0.0/8 全域回环，无需系统配置。 */
export const DEFAULT_BROWSER_HOST = "127.0.0.61";

export const COMMANDS = [
  "status",
  "open",
  "snapshot",
  "click",
  "type",
  "wait",
  "evaluate",
  "screenshot",
  "close",
  "identity_clear",
  "views",
] as const;
export type BrowserCommand = (typeof COMMANDS)[number];

export interface CommandRequest {
  cmd: BrowserCommand;
  args: Record<string, unknown>;
}

export type ParseResult =
  | { ok: true; request: CommandRequest }
  | { ok: false; code: string; message: string };

function sha256(value: string): Buffer {
  return createHash("sha256").update(value, "utf8").digest();
}

/** 恒时 token 比较（sha256 归一长度——防长度侧信道）。 */
export function checkToken(
  authHeader: string | undefined,
  token: string,
): boolean {
  const expected = token.trim();
  if (expected === "") return false;
  const raw = (authHeader ?? "").trim();
  const prefix = "bearer ";
  const presented = raw.toLowerCase().startsWith(prefix)
    ? raw.slice(prefix.length).trim()
    : "";
  if (presented === "") return false;
  return timingSafeEqual(sha256(presented), sha256(expected));
}

export function parseRequest(raw: string): ParseResult {
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    return { ok: false, code: "bad-json", message: "请求体不是合法 JSON" };
  }
  if (typeof data !== "object" || data === null || Array.isArray(data)) {
    return { ok: false, code: "bad-shape", message: "请求体必须是对象" };
  }
  const obj = data as Record<string, unknown>;
  const cmd = typeof obj.cmd === "string" ? obj.cmd : "";
  if (!(COMMANDS as readonly string[]).includes(cmd)) {
    return {
      ok: false,
      code: "unknown-command",
      message: `未知命令：${cmd || "(empty)"}`,
    };
  }
  const rawArgs = obj.args;
  const args = rawArgs === undefined ? {} : rawArgs;
  if (typeof args !== "object" || args === null || Array.isArray(args)) {
    return { ok: false, code: "bad-args", message: "args 必须是对象" };
  }
  return {
    ok: true,
    request: {
      cmd: cmd as BrowserCommand,
      args: args as Record<string, unknown>,
    },
  };
}

export function validateUrl(
  raw: unknown,
): { ok: true; url: string } | { ok: false; code: string; message: string } {
  const value = typeof raw === "string" ? raw.trim() : "";
  if (value === "") {
    return { ok: false, code: "bad-url", message: "url 不能为空" };
  }
  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    return { ok: false, code: "bad-url", message: `url 非法：${value}` };
  }
  const scheme = parsed.protocol.replace(/:$/, "").toLowerCase();
  if (scheme !== "http" && scheme !== "https") {
    return {
      ok: false,
      code: "bad-scheme",
      message: `仅允许 http/https：${scheme || "(none)"}`,
    };
  }
  return { ok: true, url: parsed.toString() };
}

export function okEnvelope(data: unknown): string {
  return JSON.stringify({ ok: true, data });
}

export function failEnvelope(code: string, message: string): string {
  return JSON.stringify({ ok: false, error: { code, message } });
}

// ---- P2：click/type/wait 参数校验（处理侧从严——缺/多/越界 loud 拒绝） ----

export type ArgsResult =
  | { ok: true; args: Record<string, unknown> }
  | { ok: false; code: string; message: string };

function badArgs(
  message: string,
): { ok: false; code: string; message: string } {
  return { ok: false, code: "bad-args", message };
}

/** ref|selector 恰一（空串/空白视为缺）。 */
function pickTarget(
  args: Record<string, unknown>,
  what: string,
):
  | { ok: true; value: { ref?: string; selector?: string } }
  | { ok: false; code: string; message: string } {
  const ref = typeof args.ref === "string" ? args.ref.trim() : "";
  const selector =
    typeof args.selector === "string" ? args.selector.trim() : "";
  if (ref === "" && selector === "") {
    return badArgs(`${what} 需要 ref 或 selector（恰一）`);
  }
  if (ref !== "" && selector !== "") {
    return badArgs("ref 与 selector 不能同时提供（恰一）");
  }
  return { ok: true, value: ref !== "" ? { ref } : { selector } };
}

export function validateClickArgs(args: Record<string, unknown>): ArgsResult {
  const t = pickTarget(args, "click");
  if (!t.ok) return t;
  return { ok: true, args: t.value };
}

export function validateTypeArgs(args: Record<string, unknown>): ArgsResult {
  const t = pickTarget(args, "type");
  if (!t.ok) return t;
  if (typeof args.text !== "string") {
    return badArgs("type 需要 text 字符串");
  }
  if (args.submit !== undefined && typeof args.submit !== "boolean") {
    return badArgs("submit 必须是布尔");
  }
  const submit = args.submit === true;
  const text = args.text;
  if (text === "" && !submit) {
    return badArgs("text 为空时需 submit=true（否则无意义）");
  }
  const out: Record<string, unknown> = { ...t.value, text };
  if (args.submit !== undefined) out.submit = submit;
  return { ok: true, args: out };
}

export function validateWaitArgs(args: Record<string, unknown>): ArgsResult {
  const selector =
    typeof args.selector === "string" ? args.selector.trim() : "";
  const text = typeof args.text === "string" ? args.text.trim() : "";
  const hasMs = args.ms !== undefined;
  const ms = hasMs ? Number(args.ms) : 0;
  if (hasMs && (!Number.isFinite(ms) || ms < 1 || ms > 60_000)) {
    return badArgs("ms 越界（1..60000）");
  }
  const count =
    (selector !== "" ? 1 : 0) + (text !== "" ? 1 : 0) + (hasMs ? 1 : 0);
  if (count !== 1) {
    return badArgs("wait 需要 selector/text/ms 恰一");
  }
  let timeoutMs: number | undefined;
  if (args.timeout_ms !== undefined) {
    const t = Number(args.timeout_ms);
    if (!Number.isFinite(t) || t < 1 || t > 30_000) {
      return badArgs("timeout_ms 越界（1..30000）");
    }
    timeoutMs = Math.floor(t);
  }
  const out: Record<string, unknown> = {};
  if (selector !== "") out.selector = selector;
  if (text !== "") out.text = text;
  if (hasMs) out.ms = Math.floor(ms);
  if (timeoutMs !== undefined) out.timeout_ms = timeoutMs;
  return { ok: true, args: out };
}

export function validateEvaluateArgs(args: Record<string, unknown>): ArgsResult {
  const expression = typeof args.expression === "string" ? args.expression : "";
  if (expression.trim() === "") {
    return badArgs("evaluate 需要非空 expression 字符串");
  }
  if (expression.length > 4000) {
    return badArgs("expression 超长（≤4000 字符）");
  }
  return { ok: true, args: { expression } };
}

// ---- v2（§11.5-①）：浏览器身份（memory/persist；页面命令必带） ----

export interface BrowserIdentity {
  key: string;
  mode: "memory" | "persist" | "storage-state";
  workspace: string;
  state_path?: string;   // v4：仅 storage-state 档必填（登录态文件绝对路径）
}

export type IdentityResult =
  | { ok: true; identity: BrowserIdentity }
  | { ok: false; code: string; message: string };

/** 页面命令身份校验（缺/非法 fail-closed——绝不静默走默认 session）。 */
export function validateIdentityArgs(raw: unknown): IdentityResult {
  const obj = (typeof raw === "object" && raw !== null && !Array.isArray(raw))
    ? (raw as Record<string, unknown>)
    : null;
  if (obj === null) {
    return { ok: false, code: "bad-identity", message: "identity 必须是对象" };
  }
  const key = typeof obj.key === "string" ? obj.key.trim() : "";
  if (!/^[a-z0-9-]{1,64}$/.test(key)) {
    return { ok: false, code: "bad-identity", message: "identity.key 非法" };
  }
  const mode = typeof obj.mode === "string" ? obj.mode : "";
  if (mode !== "memory" && mode !== "persist" && mode !== "storage-state") {
    return {
      ok: false,
      code: "bad-identity",
      message: "identity.mode 必须为 memory|persist|storage-state",
    };
  }
  const workspace =
    typeof obj.workspace === "string" ? obj.workspace.trim() : "";
  if (workspace === "" || workspace.length > 1024) {
    return {
      ok: false,
      code: "bad-identity",
      message: "identity.workspace 非法",
    };
  }
  const identity: BrowserIdentity = {
    key, mode: mode as BrowserIdentity["mode"], workspace,
  };
  if (mode === "storage-state") {
    // v4（§11.5-③）：登录态档必须携带状态文件路径（fail-closed）
    const statePath =
      typeof obj.state_path === "string" ? obj.state_path.trim() : "";
    if (statePath === "" || statePath.length > 4096) {
      return {
        ok: false,
        code: "bad-identity",
        message: "storage-state 档需要 state_path（非空 ≤4096 字符）",
      };
    }
    identity.state_path = statePath;
  }
  return { ok: true, identity };
}

/** identity_clear 参数校验（key 白名单字符集）。 */
export function validateIdentityClearArgs(
  raw: unknown,
): { ok: true; key: string } | { ok: false; code: string; message: string } {
  const obj = (typeof raw === "object" && raw !== null && !Array.isArray(raw))
    ? (raw as Record<string, unknown>)
    : null;
  const key = obj && typeof obj.key === "string" ? obj.key.trim() : "";
  if (!/^[a-z0-9-]{1,64}$/.test(key)) {
    return { ok: false, code: "bad-identity", message: "key 非法" };
  }
  return { ok: true, key };
}

/** v3：close 必带目标身份（防误关全部；目标不存在 = 幂等 closed:false）。 */
export function validateCloseArgs(raw: unknown): IdentityResult {
  const obj = (typeof raw === "object" && raw !== null && !Array.isArray(raw))
    ? (raw as Record<string, unknown>)
    : null;
  if (obj === null) {
    return { ok: false, code: "bad-identity", message: "close 需要 args 对象" };
  }
  return validateIdentityArgs(obj.identity);
}
