/** 图标注册表（外观复现 A12）：31 枚线性 SVG（24×24，stroke=currentColor；旧壳 icons.js 同源）。
    纪律：单个功能点「图标或文字」二选一，不并列；禁止 emoji（静态守卫测试）。
    注：旧壳含 <rect>/<circle> 的图标在此等价转写为 path 数据（svgIcon 只生成 path）。 */

const P = {
  workspace: [
    "M5 5h14a2 2 0 012 2v10a2 2 0 01-2 2H5a2 2 0 01-2-2V7a2 2 0 012-2z",
    "M3 9h18",
  ],
  task: ["M5 6h14M5 12h14M5 18h9"],
  running: ["M12 5a7 7 0 100 14 7 7 0 000-14z"],
  pending: ["M12 3l9 18H3z"],
  done: ["M5 13l4 4L19 7"],
  failed: ["M6 6l12 12M18 6L6 18"],
  cancelled: ["M6 12h12"],
  settings: [
    "M12 9a3 3 0 100 6 3 3 0 000-6z",
    "M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M19.1 4.9L17 7M7 17l-2.1 2.1",
  ],
  recycle: ["M4 7h16M9 7V5h6v2M6 7l1 13h10l1-13"],
  skill: ["M12 3l2.5 5.5L20 9l-4 4 1 6-5-3-5 3 1-6-4-4 5.5-.5z"],
  mcp: ["M9 3v6M15 3v6M6 9h12v4a6 6 0 01-12 0z"],
  usage: ["M4 20V10M10 20V4M16 20v-7M22 20H2"],
  artifact: ["M6 3h9l4 4v14H6z", "M14 3v5h5"],
  session: ["M4 5h16v11H8l-4 4z"],
  log: ["M5 4h14v16H5z", "M8 8h8M8 12h8M8 16h5"],
  search: ["M11 5a6 6 0 100 12 6 6 0 000-12z", "M20 20l-4.5-4.5"],
  add: ["M12 5v14M5 12h14"],
  close: ["M6 6l12 12M18 6L6 18"],
  collapse: ["M9 6l6 6-6 6"],
  export: ["M12 3v12M7 10l5 5 5-5M5 21h14"],
  copy: [
    "M10 8h8a2 2 0 012 2v8a2 2 0 01-2 2h-8a2 2 0 01-2-2v-8a2 2 0 012-2z",
    "M16 8V6a2 2 0 00-2-2H6a2 2 0 00-2 2v8a2 2 0 002 2h2",
  ],
  rename: ["M4 20h16M14 4l6 6-9 9H5v-6z"],
  archive: ["M3 6h18v4H3zM5 10v10h14V10M10 14h4"],
  help: [
    "M12 3a9 9 0 100 18 9 9 0 000-18z",
    "M9.5 9a2.5 2.5 0 114 2c-.8.6-1.5 1-1.5 2M12 16h.01",
  ],
  command: ["M9 9h6v6H9zM9 9H7a2 2 0 110-4h2zM15 9h2a2 2 0 100-4h-2zM9 15H7a2 2 0 100 4h2zM15 15h2a2 2 0 110 4h-2z"],
  more: [
    "M12 3.5a1.5 1.5 0 100 3 1.5 1.5 0 000-3z",
    "M12 10.5a1.5 1.5 0 100 3 1.5 1.5 0 000-3z",
    "M12 17.5a1.5 1.5 0 100 3 1.5 1.5 0 000-3z",
  ],
  notice: [
    "M12 3a5 5 0 00-5 5v4l-1.5 3h13L17 12V8a5 5 0 00-5-5z",
    "M10 18a2 2 0 004 0",
  ],
  clip: ["M21 11.5l-8.4 8.4a5.5 5.5 0 01-7.8-7.8l8.6-8.6a3.6 3.6 0 015.1 5.1l-8.6 8.6a1.8 1.8 0 01-2.5-2.5l7.9-7.9"],
  return: ["M20 6v5a4 4 0 01-4 4H6", "M10 11l-4 4 4 4"],
  brain: [
    "M12 4a3.5 3.5 0 00-3.2 4.9A3.2 3.2 0 006.6 14a3.5 3.5 0 003 4.8A3.5 3.5 0 0012 21",
    "M12 4a3.5 3.5 0 013.2 4.9A3.2 3.2 0 0117.4 14a3.5 3.5 0 01-3 4.8A3.5 3.5 0 0112 21",
    "M12 4v17",
  ],
  reports: ["M6 3h9l4 4v14H6z", "M9 13h6M9 17h6M9 9h4"],
} as const satisfies Record<string, readonly string[]>;

/** 注册表（断言/遍历用）。 */
export const ICON_REGISTRY = P;
export const ICON_NAMES = Object.keys(P);

/** 命名导出（调用点使用；与旧壳同名）。 */
export const ICON_WORKSPACE = P.workspace;
export const ICON_TASK = P.task;
export const ICON_RUNNING = P.running;
export const ICON_PENDING = P.pending;
export const ICON_DONE = P.done;
export const ICON_FAILED = P.failed;
export const ICON_CANCELLED = P.cancelled;
export const ICON_SETTINGS = P.settings;
export const ICON_RECYCLE = P.recycle;
export const ICON_SKILL = P.skill;
export const ICON_MCP = P.mcp;
export const ICON_USAGE = P.usage;
export const ICON_ARTIFACT = P.artifact;
export const ICON_SESSION = P.session;
export const ICON_LOG = P.log;
export const ICON_SEARCH = P.search;
export const ICON_ADD = P.add;
export const ICON_CLOSE = P.close;
export const ICON_CHEVRON = P.collapse;
export const ICON_EXPORT = P.export;
export const ICON_COPY = P.copy;
export const ICON_RENAME = P.rename;
export const ICON_ARCHIVE = P.archive;
export const ICON_HELP = P.help;
export const ICON_COMMAND = P.command;
export const ICON_MORE = P.more;
export const ICON_BELL = P.notice;
export const ICON_CLIP = P.clip;
export const ICON_RETURN = P.return;
export const ICON_BRAIN = P.brain;
export const ICON_REPORTS = P.reports;
