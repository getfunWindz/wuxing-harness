/** 浏览器身份持久注册表（O2-2 §11.5-①）：partition 命名 + persist 条目读写。
 *
 * Electron 单写、原子（tmp+rename）、fail-closed（缺失/损坏=空表）；仅 persist 条目。
 * 纯 Node（零 Electron）——可单测。
 */
import { mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import path from "node:path";

import type { BrowserIdentity } from "./browser-protocol";

export interface IdentityEntry {
  key: string;
  workspace: string;
  mode: string;
  first_used_at: string;
  last_used_at: string;
}

export function registryPath(home: string = homedir()): string {
  return path.join(home, ".wuxing", "browser_identities.json");
}

/** 身份 → Electron session partition（memory 裸名 / persist 前缀）。 */
export function partitionFor(identity: BrowserIdentity): string {
  return identity.mode === "persist" ? `persist:${identity.key}` : identity.key;
}

export function readRegistry(file: string = registryPath()): IdentityEntry[] {
  let raw: string;
  try {
    raw = readFileSync(file, "utf8");
  } catch {
    // 缺失/不可读 → 空表（fail-closed：后续按无条目处理）
    return [];
  }
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    // 损坏 → 空表（fail-closed；写侧下一轮覆盖）
    return [];
  }
  const entries = (typeof data === "object" && data !== null
    && Array.isArray((data as { entries?: unknown }).entries))
    ? (data as { entries: unknown[] }).entries
    : null;
  if (entries === null) return [];
  const out: IdentityEntry[] = [];
  for (const e of entries) {
    if (typeof e !== "object" || e === null) continue;
    const row = e as Record<string, unknown>;
    const key = typeof row.key === "string" ? row.key : "";
    if (key === "") continue;
    out.push({
      key,
      workspace: typeof row.workspace === "string" ? row.workspace : "",
      mode: typeof row.mode === "string" ? row.mode : "persist",
      first_used_at: typeof row.first_used_at === "string"
        ? row.first_used_at : "",
      last_used_at: typeof row.last_used_at === "string"
        ? row.last_used_at : "",
    });
  }
  return out;
}

function writeRegistry(entries: IdentityEntry[], file: string): void {
  mkdirSync(path.dirname(file), { recursive: true });
  const tmp = `${file}.tmp`;
  writeFileSync(tmp, JSON.stringify({ version: 1, entries }, null, 2) + "\n",
    { encoding: "utf8", mode: 0o600 });
  renameSync(tmp, file);
}

/** 持久身份使用登记：保留 first_used_at、刷新 last_used_at。 */
export function upsertRegistry(
  identity: BrowserIdentity,
  now: string = new Date().toISOString(),
  file: string = registryPath(),
): IdentityEntry[] {
  const entries = readRegistry(file);
  const idx = entries.findIndex((e) => e.key === identity.key);
  const row: IdentityEntry = {
    key: identity.key,
    workspace: identity.workspace,
    mode: identity.mode,
    first_used_at: idx >= 0 ? entries[idx].first_used_at : now,
    last_used_at: now,
  };
  if (idx >= 0) {
    entries[idx] = row;
  } else {
    entries.push(row);
  }
  writeRegistry(entries, file);
  return entries;
}

/** 移除注册表条目（返回是否发生删除）。 */
export function removeRegistry(
  key: string,
  file: string = registryPath(),
): boolean {
  const entries = readRegistry(file);
  const kept = entries.filter((e) => e.key !== key);
  if (kept.length === entries.length) return false;
  writeRegistry(kept, file);
  return true;
}
