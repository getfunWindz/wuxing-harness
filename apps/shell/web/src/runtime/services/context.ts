/** 上下文服务（B 期）：投影预览/列表 + 投影层编辑（omit/replace）。
 *
 * 设计：`docs/WUXING_上下文窗口自选_B期设计_2026-09-22.md` §4/§5。
 * 失败经命令总线可见（禁静默）；浏览（previews）为只读低频，仍走总线统一呈现。 */
import type {
  ContextEditDto,
  ContextPreviewDto,
  ContextPreviewListDto,
  ContextSourcesAckDto,
  HandoffBriefDto,
} from "../../protocol/generated.ts";
import type { CommandBus } from "../commands.ts";
import type { WritableRestClient } from "../connection/rest.ts";

export interface ContextEditInput {
  readonly round: number;
  readonly op: "omit" | "replace" | "restore";
  readonly content?: string;
}

export interface ContextSourceValues {
  readonly history?: boolean;
  readonly digest?: boolean;
  readonly skills?: boolean;
  readonly prefix?: boolean;
  readonly budget_tokens?: number;
}

export interface ContextUnitEditInput {
  readonly index: number;
  readonly fp_in: string;
  readonly fp_out: string;
  readonly file?: string;
  readonly op: "omit" | "replace" | "restore";
  readonly content?: string;
}

export interface ContextService {
  /** 单会话/单碎片投影（session 与 unit 二选一） */
  preview(
    wsId: string,
    target: { session?: string; unit?: string },
  ): Promise<ContextPreviewDto>;
  /** 全部会话行（dock 列表 %） */
  previews(wsId: string): Promise<ContextPreviewListDto>;
  /** 追加投影层编辑（append-only；日志零改写；返回更新后的预览） */
  edit(wsId: string, name: string, edit: ContextEditInput): Promise<ContextEditDto>;
  /** A2：碎片消息三键编辑（index + 双指纹） */
  editUnit(wsId: string, unit: string, edit: ContextUnitEditInput): Promise<ContextEditDto>;
  /** A1：来源开关读取（含刷新后的投影） */
  sources(
    wsId: string,
    target: { session?: string; unit?: string },
  ): Promise<ContextSourcesAckDto>;
  /** A1：来源开关写入（会话级持久——用户动作走命令总线） */
  setSources(
    wsId: string,
    target: { session?: string; unit?: string },
    values: ContextSourceValues,
  ): Promise<ContextSourcesAckDto>;
  /** 批 4：新会话承接简报（只读直连——确定性拼装，服务端生成） */
  handoffBrief(wsId: string, session: string): Promise<HandoffBriefDto>;
}

export function createContextService(deps: {
  rest: WritableRestClient;
  commands: CommandBus;
}): ContextService {
  const base = (wsId: string): string => `/api/v1/workspaces/${wsId}`;
  const query = (target: { session?: string; unit?: string }): string =>
    target.unit !== undefined && target.unit !== ""
      ? `unit=${encodeURIComponent(target.unit)}`
      : `session=${encodeURIComponent(target.session ?? "")}`;
  return {
    // 预览/列表为**后台只读刷新**：直连 REST，不走命令总线
    // （2026-09-22 教训：后台刷新进总线会使 pendingCount>0——输入区被短暂
    //  禁用，吞掉用户提交；与 sessions.title 「不进总线」同口径）。
    preview: (wsId, target) =>
      deps.rest.get<ContextPreviewDto>(
        `${base(wsId)}/context-preview?${query(target)}`),
    previews: (wsId) =>
      deps.rest.get<ContextPreviewListDto>(`${base(wsId)}/context-previews`),
    edit: (wsId, name, edit) => {
      // 用户动作：走命令总线（失败全局可见）；replace 必须带 content（服务端 422 兜底）
      const body: Record<string, unknown> = { round: edit.round, op: edit.op };
      if (edit.op === "replace") body.content = edit.content ?? "";
      return deps.commands.run("context.edit", () =>
        deps.rest.post<ContextEditDto>(
          `${base(wsId)}/conversations/${encodeURIComponent(name)}/context-edits`,
          body));
    },
    editUnit: (wsId, unit, edit) => {
      // A2：三键记录（index + fp_in + fp_out）；replace 必须带 content（服务端 422 兜底）
      const body: Record<string, unknown> = {
        index: edit.index, fp_in: edit.fp_in, fp_out: edit.fp_out, op: edit.op,
      };
      if (edit.file !== undefined && edit.file !== "") body.file = edit.file;
      if (edit.op === "replace") body.content = edit.content ?? "";
      return deps.commands.run("context.editUnit", () =>
        deps.rest.post<ContextEditDto>(
          `${base(wsId)}/unit-sessions/${encodeURIComponent(unit)}/context-edits`,
          body));
    },
    // A1：来源读取为后台只读（直连）；写入为用户动作（走总线）
    sources: (wsId, target) =>
      deps.rest.get<ContextSourcesAckDto>(
        `${base(wsId)}/context-sources?${query(target)}`),
    setSources: (wsId, target, values) =>
      deps.commands.run("context.setSources", () =>
        deps.rest.put<ContextSourcesAckDto>(
          `${base(wsId)}/context-sources?${query(target)}`, { ...values })),
    // 批 4：承接简报为后台只读（直连——不进总线，同 preview 口径）
    handoffBrief: (wsId, session) =>
      deps.rest.get<HandoffBriefDto>(
        `${base(wsId)}/handoff-brief?session=${encodeURIComponent(session)}`),
  };
}
