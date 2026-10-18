/** Electron 主进程（P0 骨架）：单实例 → 确保 Python 服务 → 窗口加载前端。
 *
 * 环境变量：
 *   WUXING_PYTHON        Python 解释器（默认 `python`）
 *   WUXING_SERVICE_ARGS  服务命令参数覆盖（如假引擎：
 *                        `e2e/shell/serve_fake.py 8723`）
 *   WUXING_PORT          服务端口（默认 8723）
 *   WUXING_REPO_ROOT     仓库根（默认由 __dirname 上溯四级推导）
 */
import { app, BrowserWindow, dialog, ipcMain, shell } from "electron";
import { spawn, type ChildProcess } from "node:child_process";
import { randomBytes } from "node:crypto";
import {
  appendFileSync,
  createWriteStream,
  mkdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import path from "node:path";

import { startBrowserServer, type BrowserServerHandle } from "./browser-server";
import { createBrowserViewDriver, type BrowserViewDriver } from "./browser-view";
import {
  DEFAULT_HOST,
  healthUrl,
  readPort,
  resolveServiceCommand,
} from "./service";

const HEALTH_POLL_MS = 300;
const HEALTH_REUSE_TIMEOUT_MS = 800;
const HEALTH_STARTUP_TIMEOUT_MS = 20_000;

// userData/日志路径稳定为应用名（无论 `electron .` 还是直接指定入口文件）
app.setName("wuxing-shell");

let serviceChild: ChildProcess | null = null;
let mainWindow: BrowserWindow | null = null;
let browserHost: BrowserServerHandle | null = null;
let browserDriver: BrowserViewDriver | null = null;

function repoRoot(): string {
  const override = (process.env.WUXING_REPO_ROOT ?? "").trim();
  return override || path.resolve(__dirname, "..", "..", "..", "..");
}

function logDir(): string {
  const dir = path.join(app.getPath("userData"), "logs");
  mkdirSync(dir, { recursive: true });
  return dir;
}

function log(line: string): void {
  try {
    appendFileSync(
      path.join(logDir(), "main.log"),
      `[${new Date().toISOString()}] ${line}\n`,
    );
  } catch {
    // 日志失败不影响主流程
  }
}

async function pingHealth(
  host: string,
  port: number,
  timeoutMs: number,
): Promise<boolean> {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    try {
      const res = await fetch(healthUrl(host, port), {
        signal: AbortSignal.timeout(1000),
      });
      if (res.ok) {
        return true;
      }
    } catch {
      // 未就绪——继续轮询
    }
    await new Promise((resolve) => setTimeout(resolve, HEALTH_POLL_MS));
  }
  return false;
}

function startService(port: number): ChildProcess {
  const { cmd, args } = resolveServiceCommand(process.env, port);
  log(`spawn: ${cmd} ${args.join(" ")} (cwd=${repoRoot()})`);
  const child = spawn(cmd, args, {
    cwd: repoRoot(),
    windowsHide: true,
    stdio: ["ignore", "pipe", "pipe"],
  });
  const stream = createWriteStream(path.join(logDir(), "service.log"), {
    flags: "a",
  });
  child.stdout?.on("data", (chunk: Buffer) => stream.write(chunk));
  child.stderr?.on("data", (chunk: Buffer) => stream.write(chunk));
  child.on("exit", (code, signal) => {
    log(`service exited code=${String(code)} signal=${String(signal)}`);
    stream.end();
  });
  return child;
}

async function ensureService(port: number): Promise<boolean> {
  if (await pingHealth(DEFAULT_HOST, port, HEALTH_REUSE_TIMEOUT_MS)) {
    log(`reuse existing service on ${DEFAULT_HOST}:${port}`);
    return true;
  }
  serviceChild = startService(port);
  const ready = await pingHealth(DEFAULT_HOST, port, HEALTH_STARTUP_TIMEOUT_MS);
  if (!ready) {
    log("service startup timeout");
  }
  return ready;
}

function startPath(): string {
  const raw = (process.env.WUXING_START_PATH ?? "/").trim();
  if (raw === "" || raw === "/") return "/";
  const normalized = raw.startsWith("/") ? raw : `/${raw}`;
  return normalized.endsWith("/") ? normalized : `${normalized}/`;
}

function createWindow(port: number): void {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1024,
    minHeight: 700,
    title: "WUXING 无形",
    backgroundColor: "#f7f4ee",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  void mainWindow.loadURL(`http://${DEFAULT_HOST}:${port}${startPath()}`);
  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

/** O2-2：内置浏览器控制通道（127.0.0.61 专用回环别名 + token）。
 *
 * 启动失败不阻塞壳主功能（工具侧 loud 降级）——诚实记录日志。
 * 通道文件兜底（`~/.wuxing/browser_channel.json`，0600）：服务复用
 * （已有 8723 实例未带 env）时 Python 端仍能发现端点。
 */
function channelFilePath(): string {
  return path.join(app.getPath("home"), ".wuxing", "browser_channel.json");
}

async function startBrowserHost(): Promise<void> {
  try {
    const token = randomBytes(32).toString("hex");
    browserDriver = createBrowserViewDriver({
      getWindow: () => mainWindow,
      log,
    });
    browserHost = await startBrowserServer({
      token,
      driver: browserDriver,
      requestTimeoutMs: 30_000,
      log,
    });
    // env：子进程继承（先于 ensureService 调用）；文件：服务复用兜底
    process.env.WUXING_BROWSER_ENDPOINT = browserHost.endpoint;
    process.env.WUXING_BROWSER_TOKEN = token;
    const file = channelFilePath();
    mkdirSync(path.dirname(file), { recursive: true });
    writeFileSync(
      file,
      JSON.stringify({
        version: 1,
        endpoint: browserHost.endpoint,
        token,
        pid: process.pid,
      }),
      { encoding: "utf8", mode: 0o600 },
    );
    log(`browser channel ${browserHost.endpoint} (file=${file})`);
  } catch (error) {
    log(`browser host 启动失败：${String(error)}`);
  }
}

function stopBrowserHost(): void {
  try {
    browserDriver?.dispose();
  } catch {
    // 退出清理尽力而为
  }
  browserDriver = null;
  if (browserHost !== null) {
    void browserHost.close().catch(() => undefined);
    browserHost = null;
  }
  try {
    const file = channelFilePath();
    const raw = JSON.parse(readFileSync(file, "utf8")) as { pid?: number };
    if (raw.pid === process.pid) rmSync(file, { force: true });
  } catch {
    // 不存在/损坏 → 忽略
  }
}

const gotLock = app.requestSingleInstanceLock();

if (!gotLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) {
        mainWindow.restore();
      }
      mainWindow.focus();
    }
  });

  app.setAppUserModelId("com.wuxing.shell");

  // A6（W1-6）：本地打开（系统默认程序）——绝对路径校验在主场；工作区白名单由渲染层把关。
  // 返回 "" 成功 / 错误文案（诚实回传，不静默）。
  ipcMain.handle("wuxing:open-path", async (_event, target: unknown) => {
    const file = typeof target === "string" ? target.trim() : "";
    if (file === "" || !path.isAbsolute(file)) return "invalid path";
    try {
      return await shell.openPath(file);
    } catch (error) {
      return String(error);
    }
  });

  app
    .whenReady()
    .then(async () => {
      const port = readPort(process.env);
      log(`app ready (port=${port})`);
      await startBrowserHost();
      const ready = await ensureService(port);
      if (!ready) {
        dialog.showErrorBox(
          "WUXING 服务启动失败",
          "无法连接本地服务。\n请手动运行 `wuxing shell serve` 后重试。",
        );
        app.quit();
        return;
      }
      createWindow(port);
    })
    .catch((error: unknown) => {
      log(`fatal: ${String(error)}`);
      app.quit();
    });

  app.on("window-all-closed", () => {
    app.quit();
  });

  app.on("before-quit", () => {
    stopBrowserHost();
    if (serviceChild) {
      log("killing service child");
      serviceChild.kill();
      serviceChild = null;
    }
  });
}
