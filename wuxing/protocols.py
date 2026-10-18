"""引擎全部接口权威（Q10/Q11：一切可替换点均 Protocol 化）。

seam 三角色（借鉴 DSH）：Service Definition(本文件) + Provider(实现) + Consumer(使用方)。
"""
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


class CancellationToken:
    """协作式取消令牌（壳 P1 对齐项②）。

    线程安全（threading.Event）；取消在检查点生效（片段/轮次/工具批前），
    不 kill 线程——状态与已落盘产物保持自洽。
    """
    def __init__(self):
        self._event = threading.Event()

    def set(self) -> None:
        self._event.set()

    def is_set(self) -> bool:
        return self._event.is_set()


@dataclass
class DomainDefinition:
    """职责域契约（机制层常驻，Q3-C/Q5-B）。"""
    domain_id: str
    title: str
    input_schema: dict
    output_schema: dict
    tool_whitelist: tuple
    quality_notes: str
    prompt_skeleton: str
    success_markers: tuple = ()   # 合格输出的关键词标记（真 LLM 冒烟后契约化）
    artifact_kind: str = ""       # 产物 kind（plan/result/verdict/acceptance）
    conditional: bool = False     # 条件域（P8：低频域按需启用——user 2.5%）
    require_write: bool = False   # P0 T3：验收需【写工具成功】物证（execute）
    require_read: bool = False    # P0 T3：验收需【读工具调用】物证（verify）

@dataclass
class Artifact:
    """产物（Q8：文件为真理，清单为索引）。"""
    path: str                    # 工作区内相对路径
    kind: str                    # "plan"|"code"|"report"|...
    schema_hint: dict = field(default_factory=dict)
    producer_unit: str = ""      # 产出的执行单元
    depends_on: tuple = ()       # 依赖的产物路径

@dataclass
class UnitResult:
    """执行单元结果。"""
    unit_id: str
    domain_id: str
    status: str                  # "ok"|"failed"|"needs_confirm"
    artifacts: list = field(default_factory=list)
    logs: list = field(default_factory=list)
    error: str | None = None
    metrics: dict = field(default_factory=dict)  # P1 T1：{llm_calls, usage 汇总}
    deliverables: list = field(default_factory=list)  # S-C：真实交付物路径（写工具成功写出）
    reply: str = ""  # Task 4-1（流式专项）：单元最后一次助手文本（模型总体回复；纯工具轮为空）
    verdict_fail: bool = False   # L0-4（审查 B6）：verify 结论「不通过」标记——
                                 # 单元完成但验收未过 → 任务状态不得 done（机制裁决）
    failure_class: str = ""     # S1：失败分类 ""｜"provider"｜"budget"｜"stalled"
    pending_question: dict = field(default_factory=dict)  # E2-5（A10）：待答问题（挂起时登记）

@dataclass
class TaskResult:
    """任务级结果（engine.run_task 返回值）。"""
    task_text: str
    fragments: list
    units: list
    artifacts: list
    status: str                  # "done"|"partial"|"failed"|"pending"
    report: str = ""
    metrics: dict = field(default_factory=dict)  # P1 T4：任务级缓存/成本指标

class LlmProvider(ABC):
    """LLM 提供方（Q7：配置化路由 + 可选智脑；本 P 只用 Mock）。

    chat(messages, tools=None)：tools 为 OpenAI 兼容函数 schema 列表（P5）；
    不支持原生 tools 的实现可忽略该参数（返回纯文本，由 ToolCallingLlm 文本协议回退）。

    cache_capabilities() -> dict（P10 E4：服务端缓存能力声明——通用环境自适应）：
      server_prompt_cache: "anthropic"|"openai-completions"|"none"
    """
    @abstractmethod
    def chat(self, messages: list, tools: list | None = None) -> str: ...
    @abstractmethod
    def name(self) -> str: ...

    def spec(self) -> str:
        """可回构配置 spec（create_provider(spec()) 能重建同配置 provider）。

        P15 前置（D1c）：智脑记忆若只存 name()（如 openai-compat:gpt-4o、toolcall:...），
        读取侧 create_provider 无法回构——记录/回构必须走 spec 语义。
        """
        return self.name()

    def cache_capabilities(self) -> dict:
        """默认：无服务端缓存（客户端缓存兜底——pi 能力声明哲学）。"""
        return {"server_prompt_cache": "none"}

    def supports_native_tools(self) -> bool:
        """原生工具调用能力声明（L4/GLM 差分发现：双轨诱导——文本协议说明仅
        对不支持原生的 provider 注入，否则模型混用文本协议+中文参数名 → schema 拒绝）。
        默认 True（OpenAI/Anthropic 系真实 provider 均支持 tools 参数）。"""
        return True

@dataclass
class ToolResult:
    """工具执行结果（阶段 3 结构化——DST Consumer 协议参考；三态语义）。

    status:
      ok      正常完成（含业务性未命中，如 read 不存在——content 表达）
      blocked 被守卫/白名单拦截（不放行、不消耗 LLM 学习信号）
      error   执行异常（超时/IO/网络——需要修复或重试）
    """
    status: str = "ok"
    content: str = ""
    tool_name: str = ""
    error: str = ""
    # O2-2 P1：挂起式待决（如浏览器回环确认）——questions 进壳问题卡，
    # meta 随 pending_question 持久化（kind/pending_id 供决议路由）
    pending_questions: list = field(default_factory=list)
    pending_meta: dict = field(default_factory=dict)


class Tool(ABC):
    """统一工具接口（MCP/本地无差别，Q15）。

    reentrant：可重入工具（内部会执行其它工具，如 delegate）——不占全局
    并发额度（2026-09-11 分级放行设计：防外层占额度等内层 = 死锁）。
    """
    reentrant = False
    @abstractmethod
    def name(self) -> str: ...
    @abstractmethod
    def description(self) -> str: ...
    @abstractmethod
    def input_schema(self) -> dict: ...
    @abstractmethod
    def execute(self, **kwargs) -> str: ...

    # P3 T2：权限声明制（最小权限——DSH 教训：默认拒绝）
    # 工具必须声明至少一项能力；全 False = 未声明 → Registry 拦截
    def permission(self) -> dict:
        """权限声明（能力面）：{read, write, execute, network, destructive}。"""
        return {"read": False, "write": False, "execute": False,
                "network": False, "destructive": False}

    # E3-3（X6）：延迟加载标记（ToolSearch 池——不进提示词工具表；loader 置位）
    deferred = False

# P13 决策：LoopEngine 接口删除（Q14——自研轻量循环由 Runner 直接实现，
# 抽象从未接入实现/消费——接口形式主义；langGraph 后路保留在规格书 §3.2）