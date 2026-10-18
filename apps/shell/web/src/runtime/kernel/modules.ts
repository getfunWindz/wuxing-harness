/** 模块生命周期：依赖齐备才激活；两阶段卸载（宣告 → 逆序释放）。 */
import type { Disposer, ServiceRegistry, ServiceToken } from "./services.ts";

export interface ModuleContext {
  /** 登记服务（注销在卸载「宣告」阶段执行） */
  provide<T>(token: ServiceToken<T>, value: T): void;
  /** 登记逆操作（LIFO 逆序清理，在「释放」阶段执行） */
  effect(disposer: Disposer): void;
  readonly services: ServiceRegistry;
}

export interface ModuleDefinition {
  readonly id: string;
  readonly deps?: readonly string[];
  readonly setup: (ctx: ModuleContext) => void;
}

export function defineModule(definition: ModuleDefinition): ModuleDefinition {
  return definition;
}

export type ModuleState = "registered" | "active" | "failed" | "disposed";

interface InternalModule {
  readonly def: ModuleDefinition;
  state: ModuleState;
  error?: unknown;
  readonly provides: Disposer[];
  readonly effects: Disposer[];
}

export interface ActivationReport {
  readonly active: readonly string[];
  readonly skipped: readonly string[];
  readonly failed: ReadonlyArray<{ id: string; error: unknown }>;
}

export class ModuleHost {
  private readonly modules = new Map<string, InternalModule>();
  private readonly services: ServiceRegistry;

  constructor(services: ServiceRegistry) {
    this.services = services;
  }

  register(definition: ModuleDefinition): void {
    if (this.modules.has(definition.id)) {
      throw new Error(`模块重复注册：${definition.id}`);
    }
    this.modules.set(definition.id, {
      def: definition,
      state: "registered",
      provides: [],
      effects: [],
    });
  }

  /** 多轮扫描：依赖齐备才激活；setup 抛错 → failed（不阻塞其余） */
  activateAll(): ActivationReport {
    const active: string[] = [];
    const failed: Array<{ id: string; error: unknown }> = [];
    let progressed = true;
    while (progressed) {
      progressed = false;
      for (const mod of this.modules.values()) {
        if (mod.state !== "registered") continue;
        const deps = mod.def.deps ?? [];
        if (!deps.every((dep) => this.modules.get(dep)?.state === "active")) continue;
        const ctx: ModuleContext = {
          services: this.services,
          provide: (token, value) => {
            mod.provides.push(this.services.provide(token, value));
          },
          effect: (disposer) => {
            mod.effects.push(disposer);
          },
        };
        try {
          mod.def.setup(ctx);
          mod.state = "active";
          active.push(mod.def.id);
        } catch (error) {
          mod.state = "failed";
          mod.error = error;
          failed.push({ id: mod.def.id, error });
        }
        progressed = true;
      }
    }
    const skipped = [...this.modules.values()]
      .filter((mod) => mod.state === "registered")
      .map((mod) => mod.def.id);
    return { active, skipped, failed };
  }

  stateOf(id: string): ModuleState | undefined {
    return this.modules.get(id)?.state;
  }

  /** 两阶段卸载：阶段一「宣告」全部退出并注销服务；阶段二逆序 LIFO 释放资源。 */
  disposeAll(): void {
    const ordered = [...this.modules.values()].reverse();
    for (const mod of ordered) {
      if (mod.state === "active" || mod.state === "failed") {
        mod.state = "disposed";
      }
      while (mod.provides.length > 0) {
        const disposer = mod.provides.pop();
        if (disposer) this.runGuarded(disposer);
      }
    }
    for (const mod of ordered) {
      while (mod.effects.length > 0) {
        const disposer = mod.effects.pop();
        if (disposer) this.runGuarded(disposer);
      }
    }
  }

  /** 释放阶段的失败（不阻塞其余清理；记录以供调用方观测） */
  disposalErrors(): readonly unknown[] {
    return this.releaseErrors;
  }

  private readonly releaseErrors: unknown[] = [];

  private runGuarded(disposer: Disposer): void {
    try {
      disposer();
    } catch (error) {
      this.releaseErrors.push(error);
    }
  }
}
