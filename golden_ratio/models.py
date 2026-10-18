"""核心数据结构：Node / DAG / Shape / Fragment / KeyToken（修订稿 §2 符号表）。"""
from dataclasses import dataclass, field


@dataclass
class Node:
    id: str
    text: str
    domain_dist: dict          # {领域: 置信度}，软路由用（§3.2）
    trades: list               # 工种集合
    complexity: str            # "low" | "mid" | "high"
    color_weight: float        # 优先级权重 w(n) ∈ (0,1]（颜色映射）
    deliverable: str           # "text" | "code" | "data" | "decision"
    weight_pts: float = 0.0    # IFPUG 复杂度分（difficulty 计算填充）


@dataclass
class DAG:
    nodes: list
    edges: list                # [(上游id, 下游id)]，A→B 表示 B 依赖 A

    @staticmethod
    def successors(dag, nid):
        return [b for a, b in dag.edges if a == nid]

    @staticmethod
    def predecessors(dag, nid):
        return [a for a, b in dag.edges if b == nid]

    @staticmethod
    def max_depth(dag):
        """最大依赖路径深度（节点数计），无环时等于拓扑序最长链。"""
        indeg = {n.id: 0 for n in dag.nodes}
        for a, b in dag.edges:
            indeg[b] += 1
        queue = [n.id for n in dag.nodes if indeg[n.id] == 0]
        depth = {nid: 1 for nid in queue}
        while queue:
            cur = queue.pop(0)
            for nxt in DAG.successors(dag, cur):
                indeg[nxt] -= 1
                depth[nxt] = max(depth.get(nxt, 0), depth[cur] + 1)
                if indeg[nxt] == 0:
                    queue.append(nxt)
        return max(depth.values(), default=0)

    @staticmethod
    def topological_order(dag):
        """Kahn 拓扑排序（并列节点按出现顺序）。"""
        indeg = {n.id: 0 for n in dag.nodes}
        for a, b in dag.edges:
            indeg[b] += 1
        queue = [n.id for n in dag.nodes if indeg[n.id] == 0]
        order = []
        while queue:
            cur = queue.pop(0)
            order.append(cur)
            for nxt in DAG.successors(dag, cur):
                indeg[nxt] -= 1
                if indeg[nxt] == 0:
                    queue.append(nxt)
        return order

    @staticmethod
    def avg_branching(dag):
        """平均分支度 = 边数 / 节点数。"""
        return len(dag.edges) / len(dag.nodes) if dag.nodes else 0.0

    @staticmethod
    def is_acyclic(dag):
        indeg = {n.id: 0 for n in dag.nodes}
        for a, b in dag.edges:
            indeg[b] += 1
        queue = [n.id for n in dag.nodes if indeg[n.id] == 0]
        seen = 0
        while queue:
            cur = queue.pop(0)
            seen += 1
            for nxt in DAG.successors(dag, cur):
                indeg[nxt] -= 1
                if indeg[nxt] == 0:
                    queue.append(nxt)
        return seen == len(dag.nodes)


@dataclass
class Shape:
    domain_dist: dict          # 任务级领域分布（各节点领域分布的加权和）
    trades: set                # 工种集
    difficulty: int            # L 1~5
    ds: float                  # 难度分
    struct: float              # 结构分
    coord_index: float         # 协调指数
    total_size: float          # 总规模 S
    fast_path: bool            # 是否走快路径
    total_effort: float = 0.0  # 任务总工时（8/80 缩放依据，difficulty 填充）
    entropy: float = 0.0       # 领域熵（绝对，T1b 协调指数依据；T1c 分桶 key 成分）


@dataclass
class KeyToken:
    word: str
    lang: str                  # "zh" | "en"
    score: float


@dataclass
class Fragment:
    fragment_id: str           # F-0001（Q4 循迹）
    stage: str                 # "segment" | "rebalance"
    node_ids: list
    text: str                  # 节点文本拼接（供分词）
    domain_dist: dict
    upstream: list = field(default_factory=list)
    downstream: list = field(default_factory=list)
    size: float = 0.0
    key_tokens: list = field(default_factory=list)
    # v4.0 关口前置条件补强（全面回顾 P1-2/P1-3）
    task_ref: str = ""              # 所属任务文本（关口分配上下文）
    difficulty: int = 0             # 任务难度档 L1~5（模型选择参考）
    total_effort: float = 0.0       # 任务总工时（模型选择/成本参考）
    deliverables: list = field(default_factory=list)  # 块内交付物类型（关口匹配）
