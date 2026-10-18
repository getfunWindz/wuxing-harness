/** 观测面只读数据（P2 dock）：技能/MCP + 任务/溯源/日志/通知/智脑/报告。
    —— 只读、零 DOM、唯一出网经 connection/rest；失败经命令总线可见。 */
import type {
  BrainStatsDto,
  BrowserAllowListDto,
  BrowserAllowRevokeDto,
  BrowserIdentityClearDto,
  BrowserIdentityDto,
  DomainPromptsDto,
  DomainPromptsSaveDto,
  InteractionPrefsDto,
  DecisionListDto,
  EventLogDto,
  MaintenanceCleanDto,
  MaintenanceDto,
  AboutDto,
  McpReloadDto,
  McpStatusDto,
  NotificationListDto,
  ProvenanceListDto,
  ReportListDto,
  SkillDto,
  SkillDetailDto,
  SkillDiscoverDto,
  SkillInstallDto,
  SkillListDto,
  SkillRemoveDto,
  TaskHistoryDto,
  TraceListDto,
  SearchResultDto,
} from "../../protocol/generated.ts";
import type { CommandBus } from "../commands.ts";
import type { WritableRestClient } from "../connection/rest.ts";

export interface ObserveService {
  skills(): Promise<SkillListDto>;
  /** M7 C1（MG-15）：关于与诊断（只读版本/环境/路径） */
  about(): Promise<AboutDto>;
  mcpStatus(): Promise<McpStatusDto>;
  taskHistory(wsId: string): Promise<TaskHistoryDto>;
  /** 轮次化（批 4）：按轮轨迹（域/状态/耗时/工具数/产物/并行标记） */
  trajectory(wsId: string): Promise<import("../../protocol/generated.ts").TrajectoryDto>;
  provenance(wsId: string): Promise<ProvenanceListDto>;
  trace(wsId: string, unit?: string): Promise<TraceListDto>;
  eventLog(tail?: number): Promise<EventLogDto>;
  notifications(since?: number, limit?: number): Promise<NotificationListDto>;
  brain(wsId: string): Promise<BrainStatsDto>;
  reports(wsId: string): Promise<ReportListDto>;
  skillDetail(name: string): Promise<SkillDetailDto>;
  skillInstall(name: string, description: string, content: string): Promise<SkillInstallDto>;
  skillRemove(name: string): Promise<SkillRemoveDto>;
  skillSetEnabled(name: string, enabled: boolean): Promise<SkillDto>;
  skillDiscover(goal: string): Promise<SkillDiscoverDto>;
  mcpReload(): Promise<McpReloadDto>;
  /** 数据与维护（设置中心「数据」分区）：概览 + 清理（workspace_cache / shell_events）。 */
  maintenance(wsId?: string): Promise<MaintenanceDto>;
  maintenanceClean(target: string, wsId?: string): Promise<MaintenanceCleanDto>;
  /** O2-2 P3：浏览器允许条目（设置「数据」分区运维）——列表 + 撤销。 */
  browserAllow(): Promise<BrowserAllowListDto>;
  browserAllowRevoke(address: string, fingerprint: string,
    kind?: string): Promise<BrowserAllowRevokeDto>;
  /** O2-2 §11.5-①：浏览器身份（设置「数据与维护」身份块）。 */
  browserIdentity(wsId?: string): Promise<BrowserIdentityDto>;
  browserIdentityClear(key: string): Promise<BrowserIdentityClearDto>;
  /** 重大优化清单 #3：域提示词（设置「域提示词」分区）。 */
  domainPrompts(wsId?: string): Promise<DomainPromptsDto>;
  domainPromptsSave(body: {
    scope: "user" | "workspace";
    ws?: string;
    values: Record<string, { notes?: string; addendum?: string }>;
  }): Promise<DomainPromptsSaveDto>;
  /** #2 Phase 1.5：交互偏好（设置「交互与文案」 + 确认卡呈现）。 */
  interaction(wsId?: string): Promise<InteractionPrefsDto>;
  interactionSave(body: {
    scope: "user" | "workspace";
    ws?: string;
    values: Record<string, unknown>;
  }): Promise<InteractionPrefsDto>;
  /** #2 T-5：决策历史（只读）。 */
  decisions(wsId?: string): Promise<DecisionListDto>;
  search(q: string): Promise<SearchResultDto>;
}

export function createObserveService(deps: {
  rest: WritableRestClient;
  commands: CommandBus;
}): ObserveService {
  return {
    skills: () =>
      deps.commands.run("observe.skills", () =>
        deps.rest.get<SkillListDto>("/api/v1/skills")),
    about: () =>
      deps.commands.run("observe.about", () =>
        deps.rest.get<AboutDto>("/api/v1/about")),
    mcpStatus: () =>
      deps.commands.run("observe.mcp", () =>
        deps.rest.get<McpStatusDto>("/api/v1/mcp")),
    taskHistory: (wsId) =>
      deps.commands.run("observe.tasks.history", () =>
        deps.rest.get<TaskHistoryDto>(`/api/v1/workspaces/${wsId}/tasks/history`)),
    trajectory: (wsId) =>
      deps.commands.run("observe.trajectory", () =>
        deps.rest.get<import("../../protocol/generated.ts").TrajectoryDto>(
          `/api/v1/workspaces/${wsId}/trajectory`)),
    provenance: (wsId) =>
      deps.commands.run("observe.provenance", () =>
        deps.rest.get<ProvenanceListDto>(`/api/v1/workspaces/${wsId}/observe/provenance`)),
    trace: (wsId, unit = "") =>
      deps.commands.run("observe.trace", () =>
        deps.rest.get<TraceListDto>(
          `/api/v1/workspaces/${wsId}/observe/trace` +
          (unit === "" ? "" : `?unit=${encodeURIComponent(unit)}`))),
    eventLog: (tail = 200) =>
      deps.commands.run("observe.events.log", () =>
        deps.rest.get<EventLogDto>(`/api/v1/events/log?tail=${tail}`)),
    notifications: (since = 0, limit = 100) =>
      deps.commands.run("observe.notifications", () =>
        deps.rest.get<NotificationListDto>(
          `/api/v1/notifications?since=${since}&limit=${limit}`)),
    brain: (wsId) =>
      deps.commands.run("observe.brain", () =>
        deps.rest.get<BrainStatsDto>(`/api/v1/workspaces/${wsId}/brain`)),
    reports: (wsId) =>
      deps.commands.run("observe.reports", () =>
        deps.rest.get<ReportListDto>(`/api/v1/workspaces/${wsId}/reports`)),
    skillDetail: (name) =>
      deps.commands.run("observe.skills.detail", () =>
        deps.rest.get<SkillDetailDto>(`/api/v1/skills/${encodeURIComponent(name)}`)),
    skillInstall: (name, description, content) =>
      deps.commands.run("observe.skills.install", () =>
        deps.rest.post<SkillInstallDto>("/api/v1/skills/install",
          { name, description, content })),
    skillRemove: (name) =>
      deps.commands.run("observe.skills.remove", () =>
        deps.rest.del<SkillRemoveDto>(`/api/v1/skills/${encodeURIComponent(name)}`)),
    skillSetEnabled: (name, enabled) =>
      deps.commands.run("observe.skills.toggle", () =>
        deps.rest.patch<SkillDto>(`/api/v1/skills/${encodeURIComponent(name)}`,
                                  { enabled })),
    skillDiscover: (goal) =>
      deps.commands.run("observe.skills.discover", () =>
        deps.rest.post<SkillDiscoverDto>("/api/v1/skills/discover", { goal })),
    mcpReload: () =>
      deps.commands.run("observe.mcp.reload", () =>
        deps.rest.post<McpReloadDto>("/api/v1/mcp/reload", {})),
    maintenance: (wsId) =>
      deps.commands.run("observe.maintenance", () =>
        deps.rest.get<MaintenanceDto>(
          wsId === undefined || wsId === ""
            ? "/api/v1/maintenance"
            : `/api/v1/maintenance?ws=${encodeURIComponent(wsId)}`)),
    maintenanceClean: (target, wsId) =>
      deps.commands.run("observe.maintenance.clean", () =>
        deps.rest.post<MaintenanceCleanDto>("/api/v1/maintenance/clean",
          wsId === undefined || wsId === "" ? { target } : { target, ws: wsId })),
    browserAllow: () =>
      deps.commands.run("observe.browserAllow", () =>
        deps.rest.get<BrowserAllowListDto>("/api/v1/browser/allow")),
    browserAllowRevoke: (address, fingerprint, kind = "loopback") =>
      deps.commands.run("observe.browserAllow.revoke", () =>
        deps.rest.post<BrowserAllowRevokeDto>("/api/v1/browser/allow/revoke",
          { address, fingerprint, kind })),
    browserIdentity: (wsId?: string) =>
      deps.commands.run("observe.browserIdentity", () =>
        deps.rest.get<BrowserIdentityDto>(
          `/api/v1/browser/identity${wsId ? `?ws=${encodeURIComponent(wsId)}` : ""}`)),
    browserIdentityClear: (key) =>
      deps.commands.run("observe.browserIdentity.clear", () =>
        deps.rest.post<BrowserIdentityClearDto>(
          "/api/v1/browser/identity/clear", { key })),
    domainPrompts: (wsId?: string) =>
      deps.commands.run("observe.domainPrompts", () =>
        deps.rest.get<DomainPromptsDto>(
          `/api/v1/prompts/domains${wsId ? `?ws=${encodeURIComponent(wsId)}` : ""}`)),
    domainPromptsSave: (body) =>
      deps.commands.run("observe.domainPromptsSave", () =>
        deps.rest.post<DomainPromptsSaveDto>("/api/v1/prompts/domains", body)),
    interaction: (wsId?: string) =>
      deps.commands.run("observe.interaction", () =>
        deps.rest.get<InteractionPrefsDto>(
          `/api/v1/interaction${wsId ? `?ws=${encodeURIComponent(wsId)}` : ""}`)),
    interactionSave: (body) =>
      deps.commands.run("observe.interactionSave", () =>
        deps.rest.post<InteractionPrefsDto>("/api/v1/interaction", body)),
    decisions: (wsId?: string) =>
      deps.commands.run("observe.decisions", () =>
        deps.rest.get<DecisionListDto>(
          `/api/v1/workspaces/${wsId}/decisions`)),
    search: (q) =>
      deps.commands.run("observe.search", () =>
        deps.rest.get<SearchResultDto>(`/api/v1/search?q=${encodeURIComponent(q)}`)),
  };
}
