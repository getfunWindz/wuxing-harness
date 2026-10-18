/** 工作区服务：列表投影 + 活动工作区（消费 REST，不碰 DOM）。 */
import type { FolderDto, WorkspaceDto, WorkspaceListDto } from "../../protocol/generated.ts";
import type { CommandBus } from "../commands.ts";
import type { WritableRestClient } from "../connection/rest.ts";
import { createProjection, type Projection } from "../projection/store.ts";

export interface WorkspacesService {
  readonly projection: Projection<readonly WorkspaceDto[]>;
  list(): readonly WorkspaceDto[];
  activeId(): string | null;
  setActive(id: string | null): void;
  refresh(): Promise<void>;
  create(path: string): Promise<string>;
  archive(id: string, state?: string): Promise<void>;
  close(id: string): Promise<void>;
  folders(): readonly FolderDto[];
  createFolder(name: string): Promise<void>;
  renameFolder(id: string, name: string): Promise<void>;
  setFolderCollapsed(id: string, collapsed: boolean): Promise<void>;
  setAutoConfirm(id: string, autoConfirm: boolean): Promise<void>;
  deleteFolder(id: string): Promise<void>;
  moveToFolder(wsId: string, folder: string): Promise<void>;
  subscribe(listener: () => void): () => void;
}

export function createWorkspacesService(deps: {
  rest: WritableRestClient;
  commands: CommandBus;
}): WorkspacesService {
  const projection = createProjection<readonly WorkspaceDto[]>([]);
  const folderProjection = createProjection<readonly FolderDto[]>([]);
  let active: string | null = null;
  const listeners = new Set<() => void>();
  const notify = (): void => {
    for (const listener of [...listeners]) listener();
  };

  async function loadAll(): Promise<void> {
    const payload = await deps.commands.run("workspaces.refresh", () =>
      deps.rest.get<WorkspaceListDto>("/api/v1/workspaces"));
    projection.seed(payload.workspaces);
    folderProjection.seed(payload.folders ?? []);
    // 激活工作区已不存在（关闭/归档）→ 回退首个（否则后续查询打到已移除工作区）
    if (active === null || !payload.workspaces.some((w) => w.id === active)) {
      active = payload.workspaces[0]?.id ?? null;
    }
    notify();
  }

  return {
    projection,
    list: () => projection.get(),
    activeId: () => active,
    setActive(id) {
      active = id;
      notify();
    },
    async refresh(): Promise<void> {
      await loadAll();
    },
    async create(path: string): Promise<string> {
      const created = await deps.commands.run("workspaces.create", () =>
        deps.rest.post<{ id: string }>("/api/v1/workspaces", { path }));
      await loadAll();
      active = created.id;
      notify();
      return created.id;
    },
    async archive(id: string, state = "archived"): Promise<void> {
      await deps.commands.run("workspaces.archive", () =>
        deps.rest.post(`/api/v1/workspaces/${id}/archive`, { state }));
      await loadAll();
    },
    async close(id: string): Promise<void> {
      await deps.commands.run("workspaces.close", () =>
        deps.rest.del(`/api/v1/workspaces/${id}`));
      await loadAll();
    },
    folders: () => folderProjection.get(),
    async createFolder(name: string): Promise<void> {
      await deps.commands.run("folders.create", () =>
        deps.rest.post("/api/v1/folders", { name }));
      await loadAll();
    },
    async renameFolder(id: string, name: string): Promise<void> {
      await deps.commands.run("folders.rename", () =>
        deps.rest.patch(`/api/v1/folders/${id}`, { name }));
      await loadAll();
    },
    async setFolderCollapsed(id: string, collapsed: boolean): Promise<void> {
      await deps.commands.run("folders.collapse", () =>
        deps.rest.patch(`/api/v1/folders/${id}`, { collapsed }));
      await loadAll();
    },
    async setAutoConfirm(id: string, autoConfirm: boolean): Promise<void> {
      await deps.commands.run("workspaces.autoConfirm", () =>
        deps.rest.put(`/api/v1/workspaces/${id}/settings`,
                      { auto_confirm: autoConfirm }));
      await loadAll();
    },
    async deleteFolder(id: string): Promise<void> {
      await deps.commands.run("folders.delete", () =>
        deps.rest.del(`/api/v1/folders/${id}`));
      await loadAll();
    },
    async moveToFolder(wsId: string, folder: string): Promise<void> {
      await deps.commands.run("workspaces.move", () =>
        deps.rest.put(`/api/v1/workspaces/${wsId}/folder`, { folder }));
      await loadAll();
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => { listeners.delete(listener); };
    },
  };
}
