/** 内置浏览器控制通道 · 纯 Node HTTP 主机（O2-2 P1）。
 *
 * 与 Electron 解耦：经 BrowserDriver 接口调用视图驱动（真实实现见 browser-view.ts，
 * 测试用假驱动）——本模块可在无 Electron 环境单测（node --test）。
 *
 * 安全面（第一道）：仅 127.0.0.1 · 仅 POST /cmd · Bearer token 恒时比较 ·
 * 请求体上限 · 命令白名单 · 错误一律结构化（不泄栈）。
 */
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";

import {
  DEFAULT_BROWSER_HOST,
  MAX_BODY_BYTES,
  PROTOCOL_VERSION,
  checkToken,
  failEnvelope,
  okEnvelope,
  parseRequest,
  validateClickArgs,
  validateEvaluateArgs,
  validateIdentityArgs,
  validateIdentityClearArgs,
  validateCloseArgs,
  validateTypeArgs,
  validateUrl,
  validateWaitArgs,
  type BrowserIdentity,
} from "./browser-protocol.ts";

export interface BrowserDriver {
  status(): Promise<Record<string, unknown>> | Record<string, unknown>;
  open(
    url: string, identity: BrowserIdentity,
  ): Promise<Record<string, unknown>> | Record<string, unknown>;
  snapshot(
    identity: BrowserIdentity,
  ): Promise<Record<string, unknown>> | Record<string, unknown>;
  click(
    args: Record<string, unknown>, identity: BrowserIdentity,
  ): Promise<Record<string, unknown>> | Record<string, unknown>;
  type(
    args: Record<string, unknown>, identity: BrowserIdentity,
  ): Promise<Record<string, unknown>> | Record<string, unknown>;
  wait(
    args: Record<string, unknown>, identity: BrowserIdentity,
  ): Promise<Record<string, unknown>> | Record<string, unknown>;
  evaluate(
    args: Record<string, unknown>, identity: BrowserIdentity,
  ): Promise<Record<string, unknown>> | Record<string, unknown>;
  screenshot(
    args: Record<string, unknown>, identity: BrowserIdentity,
  ): Promise<Record<string, unknown>> | Record<string, unknown>;
  close(
    identity: BrowserIdentity,
  ): Promise<Record<string, unknown>> | Record<string, unknown>;
  views(): Promise<Record<string, unknown>> | Record<string, unknown>;
  identityClear(
    key: string,
  ): Promise<Record<string, unknown>> | Record<string, unknown>;
}

export interface BrowserServerOptions {
  token: string;
  driver: BrowserDriver;
  host?: string;
  port?: number;
  requestTimeoutMs?: number;
  log?: (message: string) => void;
}

export interface BrowserServerHandle {
  endpoint: string;
  port: number;
  close(): Promise<void>;
}

type BodyResult =
  | { ok: true; body: string }
  | { ok: false; code: string; message: string };

function readBody(req: IncomingMessage, limit: number): Promise<BodyResult> {
  return new Promise((resolve) => {
    const chunks: Buffer[] = [];
    let size = 0;
    let overflow = false;
    req.on("data", (chunk: Buffer) => {
      size += chunk.length;
      if (size > limit) {
        overflow = true; // 超限后丢弃（不驻留内存），等 end 后统一回 413
        return;
      }
      chunks.push(chunk);
    });
    req.on("end", () => {
      if (overflow) {
        resolve({
          ok: false,
          code: "body-too-large",
          message: `请求体超限（>${limit} 字节）`,
        });
        return;
      }
      resolve({ ok: true, body: Buffer.concat(chunks).toString("utf8") });
    });
    req.on("error", () => {
      resolve({ ok: false, code: "read-error", message: "请求体读取失败" });
    });
  });
}

async function withTimeout<T>(
  run: () => Promise<T> | T,
  ms: number,
  label: string,
): Promise<T> {
  let timer: NodeJS.Timeout | undefined;
  try {
    return await Promise.race([
      (async () => run())(),
      new Promise<never>((_, reject) => {
        timer = setTimeout(
          () => reject(new Error(`${label} 超时（${ms}ms）`)),
          ms,
        );
      }),
    ]);
  } finally {
    if (timer !== undefined) clearTimeout(timer);
  }
}

export async function startBrowserServer(
  options: BrowserServerOptions,
): Promise<BrowserServerHandle> {
  const host = options.host ?? DEFAULT_BROWSER_HOST;
  const timeoutMs = options.requestTimeoutMs ?? 60_000;
  const log = options.log ?? (() => {});

  // P3（§11.2）→ v3（§11.5-② Q3=A）：每视图命令 FIFO 分片——
  // 同 identity.key 串行、异键并行；status/views/identity_clear 走全局链；
  // 校验失败的 4xx 不入队；单体失败不阻断后续（链上吞错续行）。
  const chains = new Map<string, Promise<void>>();
  const GLOBAL_CHAIN = "__global";
  function enqueue<T>(key: string, run: () => Promise<T>): Promise<T> {
    const prev = chains.get(key) ?? Promise.resolve();
    const next = prev.then(() => run());
    const tail = next.then(() => undefined, () => undefined);
    chains.set(key, tail);
    void tail.finally(() => {
      if (chains.get(key) === tail) chains.delete(key);
    });
    return next;
  }
  const exec = <T,>(
    key: string,
    label: string,
    run: () => Promise<T> | T,
  ): Promise<T> => enqueue(key, () => withTimeout(run, timeoutMs, label));

  const server = createServer((req, res) => {
    void handle(req, res);
  });
  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(options.port ?? 0, host, () => {
      server.removeListener("error", reject);
      resolve();
    });
  });
  const address = server.address();
  if (address === null || typeof address === "string") {
    await new Promise<void>((resolve) => server.close(() => resolve()));
    throw new Error("无法确定控制通道监听端口");
  }

  async function handle(
    req: IncomingMessage,
    res: ServerResponse,
  ): Promise<void> {
    const reply = (status: number, body: string): void => {
      res.writeHead(status, {
        "content-type": "application/json; charset=utf-8",
        "content-length": Buffer.byteLength(body),
      });
      res.end(body);
    };
    if (req.method !== "POST" || (req.url ?? "") !== "/cmd") {
      reply(404, failEnvelope("not-found", "仅支持 POST /cmd"));
      return;
    }
    if (!checkToken(req.headers.authorization, options.token)) {
      reply(401, failEnvelope("unauthorized", "token 无效"));
      return;
    }
    const body = await readBody(req, MAX_BODY_BYTES);
    if (!body.ok) {
      reply(413, failEnvelope(body.code, body.message));
      return;
    }
    const parsed = parseRequest(body.body);
    if (!parsed.ok) {
      reply(400, failEnvelope(parsed.code, parsed.message));
      return;
    }
    const { cmd, args } = parsed.request;
    const identOrReply = (): BrowserIdentity | null => {
      const v = validateIdentityArgs(args.identity);
      if (!v.ok) {
        reply(400, failEnvelope(v.code, v.message));
        return null;
      }
      return v.identity;
    };
    try {
      let result: Record<string, unknown>;
      switch (cmd) {
        case "status":
          result = {
            protocol: PROTOCOL_VERSION,
            ...(await exec(GLOBAL_CHAIN, "status", () => options.driver.status())),
          };
          break;
        case "views":
          result = await exec(GLOBAL_CHAIN, "views", () => options.driver.views());
          break;
        case "open": {
          const url = validateUrl(args.url);
          if (!url.ok) {
            reply(400, failEnvelope(url.code, url.message));
            return;
          }
          const ident = identOrReply();
          if (ident === null) return;
          result = await exec(ident.key, "open",
            () => options.driver.open(url.url, ident));
          break;
        }
        case "snapshot": {
          const ident = identOrReply();
          if (ident === null) return;
          result = await exec(ident.key, "snapshot",
            () => options.driver.snapshot(ident));
          break;
        }
        case "click": {
          const ident = identOrReply();
          if (ident === null) return;
          const v = validateClickArgs(args);
          if (!v.ok) {
            reply(400, failEnvelope(v.code, v.message));
            return;
          }
          result = await exec(ident.key, "click",
            () => options.driver.click(v.args, ident));
          break;
        }
        case "type": {
          const ident = identOrReply();
          if (ident === null) return;
          const v = validateTypeArgs(args);
          if (!v.ok) {
            reply(400, failEnvelope(v.code, v.message));
            return;
          }
          result = await exec(ident.key, "type",
            () => options.driver.type(v.args, ident));
          break;
        }
        case "wait": {
          const ident = identOrReply();
          if (ident === null) return;
          const v = validateWaitArgs(args);
          if (!v.ok) {
            reply(400, failEnvelope(v.code, v.message));
            return;
          }
          result = await exec(ident.key, "wait",
            () => options.driver.wait(v.args, ident));
          break;
        }
        case "evaluate": {
          const ident = identOrReply();
          if (ident === null) return;
          const v = validateEvaluateArgs(args);
          if (!v.ok) {
            reply(400, failEnvelope(v.code, v.message));
            return;
          }
          result = await exec(ident.key, "evaluate",
            () => options.driver.evaluate(v.args, ident));
          break;
        }
        case "screenshot": {
          const ident = identOrReply();
          if (ident === null) return;
          result = await exec(ident.key, "screenshot",
            () => options.driver.screenshot(args, ident));
          break;
        }
        case "close": {
          const v = validateCloseArgs(args);
          if (!v.ok) {
            reply(400, failEnvelope(v.code, v.message));
            return;
          }
          result = await exec(v.identity.key, "close",
            () => options.driver.close(v.identity));
          break;
        }
        case "identity_clear": {
          const v = validateIdentityClearArgs(args);
          if (!v.ok) {
            reply(400, failEnvelope(v.code, v.message));
            return;
          }
          result = await exec(GLOBAL_CHAIN, "identity_clear",
            () => options.driver.identityClear(v.key));
          break;
        }
        default:
          reply(400, failEnvelope("unknown-command", `未知命令：${String(cmd)}`));
          return;
      }
      reply(200, okEnvelope(result));
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      log(`[browser-server] ${cmd} 失败：${message}`);
      reply(500, failEnvelope("command-failed", message));
    }
  }

  log(`[browser-server] listening http://${host}:${address.port}`);
  return {
    endpoint: `http://${host}:${address.port}`,
    port: address.port,
    close: () =>
      new Promise<void>((resolve) => {
        server.close(() => resolve());
      }),
  };
}
