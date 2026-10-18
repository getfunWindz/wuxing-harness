/** UI Slots：单一注册 API + 声明者授权（未声明渲染 = 加载期失败）+ 可逆注册。 */
import type { Disposer } from "./services.ts";

export interface SlotEntry {
  readonly id: string;
  readonly deps?: readonly string[];
  readonly render: (host: HTMLElement, props: unknown) => Disposer | void;
}

export class SlotRegistry {
  private readonly entries = new Map<string, Map<string, SlotEntry>>();
  private readonly declarations = new Map<string, Set<string>>();

  /** 组件声明「我会渲染该 slot」——返回撤销。 */
  declare(slot: string, owner: string): Disposer {
    let owners = this.declarations.get(slot);
    if (!owners) {
      owners = new Set();
      this.declarations.set(slot, owners);
    }
    if (owners.has(owner)) {
      throw new Error(`slot 重复声明：${owner} -> ${slot}`);
    }
    owners.add(owner);
    return () => {
      owners.delete(owner);
    };
  }

  register(slot: string, entry: SlotEntry): Disposer {
    let bucket = this.entries.get(slot);
    if (!bucket) {
      bucket = new Map();
      this.entries.set(slot, bucket);
    }
    if (bucket.has(entry.id)) {
      throw new Error(`slot 条目重复：${slot}/${entry.id}`);
    }
    bucket.set(entry.id, entry);
    return () => {
      bucket?.delete(entry.id);
    };
  }

  /** 渲染：owner 必须已声明；条目按注册顺序渲染，返回逆序释放。 */
  render(slot: string, owner: string, host: HTMLElement, props: unknown): Disposer {
    const owners = this.declarations.get(slot);
    if (!owners?.has(owner)) {
      throw new Error(`未声明的 slot 渲染：${owner} -> ${slot}`);
    }
    const disposers: Disposer[] = [];
    for (const entry of this.entries.get(slot)?.values() ?? []) {
      const disposer = entry.render(host, props);
      if (typeof disposer === "function") disposers.push(disposer);
    }
    return () => {
      while (disposers.length > 0) {
        const disposer = disposers.pop();
        if (disposer) disposer();
      }
    };
  }

  entryIds(slot: string): string[] {
    return [...(this.entries.get(slot)?.keys() ?? [])];
  }
}
