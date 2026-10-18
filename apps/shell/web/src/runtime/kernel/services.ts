/** 能力缝：服务定义（Token）+ 提供/解析（Provider/Consumer 三角）。 */

export type Disposer = () => void;

export interface ServiceToken<T> {
  readonly id: string;
  /** 仅类型标记（运行时不存在） */
  readonly type?: T;
}

export function serviceToken<T>(id: string): ServiceToken<T> {
  return { id };
}

export class ServiceRegistry {
  private readonly values = new Map<string, unknown>();

  provide<T>(token: ServiceToken<T>, value: T): Disposer {
    if (this.values.has(token.id)) {
      throw new Error(`服务已注册：${token.id}`);
    }
    this.values.set(token.id, value);
    return () => {
      this.values.delete(token.id);
    };
  }

  has(token: ServiceToken<unknown>): boolean {
    return this.values.has(token.id);
  }

  resolve<T>(token: ServiceToken<T>): T {
    if (!this.values.has(token.id)) {
      throw new Error(`服务未注册：${token.id}`);
    }
    return this.values.get(token.id) as T;
  }

  tryResolve<T>(token: ServiceToken<T>): T | undefined {
    return this.values.get(token.id) as T | undefined;
  }
}
