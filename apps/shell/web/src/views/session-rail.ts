/** 左栏会话行加载（2026-09-27 全角落审查修复）：
 *  列表**立即上屏**，LLM 标题后台补齐——切工作区时列表不再被标题生成阻塞。
 *
 * 背景（实测复现）：旧实现 `refreshRailSessions` 串行等待最多 8 条标题生成
 * （真实服务 = LLM 总结首轮，秒级/可被客户端中止）才更新 `railSessions`——
 * 用户看到「工作区已切换、会话列表仍是旧的/空的」，易误以为切换未生效。
 * 本模块把「列表就位」与「标题补齐」解耦，并防陈旧回填（工作区切走后丢弃）；
 * U12（2026-09-27）：标题补齐改为**有界并发**（缺省 2）+ 上量限流（缺省 8）——
 * 缓存命中（title 非空）不请求，单条失败静默重试下轮。
 */
import type { SessionDto } from "../protocol/generated.ts";
import { deriveSessionRows, type SessionRow } from "./view-model.ts";

export interface SessionRailDeps {
  /** 会话列表（快；不得阻塞在标题上） */
  readonly list: () => Promise<readonly SessionDto[]>;
  /** 单条标题生成（慢——LLM；失败抛出由本模块吞掉） */
  readonly title: (name: string) => Promise<string>;
  /** 列表就位（立即调用——先上屏，不等标题）；startedAt = 列表发起时刻
   *  （Wave-2 T3：调用方以「发起时刻 vs 选择时刻」判定陈旧快照）。 */
  readonly apply: (rows: SessionRow[], startedAt: number) => void;
  /** 单条标题后台到达（调用方负责更新行 + 重渲染） */
  readonly onTitle: (name: string, title: string) => void;
  /** 陈旧判定（工作区已切走 → true；回填丢弃） */
  readonly isStale: () => boolean;
  /** 单次标题补齐上限（缺省 8——防一次会话切换触发过多 LLM 调用） */
  readonly titleLimit?: number;
  /** 标题补齐并发上限（缺省 2——限流 LLM 调用；缓存命中不请求） */
  readonly titleConcurrency?: number;
}

/** 加载会话行：列表立即应用；标题异步补齐（不阻塞返回）。 */
export async function loadSessionRail(deps: SessionRailDeps): Promise<void> {
  const startedAt = Date.now();   // Wave-2 T3：列表发起时刻（apply 携带——反清判据）
  const sessions = await deps.list();
  deps.apply(deriveSessionRows(sessions), startedAt);
  void backfillTitles(deps, sessions); // 后台补齐——列表已上屏
}

async function backfillTitles(deps: SessionRailDeps,
                              sessions: readonly SessionDto[]): Promise<void> {
  const limit = Math.max(0, deps.titleLimit ?? 8);
  const concurrency = Math.max(1, deps.titleConcurrency ?? 2);
  const pending = sessions
    .filter((s) => s.title.trim() === "")
    .slice(0, limit);
  let idx = 0;
  const worker = async (): Promise<void> => {
    for (;;) {
      if (deps.isStale()) return;
      const item = pending[idx];
      idx += 1;
      if (item === undefined) return;
      let title = "";
      try {
        title = (await deps.title(item.name)).trim();
      } catch (err) {
        void err; // 单条标题失败静默（下轮重试）——不阻断后续
        continue;
      }
      if (deps.isStale()) return;
      if (title !== "") deps.onTitle(item.name, title);
    }
  };
  await Promise.all(Array.from(
    { length: Math.min(concurrency, pending.length) }, () => worker()));
}
