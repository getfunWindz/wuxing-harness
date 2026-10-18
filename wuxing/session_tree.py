"""会话树（任务历史树——2026-09-05 剩余清单项）。

数据来源（复用既有写路径——读取侧聚合，不新增写入）：
  - task_state.json：任务根（task_text/状态/碎片）
  - .wuxing/provenance.jsonl：单元 + delegate 子任务（parent 父子链——git commit 思想）
  - .wuxing/sessions/*.jsonl：单元会话存档计数（叶子信息量）
"""
import logging
import pathlib
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class TreeNode:
    id: str
    type: str                     # "task" | "unit" | "delegate"
    label: str
    status: str = ""
    domain: str = ""
    artifacts: list = field(default_factory=list)
    meta: dict = field(default_factory=dict)
    children: list = field(default_factory=list)

    def to_lines(self, prefix: str = "", is_last: bool = True) -> list:
        """文本渲染（CLI 输出形态——树形缩进）。"""
        connector = "" if not prefix else ("└─ " if is_last else "├─ ")
        status_txt = f" [{self.status}]" if self.status else ""
        domain_txt = f" ({self.domain})" if self.domain else ""
        lines = [f"{prefix}{connector}{self.label}{domain_txt}{status_txt}"]
        for i, c in enumerate(self.children):
            child_prefix = prefix + ("" if is_last and connector else "   ")
            child_prefix = prefix + ("   " if is_last else "│  ")
            if not prefix:
                child_prefix = ""
            lines.extend(c.to_lines(child_prefix, i == len(self.children) - 1))
        return lines


def build_task_tree(workdir: pathlib.Path) -> TreeNode | None:
    """从工作区聚合构建会话树；无任务状态 → None（容错）。"""
    wd = pathlib.Path(workdir)

    # 任务根（最新 run 状态优先，旧根级路径回退——任务级真相）
    from wuxing.state import latest_state_path
    state_path = latest_state_path(wd)
    if not state_path.exists():
        return None
    try:
        import json
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # 状态文件缺失/损坏 → None（视为无树可展开）
        return None
    from wuxing.provenance import task_hash
    root = TreeNode(id=f"task-{task_hash(state.get('task_text', ''))}",
                    type="task", label=state.get("task_text", "(未知任务)"),
                    status=state.get("status", "running"))

    # provenance 单元节点（父子链）
    from wuxing.provenance import ProvenanceLedger
    rows = ProvenanceLedger(wd / ".wuxing" / "provenance.jsonl").load()
    nodes = {}
    for row in rows:
        uid = row.get("unit_id", "")
        if not uid:
            continue
        node = TreeNode(
            id=uid,
            type="delegate" if uid.startswith("delegate-") else "unit",
            label=uid,
            status=row.get("status", ""),
            domain=row.get("domain", ""),
            artifacts=list(row.get("artifacts", []) or []),
            meta={"goal": row.get("goal", ""), "model": row.get("model", "")},
        )
        nodes[uid] = node
    # 挂接：parent 指向的节点（delegate 挂父单元；单元挂任务根）
    child_ids = set()
    for row in rows:
        uid = row.get("unit_id", "")
        parent_id = row.get("parent_id", "")
        node = nodes.get(uid)
        if node is None:
            continue
        if parent_id and parent_id in nodes:
            nodes[parent_id].children.append(node)
            child_ids.add(uid)
        else:
            root.children.append(node)
            child_ids.add(uid)

    # session 叶子信息（单元存档行数/消息数）
    sess_dir = wd / ".wuxing" / "sessions"
    if sess_dir.exists():
        for sp in sess_dir.iterdir():
            if sp.suffix != ".jsonl":
                continue
            unit_id = sp.stem
            node = nodes.get(unit_id)
            if node is not None:
                try:
                    lines = [l for l in sp.read_text(encoding="utf-8").splitlines()
                             if l.strip()]
                    node.meta["session_rounds"] = len(lines)
                except OSError as exc:
                    logger.debug("会话归档统计读取失败（不阻断）：%s", exc)

    # 状态覆盖：task_state 的 units 状态更权威（provenance 可能有重复行）
    for u in state.get("units", []):
        uid = u.get("unit_id")
        if uid in nodes and u.get("status"):
            nodes[uid].status = u["status"]
        elif uid and u.get("status"):
            root.children.append(TreeNode(id=uid, type="unit", label=uid,
                                          status=u["status"],
                                          domain=u.get("domain_id", ""),
                                          artifacts=[a.get("path") for a in
                                                     u.get("artifacts", [])]))
    return root


def find_by_hash(tree: TreeNode | None, task_hash: str) -> TreeNode | None:
    """按任务 hash 查询（内容寻址——根节点 id 含 hash 前缀）。"""
    if tree is None:
        return None
    if tree.id.endswith(task_hash):
        return tree
    for c in tree.children:
        found = find_by_hash(c, task_hash)
        if found is not None:
            return found
    return None
