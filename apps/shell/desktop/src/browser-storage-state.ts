/** storage-state 登录态档纯模块（O2-2 §11.5-③）：Playwright 格式解析/校验/注入计划。
 *
 * 零 Electron——可 node --test；**值纪律**：本模块不打印/不外传值，只做映射与计数。
 * 格式（D5）：`{cookies:[{name,value,domain,path,expires,httpOnly,secure,sameSite}],
 * origins:[{origin, localStorage:[{name,value}]}]}`。
 */

export interface StorageCookie {
  name: string;
  value: string;
  domain: string;
  path: string;
  expires?: number;
  httpOnly?: boolean;
  secure?: boolean;
  sameSite?: "Strict" | "Lax" | "None";
}

export interface StorageOrigin {
  origin: string;
  localStorage: Array<{ name: string; value: string }>;
}

export interface StorageCounts {
  cookies: number;
  origins: number;
}

export type StorageStateParse =
  | { ok: true; cookies: StorageCookie[]; origins: StorageOrigin[]; counts: StorageCounts }
  | { ok: false; error: string };

const MAX_ORIGIN_LOCAL_ITEMS = 5000;

function bad(error: string): { ok: false; error: string } {
  return { ok: false, error: `storage-state 非法：${error}` };
}

export function parseStorageState(raw: string): StorageStateParse {
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    return bad("JSON 解析失败");
  }
  if (typeof data !== "object" || data === null || Array.isArray(data)) {
    return bad("顶层必须是对象");
  }
  const obj = data as Record<string, unknown>;
  const rawCookies = obj.cookies;
  const rawOrigins = obj.origins;
  if (!Array.isArray(rawCookies) || !Array.isArray(rawOrigins)) {
    return bad("需要 cookies/origins 数组");
  }
  if (rawCookies.length === 0 && rawOrigins.length === 0) {
    return bad("为空（无 cookies/origins）");
  }
  const cookies: StorageCookie[] = [];
  for (const item of rawCookies) {
    if (typeof item !== "object" || item === null) return bad("cookie 条目非对象");
    const c = item as Record<string, unknown>;
    const name = typeof c.name === "string" ? c.name : "";
    const value = typeof c.value === "string" ? c.value : "";
    const domain = typeof c.domain === "string" ? c.domain : "";
    if (name === "" || domain === "") return bad("cookie 缺少 name/domain");
    const cookie: StorageCookie = {
      name, value, domain,
      path: typeof c.path === "string" && c.path !== "" ? c.path : "/",
    };
    if (typeof c.expires === "number" && Number.isFinite(c.expires)) {
      cookie.expires = c.expires;
    }
    if (typeof c.httpOnly === "boolean") cookie.httpOnly = c.httpOnly;
    if (typeof c.secure === "boolean") cookie.secure = c.secure;
    if (c.sameSite === "Strict" || c.sameSite === "Lax"
        || c.sameSite === "None") {
      cookie.sameSite = c.sameSite;
    }
    cookies.push(cookie);
  }
  const origins: StorageOrigin[] = [];
  for (const item of rawOrigins) {
    if (typeof item !== "object" || item === null) return bad("origin 条目非对象");
    const o = item as Record<string, unknown>;
    const origin = typeof o.origin === "string" ? o.origin.trim() : "";
    let parsed: URL;
    try {
      parsed = new URL(origin);
    } catch {
      return bad(`origin 非法：${origin}`);
    }
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
      return bad(`origin 仅支持 http/https：${origin}`);
    }
    const rawItems = o.localStorage;
    if (!Array.isArray(rawItems) || rawItems.length > MAX_ORIGIN_LOCAL_ITEMS) {
      return bad(`origin.localStorage 非法：${origin}`);
    }
    const localStorage: Array<{ name: string; value: string }> = [];
    for (const li of rawItems) {
      if (typeof li !== "object" || li === null) return bad("localStorage 条目非对象");
      const l = li as Record<string, unknown>;
      if (typeof l.name !== "string" || typeof l.value !== "string") {
        return bad("localStorage 条目需要字符串 name/value");
      }
      localStorage.push({ name: l.name, value: l.value });
    }
    origins.push({ origin, localStorage });
  }
  return {
    ok: true, cookies, origins,
    counts: { cookies: cookies.length, origins: origins.length },
  };
}

/** cookie → Electron `session.cookies.set` 参数（url 按 domain/path/scheme 构造）。 */
export function cookieParams(cookie: StorageCookie): Record<string, unknown> {
  const scheme = cookie.secure === true ? "https" : "http";
  const host = cookie.domain.replace(/^\./, "");
  const url = `${scheme}://${host}${cookie.path.startsWith("/") ? cookie.path : `/${cookie.path}`}`;
  const out: Record<string, unknown> = {
    url,
    name: cookie.name,
    value: cookie.value,
    domain: cookie.domain,
    path: cookie.path,
  };
  if (cookie.expires !== undefined && cookie.expires > 0) {
    out.expirationDate = cookie.expires;
  }
  if (cookie.httpOnly !== undefined) out.httpOnly = cookie.httpOnly;
  if (cookie.secure !== undefined) out.secure = cookie.secure;
  if (cookie.sameSite !== undefined) out.sameSite = cookie.sameSite;
  return out;
}
