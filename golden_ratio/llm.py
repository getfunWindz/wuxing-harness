"""LLM 客户端抽象（Q6：mock/真 LLM 只换实现不换签名）。MockLLM 为确定性脚本化响应。"""
from abc import ABC, abstractmethod
from typing import ClassVar


class LLMClient(ABC):
    """LLM 客户端抽象（Q6：mock/真 LLM 只换实现不换签名）。数据契约：

    - shape_task(task_text) -> {"nodes": [...], "edges": [[a,b],...], "total_size": float}
      节点字段：id/text/domain_dist(非空正数置信度)/trades(非空)/complexity(low|mid|high)/
      deliverable(text|code|data|decision)/color_weight((0,1])；edges 引用存在、无环、DAG 连通。
      输出必须过 validate_shape_output（shape.py 已接入；非法输出触发一次重试）。
    - merge_nodes(node_infos) -> [[id,...],...]
      输入 [{"id","domain","deliverable","share","effort"}]（segment 构造）；
      输出须覆盖全部节点、不重复、收缩依赖图无环（否则 ValueError，segment.py 校验）。
    - rebalance_suggest(fragment_info) -> {"moves": [{"from","to","node_ids"},...]}
      迁移建议可为空（空 = 行为与确定性规则一致）；from/to 必须存在、node_ids 属于 from。
      建议必须基于 fragment_info（当前状态）；无效/过时建议被跳过（降级不中断）。
    - score_keys(tokens) -> {word: score}
      分数为数值，可替代 TF 规则分；异常时调用方回退规则分。

    接入状态（v5）：四个方法均已进入真实调用链（shape/segment/rebalance/keyify），
    由 cfg.llm_merge_enabled / llm_rebalance_enabled / llm_key_scoring_enabled 控制，
    默认关闭走确定性规则。
    """
    @abstractmethod
    def shape_task(self, task_text): ...
    @abstractmethod
    def merge_nodes(self, node_infos): ...
    @abstractmethod
    def rebalance_suggest(self, fragment_info): ...
    @abstractmethod
    def score_keys(self, tokens): ...


class MockLLM(LLMClient):
    """内置 4 个确定性任务模板；未知任务回退到单节点模板。call_count 供成本指标统计。"""

    TEMPLATES: ClassVar[dict] = {
        "写一封请假邮件": {
            "nodes": [{"id": "n1", "text": "撰写请假邮件", "domain_dist": {"写作": 0.9},
                       "trades": ["创作"], "complexity": "low", "deliverable": "text", "color_weight": 0.5}],
            "edges": [], "total_size": 1.0,
        },
        "写一份季度报告": {
            "nodes": [
                {"id": "n1", "text": "收集业务数据", "domain_dist": {"分析": 0.6}, "trades": ["调研"],
                 "complexity": "mid", "deliverable": "text", "color_weight": 0.5},
                {"id": "n2", "text": "分析数据", "domain_dist": {"分析": 0.7}, "trades": ["分析"],
                 "complexity": "mid", "deliverable": "text", "color_weight": 0.7},
                {"id": "n3", "text": "撰写季度报告", "domain_dist": {"写作": 0.8}, "trades": ["创作"],
                 "complexity": "mid", "deliverable": "text", "color_weight": 0.8},
            ],
            "edges": [["n1", "n2"], ["n2", "n3"]], "total_size": 3.0,
        },
        "开发一个带用户系统的网站": {
            "nodes": [
                {"id": "n1", "text": "需求分析", "domain_dist": {"分析": 0.7}, "trades": ["分析"],
                 "complexity": "low", "deliverable": "decision", "color_weight": 0.6},
                {"id": "n2", "text": "数据库设计", "domain_dist": {"数据": 0.8}, "trades": ["实现"],
                 "complexity": "high", "deliverable": "data", "color_weight": 0.9},
                {"id": "n3", "text": "后端接口开发", "domain_dist": {"编程": 0.9}, "trades": ["实现"],
                 "complexity": "high", "deliverable": "code", "color_weight": 0.9},
                {"id": "n4", "text": "前端页面开发", "domain_dist": {"编程": 0.9}, "trades": ["实现"],
                 "complexity": "high", "deliverable": "code", "color_weight": 0.8},
                {"id": "n5", "text": "接口测试", "domain_dist": {"编程": 0.6}, "trades": ["测试"],
                 "complexity": "mid", "deliverable": "code", "color_weight": 0.5},
                {"id": "n6", "text": "部署文档", "domain_dist": {"写作": 0.7}, "trades": ["创作"],
                 "complexity": "low", "deliverable": "text", "color_weight": 0.3},
            ],
            "edges": [["n1", "n2"], ["n2", "n3"], ["n3", "n4"], ["n3", "n5"], ["n4", "n6"], ["n5", "n6"]],
            "total_size": 6.0,
        },
        "分析两款产品并选择一款": {
            "nodes": [
                {"id": "n1", "text": "调研两款产品", "domain_dist": {"分析": 0.6}, "trades": ["调研"],
                 "complexity": "mid", "deliverable": "text", "color_weight": 0.6},
                {"id": "n2", "text": "对比功能与成本", "domain_dist": {"分析": 0.8}, "trades": ["分析"],
                 "complexity": "mid", "deliverable": "decision", "color_weight": 0.8},
            ],
            "edges": [["n1", "n2"]], "total_size": 2.0,
        },
    }

    def __init__(self):
        self.call_count = 0

    def _hit(self):
        self.call_count += 1

    def shape_task(self, task_text):
        self._hit()
        import copy
        return copy.deepcopy(self.TEMPLATES.get(task_text, self.TEMPLATES["写一封请假邮件"]))

    def merge_nodes(self, node_infos):
        self._hit()
        return [[n["id"]] for n in node_infos]

    def rebalance_suggest(self, fragment_info):
        self._hit()
        return {"moves": []}

    def score_keys(self, tokens):
        self._hit()
        return {t: 1.0 / (i + 1) for i, t in enumerate(tokens)}
