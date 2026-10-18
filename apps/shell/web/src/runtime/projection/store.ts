/** 投影存储：宿主唯一权威、seq 单调（旧序拒绝）、可重置（epoch 变更）。 */

export type ProjectionListener<T> = (value: T) => void;

export interface Projection<T> {
  get(): T;
  /** seq 大于已应用序号才生效——返回是否应用 */
  apply(seq: number, updater: (current: T) => T): boolean;
  seed(value: T, seq?: number): void;
  reset(): void;
  subscribe(listener: ProjectionListener<T>): () => void;
}

export function createProjection<T>(initial: T): Projection<T> {
  let value = initial;
  let lastSeq = -1;
  const listeners = new Set<ProjectionListener<T>>();
  const emit = (): void => {
    for (const listener of [...listeners]) listener(value);
  };
  return {
    get: () => value,
    apply(seq, updater) {
      if (seq <= lastSeq) return false;
      lastSeq = seq;
      value = updater(value);
      emit();
      return true;
    },
    seed(next, seq) {
      value = next;
      if (seq !== undefined && seq > lastSeq) lastSeq = seq;
      emit();
    },
    reset() {
      lastSeq = -1;
      value = initial;
      emit();
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => { listeners.delete(listener); };
    },
  };
}
