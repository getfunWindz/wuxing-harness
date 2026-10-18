/** 会话消息装载（并发安全——2026-09-30 修复）。
 *
 * 背景（用户黄金测试灾难级问题）：openSession 后异步拉取 messages/rounds，
 * 旧实现 await 后**无条件回填**且 rounds 用写入时刻的 activeSession——
 * 快速切换会话时，慢响应（尤其空会话 []）覆盖当前视图 → 「切回初始页」。
 * 本模块：入口快照会话身份，每个 await 之后校验；不一致即丢弃（陈旧）。
 * 纯逻辑（依赖注入）——node:test 覆盖；DOM 渲染由调用方负责。
 */
import type { SessionRoundsDto } from "../protocol/generated.ts";

export interface SessionChatRef {
  wsId: string;
  name: string;
}

export interface SessionLoadDeps {
  /** 当前激活的（工作区，会话）——每次调用实时读取。 */
  current(): { wsId: string | null; name: string | null };
  fetchMessages(wsId: string, name: string):
    Promise<{ rows?: readonly Record<string, unknown>[] }>;
  fetchRounds(wsId: string, name: string): Promise<SessionRoundsDto>;
  /** Wave-2 T2（用户裁决 2026-10-01）：切换即清旧内容——首个 await 前调用
   *  （先清后填，杜绝切换中闪前一会话内容）。 */
  onStart?(): void;
  onApply(rows: readonly Record<string, unknown>[],
          rounds: SessionRoundsDto | null): void;
  onClear(): void;
}

function sameRef(ref: SessionChatRef,
                 cur: { wsId: string | null; name: string | null }): boolean {
  return ref.wsId === cur.wsId && ref.name === cur.name;
}

/** 装载当前会话（并发安全）：会话已切走 → 响应丢弃；读取失败 → 保留旧数据。 */
export async function loadSessionChat(deps: SessionLoadDeps): Promise<void> {
  const start = deps.current();
  if (start.wsId === null || start.name === null) {
    deps.onClear();
    return;
  }
  deps.onStart?.();   // Wave-2 T2：先清后填（切换即清行 + 装载态）
  const ref: SessionChatRef = { wsId: start.wsId, name: start.name };
  let rows: readonly Record<string, unknown>[];
  try {
    rows = (await deps.fetchMessages(ref.wsId, ref.name)).rows ?? [];
  } catch {
    return; // 读取失败保留旧数据（不静默清空）
  }
  if (!sameRef(ref, deps.current())) {
    return; // 陈旧会话 → 丢弃（不得覆盖当前视图）
  }
  let rounds: SessionRoundsDto | null = null;
  try {
    rounds = await deps.fetchRounds(ref.wsId, ref.name);
  } catch {
    rounds = null; // 轮次聚合失败不阻塞会话展示
  }
  if (!sameRef(ref, deps.current())) {
    return; // 第二次 await 后再次校验（rounds 不得串台）
  }
  deps.onApply(rows, rounds);
}
