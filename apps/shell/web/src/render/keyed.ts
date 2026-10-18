/** keyed 列表：纯规划（plan）与 DOM 应用（apply）分离——规划纯函数可单测。 */

export interface KeyedPlan {
  readonly order: readonly string[];
  readonly inserts: readonly string[];
  readonly removes: readonly string[];
}

export function planKeyed(prev: readonly string[], next: readonly string[]): KeyedPlan {
  const prevSet = new Set(prev);
  const nextSet = new Set(next);
  return {
    order: [...next],
    inserts: next.filter((key) => !prevSet.has(key)),
    removes: prev.filter((key) => !nextSet.has(key)),
  };
}

export function applyKeyed(
  host: HTMLElement,
  plan: KeyedPlan,
  create: (key: string) => HTMLElement,
  update?: (key: string, node: HTMLElement) => void,
): void {
  const existing = new Map<string, HTMLElement>();
  for (const child of Array.from(host.children)) {
    const node = child as HTMLElement;
    const key = node.dataset.key;
    if (key) existing.set(key, node);
  }
  for (const key of plan.removes) {
    existing.get(key)?.remove();
    existing.delete(key);
  }
  for (const key of plan.order) {
    let node = existing.get(key);
    if (!node) {
      node = create(key);
      node.dataset.key = key;
      existing.set(key, node);
    } else if (update) {
      update(key, node);
    }
    host.appendChild(node); // 已存在节点 = 移动到队尾（相对顺序由 order 决定）
  }
}
