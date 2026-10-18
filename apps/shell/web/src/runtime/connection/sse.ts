/** SSE 客户端：解析（纯函数）+ 连接状态机（transport 可注入）。 */

export interface SseFrame {
  id?: string;
  event?: string;
  data: string;
}

/** 解析 SSE 文本块（可能含半帧）——返回完整帧与残余缓冲。 */
export function parseSseChunk(input: string): { frames: SseFrame[]; rest: string } {
  const buffer = input.replace(/\r\n/g, "\n");
  const frames: SseFrame[] = [];
  let rest = buffer;
  let boundary = rest.indexOf("\n\n");
  while (boundary !== -1) {
    const raw = rest.slice(0, boundary);
    rest = rest.slice(boundary + 2);
    const frame: SseFrame = { data: "" };
    const dataLines: string[] = [];
    for (const line of raw.split("\n")) {
      if (line === "" || line.startsWith(":")) continue;
      const colon = line.indexOf(":");
      const field = colon === -1 ? line : line.slice(0, colon);
      const value = colon === -1 ? "" : line.slice(colon + 1).replace(/^ /, "");
      if (field === "id") frame.id = value;
      else if (field === "event") frame.event = value;
      else if (field === "data") dataLines.push(value);
    }
    if (dataLines.length === 0 && frame.id === undefined && frame.event === undefined) {
      boundary = rest.indexOf("\n\n"); // 纯注释/心跳帧：不派发
      continue;
    }
    frame.data = dataLines.join("\n");
    frames.push(frame);
    boundary = rest.indexOf("\n\n");
  }
  return { frames, rest };
}

export type SseStatus = "connecting" | "open" | "closed";

export interface SseControlFrame {
  readonly type: "hello" | "resync_required";
  readonly data: Record<string, unknown>;
}

export interface SseConnectOptions {
  url: string;
  onOpen(): void;
  onError(): void;
  onMessage(data: string, event?: string, id?: string): void;
}

export interface SseTransport {
  close(): void;
}

export type SseTransportFactory = (options: SseConnectOptions) => SseTransport;

export interface SseClientOptions {
  baseUrl: string;
  path?: string;
  reconnectDelayMs?: number;
  transport?: SseTransportFactory;
  onEvent(envelope: unknown): void;
  onControl(frame: SseControlFrame): void;
  onStatus(status: SseStatus): void;
}

export interface SseClient {
  start(): void;
  stop(): void;
  lastSeq(): number;
  reconnectNow(): void;
}

function defaultTransport(options: SseConnectOptions): SseTransport {
  const source = new EventSource(options.url);
  source.onopen = () => { options.onOpen(); };
  source.onerror = () => { options.onError(); };
  source.onmessage = (event: MessageEvent<string>) => {
    options.onMessage(event.data, undefined, event.lastEventId);
  };
  const forward = (name: string) => (event: Event) => {
    const message = event as MessageEvent<string>;
    options.onMessage(message.data, name);
  };
  source.addEventListener("hello", forward("hello"));
  source.addEventListener("resync_required", forward("resync_required"));
  return {
    close() { source.close(); },
  };
}

function safeParse(raw: string): unknown {
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

export function createSseClient(options: SseClientOptions): SseClient {
  let lastSeq = 0;
  let lastEpoch: string | null = null;
  let running = false;
  let transport: SseTransport | null = null;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  const reconnectDelayMs = options.reconnectDelayMs ?? 1500;

  const url = (): string =>
    `${options.baseUrl}${options.path ?? "/api/v1/events"}?since=${lastSeq}`;

  const scheduleReconnect = (): void => {
    if (!running || reconnectTimer !== null) return;
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      connect();
    }, reconnectDelayMs);
  };

  const connect = (): void => {
    if (!running) return;
    options.onStatus("connecting");
    transport = (options.transport ?? defaultTransport)({
      url: url(),
      onOpen: () => { options.onStatus("open"); },
      onError: () => {
        options.onStatus("closed");
        transport?.close();
        transport = null;
        scheduleReconnect();
      },
      onMessage: (data, event, id) => {
        if (event === "hello" || event === "resync_required") {
          const parsed = safeParse(data);
          const record = (parsed && typeof parsed === "object" ? parsed : {}) as Record<string, unknown>;
          if (event === "hello") {
            const epoch = typeof record.epoch === "string" ? record.epoch : null;
            if (epoch !== null) {
              if (lastEpoch !== null && epoch !== lastEpoch) {
                lastSeq = 0; // 新 epoch：seq 域重置（服务重启后新事件不被去重丢弃）
              }
              lastEpoch = epoch;
            }
          }
          options.onControl({ type: event, data: record });
          return;
        }
        const envelope = safeParse(data);
        const seq = (envelope as { seq?: unknown } | null)?.seq;
        if (typeof seq === "number") {
          if (seq <= lastSeq) return; // 重复/旧序丢弃（连接层去重）
          lastSeq = seq;
        } else if (id && /^\d+$/.test(id)) {
          const numericId = Number(id);
          if (numericId <= lastSeq) return;
          lastSeq = numericId;
        }
        options.onEvent(envelope);
      },
    });
  };

  return {
    start() {
      if (running) return;
      running = true;
      connect();
    },
    stop() {
      running = false;
      if (reconnectTimer !== null) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
      transport?.close();
      transport = null;
      options.onStatus("closed");
    },
    lastSeq: () => lastSeq,
    reconnectNow() {
      if (!running) return;
      if (reconnectTimer !== null) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
      transport?.close();
      transport = null;
      connect();
    },
  };
}
