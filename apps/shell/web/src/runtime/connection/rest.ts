/** REST 客户端（唯一出网入口——视图/服务不得直接 fetch）。 */

export type RestErrorKind = "network" | "http" | "timeout";

export class RestError extends Error {
  readonly kind: RestErrorKind;
  readonly status: number | undefined;
  readonly code: string | undefined;

  constructor(
    kind: RestErrorKind,
    message: string,
    status?: number,
    code?: string,
  ) {
    super(message);
    this.name = "RestError";
    this.kind = kind;
    this.status = status;
    this.code = code;
  }
}

export interface RestClient {
  get<T>(path: string): Promise<T>;
  post<T>(path: string, body?: unknown): Promise<T>;
}

/** 写入面（PUT/DELETE）——设置等写操作服务消费（P2）。 */
export interface WritableRestClient extends RestClient {
  put<T>(path: string, body?: unknown): Promise<T>;
  patch<T>(path: string, body?: unknown): Promise<T>;
  del<T>(path: string): Promise<T>;
}

export interface RestClientOptions {
  baseUrl: string;
  fetchLike?: typeof fetch;
  timeoutMs?: number;
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return null; // 非 JSON 响应体（空体/错误页）：按 null 处理，错误按状态码构造
  }
}

export function createRestClient(options: RestClientOptions): WritableRestClient {
  const doFetch = options.fetchLike ?? fetch;
  const timeoutMs = options.timeoutMs ?? 15_000;

  async function request<T>(
    method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE",
    path: string,
    body?: unknown,
  ): Promise<T> {
    const controller = new AbortController();
    const timer = setTimeout(() => { controller.abort(); }, timeoutMs);
    try {
      const init: RequestInit = {
        method,
        signal: controller.signal,
        headers: {
          ...(body === undefined ? {} : { "Content-Type": "application/json" }),
          ...(method === "GET" ? {} : { "X-Wuxing": "1" }),
        },
      };
      if (body !== undefined) {
        init.body = JSON.stringify(body);
      }
      const response = await doFetch(`${options.baseUrl}${path}`, init);
      const payload: unknown = await readJson(response);
      if (!response.ok) {
        const error = (payload as { error?: { code?: string; message?: string } } | null)?.error;
        throw new RestError("http", error?.message ?? `HTTP ${response.status}`,
          response.status, error?.code);
      }
      return payload as T;
    } catch (error) {
      if (error instanceof RestError) throw error;
      if ((error as { name?: string } | null)?.name === "AbortError") {
        throw new RestError("timeout", "请求超时");
      }
      throw new RestError("network", error instanceof Error ? error.message : "网络错误");
    } finally {
      clearTimeout(timer);
    }
  }

  return {
    get: <T>(path: string) => request<T>("GET", path),
    post: <T>(path: string, body?: unknown) => request<T>("POST", path, body),
    put: <T>(path: string, body?: unknown) => request<T>("PUT", path, body),
    patch: <T>(path: string, body?: unknown) => request<T>("PATCH", path, body),
    del: <T>(path: string) => request<T>("DELETE", path),
  };
}
