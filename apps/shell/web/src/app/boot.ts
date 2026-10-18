/** 应用装配：运行时内核（两阶段启动 + 事件接线 + 错误边界；无 DOM）。 */
import type { AnyEvent } from "../protocol/generated.ts";
import { createCommandBus, type CommandBus, type CommandEvent } from "../runtime/commands.ts";
import { createRestClient } from "../runtime/connection/rest.ts";
import {
  createSseClient,
  type SseControlFrame,
  type SseStatus,
  type SseTransportFactory,
} from "../runtime/connection/sse.ts";
import { defineModule, ModuleHost } from "../runtime/kernel/modules.ts";
import { ServiceRegistry, serviceToken } from "../runtime/kernel/services.ts";
import { SlotRegistry } from "../runtime/kernel/slots.ts";
import { createTaskService, type TaskService } from "../runtime/services/tasks.ts";
import { createSettingsService, type SettingsService } from "../runtime/services/settings.ts";
import { createObserveService, type ObserveService } from "../runtime/services/observe.ts";
import { createDialogService, type DialogService } from "../runtime/services/dialog.ts";
import { createRecycleService, type RecycleService } from "../runtime/services/recycle.ts";
import { createSessionsService, type SessionsService } from "../runtime/services/sessions.ts";
import { createContextService, type ContextService } from "../runtime/services/context.ts";
import { createModesService, type ModesService } from "../runtime/services/modes.ts";
import { createDesignService, type DesignService } from "../runtime/services/design.ts";
import { createExtensionsService, type ExtensionsService } from "../runtime/services/extensions.ts";
import { createPresetsService, type PresetsService } from "../runtime/services/presets.ts";
import { createWorkspacesService, type WorkspacesService } from "../runtime/services/workspaces.ts";

export interface RuntimeOptions {
  baseUrl: string;
  fetchLike?: typeof fetch;
  transport?: SseTransportFactory;
  onStatus?(status: SseStatus): void;
  onCommandFailure?(event: CommandEvent): void;
  onSettle?(): void;
}

export interface Runtime {
  readonly commands: CommandBus;
  readonly services: ServiceRegistry;
  readonly slots: SlotRegistry;
  readonly workspaces: WorkspacesService;
  readonly tasks: TaskService;
  readonly settings: SettingsService;
  readonly observe: ObserveService;
  readonly dialog: DialogService;
  readonly recycle: RecycleService;
  readonly sessions: SessionsService;
  /** 上下文投影/编辑（B 期） */
  readonly context: ContextService;
  /** 会话模式（双模式批 1） */
  readonly modes: ModesService;
  /** 循迹设计（双模式批 3） */
  readonly design: DesignService;
  /** 扩展命令（E2-UI） */
  readonly extensions: ExtensionsService;
  /** 装配预设（E2-UI） */
  readonly presets: PresetsService;
  start(): Promise<void>;
  stop(): void;
}

const WORKSPACES_TOKEN = serviceToken<WorkspacesService>("workspaces");
const TASKS_TOKEN = serviceToken<TaskService>("tasks");

function isEnvelope(value: unknown): value is AnyEvent {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as { seq?: unknown }).seq === "number" &&
    typeof (value as { type?: unknown }).type === "string"
  );
}

export function createRuntime(options: RuntimeOptions): Runtime {
  const commands = createCommandBus(options.onCommandFailure);
  const rest = createRestClient({
    baseUrl: options.baseUrl,
    ...(options.fetchLike ? { fetchLike: options.fetchLike } : {}),
  });
  const settings = createSettingsService({ rest, commands });
  const observe = createObserveService({ rest, commands });
  const dialog = createDialogService({ rest, commands });
  const recycle = createRecycleService({ rest, commands });
  const sessions = createSessionsService({ rest, commands });
  const context = createContextService({ rest, commands });
  const modes = createModesService({ rest, commands });
  const design = createDesignService({ rest, commands });
  const extensions = createExtensionsService({ rest, commands });
  const presets = createPresetsService({ rest, commands });
  const services = new ServiceRegistry();
  const slots = new SlotRegistry();
  const modules = new ModuleHost(services);

  // ---- 阶段一：注册（只登记 setup；依赖齐备才激活） ----
  modules.register(defineModule({
    id: "core.workspaces",
    setup: (ctx) => {
      ctx.provide(WORKSPACES_TOKEN, createWorkspacesService({ rest, commands }));
    },
  }));
  modules.register(defineModule({
    id: "core.tasks",
    deps: ["core.workspaces"],
    setup: (ctx) => {
      const workspaces = ctx.services.resolve(WORKSPACES_TOKEN);
      ctx.provide(TASKS_TOKEN, createTaskService({
        rest,
        commands,
        workspaceId: () => workspaces.activeId(),
      }));
    },
  }));
  modules.register(defineModule({
    id: "core.events",
    deps: ["core.workspaces", "core.tasks"],
    setup: (ctx) => {
      const workspaces = ctx.services.resolve(WORKSPACES_TOKEN);
      const tasks = ctx.services.resolve(TASKS_TOKEN);
      let lastEpoch: string | null = null;

      const reload = async (): Promise<void> => {
        tasks.projection.reset();
        workspaces.projection.reset();
        await workspaces.refresh();
        const activeId = workspaces.activeId();
        if (activeId) await tasks.setWorkspace(activeId);
      };

      const handleControl = (frame: SseControlFrame): void => {
        const epoch = typeof frame.data.epoch === "string" ? frame.data.epoch : null;
        const changed = epoch !== null && lastEpoch !== null && epoch !== lastEpoch;
        if (epoch !== null) lastEpoch = epoch;
        if (frame.type === "resync_required" || changed) {
          void reload().catch(() => {
            // 失败已在命令总线广播（全局面呈现）——此处仅防未处理拒绝
          });
        }
      };

      const sse = createSseClient({
        baseUrl: options.baseUrl,
        ...(options.transport ? { transport: options.transport } : {}),
        onStatus: options.onStatus ?? (() => {}),
        onControl: handleControl,
        onEvent: (envelope) => {
          if (isEnvelope(envelope)) tasks.applyEvent(envelope);
        },
      });
      sse.start();
      ctx.effect(() => { sse.stop(); });

      // 移动端：后台回前台 / 网络恢复 → 立即重连（WebView 后台会挂起 SSE；since 续传）
      const resumeSse = (): void => { sse.reconnectNow(); };
      if (typeof document !== "undefined") {
        document.addEventListener("visibilitychange", () => {
          if (!document.hidden) resumeSse();
        });
      }
      if (typeof window !== "undefined") {
        window.addEventListener("online", resumeSse);
      }
    },
  }));

  const resolveWorkspaces = (): WorkspacesService => services.resolve(WORKSPACES_TOKEN);
  const resolveTasks = (): TaskService => services.resolve(TASKS_TOKEN);

  return {
    commands,
    services,
    slots,
    settings,
    observe,
    dialog,
    recycle,
    sessions,
    context,
    modes,
    design,
    extensions,
    presets,
    get workspaces(): WorkspacesService {
      return resolveWorkspaces();
    },
    get tasks(): TaskService {
      return resolveTasks();
    },
    /** 阶段二：激活 → 首次数据 → settle（调用方在 settle 后揭示 UI） */
    async start() {
      const report = modules.activateAll();
      if (report.failed.length > 0 || report.skipped.length > 0) {
        throw new Error(
          `核心模块激活失败（failed=${JSON.stringify(report.failed)} ` +
          `skipped=${JSON.stringify(report.skipped)}）`,
        );
      }
      await resolveWorkspaces().refresh();
      const activeId = resolveWorkspaces().activeId();
      if (activeId) {
        await resolveTasks().setWorkspace(activeId);
      }
      options.onSettle?.();
    },
    stop() {
      modules.disposeAll();
    },
  };
}
