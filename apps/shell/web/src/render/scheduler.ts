/** 微任务批渲染调度器（可注入调度函数以便单测）。 */

export interface Scheduler {
  schedule(task: () => void): void;
  flush(): void;
}

export function createScheduler(
  schedule: (callback: () => void) => void = (callback) => { queueMicrotask(callback); },
): Scheduler {
  const queue: Array<() => void> = [];
  let scheduled = false;
  const flush = (): void => {
    scheduled = false;
    const tasks = queue.splice(0, queue.length);
    for (const task of tasks) task();
  };
  return {
    schedule(task) {
      queue.push(task);
      if (!scheduled) {
        scheduled = true;
        schedule(flush);
      }
    },
    flush,
  };
}
