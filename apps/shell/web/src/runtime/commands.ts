/** 命令总线：统一 pending/success/failure 生命周期——失败必可见（禁静默）。 */

export type CommandState = "pending" | "success" | "failure";

export interface CommandEvent {
  readonly name: string;
  readonly state: CommandState;
  readonly error?: string;
}

export interface CommandBus {
  run<T>(name: string, task: () => Promise<T>): Promise<T>;
  subscribe(listener: (event: CommandEvent) => void): () => void;
  pendingCount(): number;
}

export function createCommandBus(onFailure?: (event: CommandEvent) => void): CommandBus {
  const listeners = new Set<(event: CommandEvent) => void>();
  let pending = 0;
  const emit = (event: CommandEvent): void => {
    for (const listener of [...listeners]) listener(event);
    if (event.state === "failure") onFailure?.(event);
  };
  return {
    async run<T>(name: string, task: () => Promise<T>): Promise<T> {
      pending += 1;
      emit({ name, state: "pending" });
      try {
        const result = await task();
        pending -= 1;
        emit({ name, state: "success" });
        return result;
      } catch (error) {
        pending -= 1;
        emit({
          name,
          state: "failure",
          error: error instanceof Error ? error.message : String(error),
        });
        throw error;
      }
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => { listeners.delete(listener); };
    },
    pendingCount: () => pending,
  };
}
