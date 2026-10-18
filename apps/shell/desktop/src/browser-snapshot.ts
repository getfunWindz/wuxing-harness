/** 内置浏览器 · AX 树 → 行式快照（O2-2 P1；纯函数，零 Electron 依赖）。 */

export interface AxNodeLike {
  nodeId?: string;
  ignored?: boolean;
  role?: { value?: string } | null;
  name?: { value?: string } | null;
  backendDOMNodeId?: number;
}

export interface SnapshotRef {
  nodeId?: string;
  backendNodeId?: number;
  role: string;
  name: string;
}

export interface SnapshotResult {
  lines: string[];
  refs: Record<string, SnapshotRef>;
  truncated: boolean;
  total: number;
  /** P2：跨快照单调编号游标——下次快照以它作 startRef（换代不重置，旧 ref 自然失效）。 */
  nextRef: number;
}

/** 交互元素（可点击/可输入——分配 ref 供后续操作）。 */
const INTERACTIVE_ROLES = new Set([
  "button",
  "link",
  "textbox",
  "searchbox",
  "checkbox",
  "radio",
  "switch",
  "slider",
  "spinbutton",
  "combobox",
  "listbox",
  "option",
  "menuitem",
  "menuitemcheckbox",
  "menuitemradio",
  "tab",
]);

const NAME_MAX = 80;
const DEFAULT_MAX_LINES = 400;

function clip(text: string): string {
  if (text.length <= NAME_MAX) return text;
  return `${text.slice(0, NAME_MAX - 1)}…`;
}

/** AX 树 → 行式快照（`- role "name" [ref=eN]`）。
 *
 * 过滤：ignored / 空 role / none|presentation；无名且非交互 → 丢弃（结构骨架由具名节点承载）。
 * 截断：行数超 maxLines → truncated=true（调用方另做 token 上限）。
 * P2：ref 编号从 startRef 续编（跨快照单调）——返回 nextRef 作为下次游标。
 */
export function simplifyAxTree(
  nodes: AxNodeLike[],
  options?: { maxLines?: number; startRef?: number },
): SnapshotResult {
  const maxLines = options?.maxLines ?? DEFAULT_MAX_LINES;
  const lines: string[] = [];
  const refs: Record<string, SnapshotRef> = {};
  let total = 0;
  let refSeq = Math.max(0, Math.floor(options?.startRef ?? 0));
  for (const node of nodes) {
    if (node === null || node === undefined || node.ignored === true) continue;
    const role = String(node.role?.value ?? "").trim();
    if (role === "" || role === "none" || role === "presentation") continue;
    const name = clip(String(node.name?.value ?? "").trim());
    const interactive = INTERACTIVE_ROLES.has(role);
    if (name === "" && !interactive) continue;
    total += 1;
    if (lines.length >= maxLines) continue;
    let line = `- ${role}${name === "" ? "" : ` "${name}"`}`;
    if (interactive) {
      refSeq += 1;
      const ref = `e${refSeq}`;
      refs[ref] = {
        nodeId: node.nodeId,
        backendNodeId: node.backendDOMNodeId,
        role,
        name,
      };
      line += ` [ref=${ref}]`;
    }
    lines.push(line);
  }
  return { lines, refs, truncated: total > lines.length, total, nextRef: refSeq };
}
