/** 服务进程启动参数解析（纯逻辑，env 注入）。 */

export interface ServiceCommand {
  cmd: string;
  args: string[];
}

export const DEFAULT_HOST = "127.0.0.60";
export const DEFAULT_PORT = 8723;

export function resolveServiceCommand(
  env: NodeJS.ProcessEnv,
  port: number,
): ServiceCommand {
  const python = (env.WUXING_PYTHON ?? "").trim() || "python";
  const override = (env.WUXING_SERVICE_ARGS ?? "").trim();
  if (override) {
    return { cmd: python, args: override.split(/\s+/).filter(Boolean) };
  }
  return {
    cmd: python,
    args: ["-m", "wuxing.cli", "shell", "serve", "--port", String(port)],
  };
}

export function readPort(env: NodeJS.ProcessEnv): number {
  const raw = (env.WUXING_PORT ?? "").trim();
  if (!raw) {
    return DEFAULT_PORT;
  }
  const parsed = Number(raw);
  return Number.isInteger(parsed) && parsed > 0 && parsed < 65536
    ? parsed
    : DEFAULT_PORT;
}

export function healthUrl(host: string, port: number): string {
  return `http://${host}:${port}/health`;
}
