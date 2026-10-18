/**
 * 连接模型（纯逻辑）：URL 规范化 + 令牌换发 URL + 同源白名单。
 * 约定：base = scheme://host[:port][/path]（无尾斜杠）；origin = scheme://host[:port]。
 */
export class Connection {
  private readonly base: string;
  private readonly origin: string;

  private constructor(base: string, origin: string) {
    this.base = base;
    this.origin = origin;
  }

  static parse(raw: string): Connection | null {
    let text: string = raw.trim();
    if (text.length === 0) {
      return null;
    }
    if (!text.includes('://')) {
      text = 'http://' + text;
    }
    const m: RegExpMatchArray | null =
      text.match(/^(https?):\/\/(\[[^\]]+\]|[^\/:\s]+)(?::(\d+))?(\/[^?#\s]*)?$/i);
    if (m === null) {
      return null;
    }
    const scheme: string = m[1].toLowerCase();
    const host: string = m[2].toLowerCase();
    const port: string = m[3] ? ':' + m[3] : '';
    const path: string = (m[4] ?? '').replace(/\/$/, '');
    const origin: string = `${scheme}://${host}${port}`;
    return new Connection(origin + path, origin);
  }

  baseUrl(): string {
    return this.base;
  }

  originUrl(): string {
    return this.origin;
  }

  /** 首次访问 URL：<base>/?token=…（服务端换 HttpOnly cookie）。 */
  connectUrl(token: string): string {
    return `${this.base}/?token=${encodeURIComponent(token.trim())}`;
  }

  /** 导航白名单：仅同源。 */
  isInternal(url: string): boolean {
    return url === this.origin || url.startsWith(this.origin + '/');
  }
}
