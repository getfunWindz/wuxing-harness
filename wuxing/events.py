"""事件流契约（P3：壳层进度/确认面板的数据基础；引擎→壳唯一事件通道）。"""
from dataclasses import dataclass, field


@dataclass
class UnitStarted:
    unit_id: str
    domain_id: str

@dataclass
class UnitDone:
    unit_id: str
    domain_id: str
    status: str          # "ok"|"failed"
    failure_class: str = ""   # S1-C：""|"provider"|"budget"|"stalled"（呈现分类）

@dataclass
class UnitAutoRetry:
    """S1-A：自动恢复可见性（同 provider 重试 / 降级链换候选）。"""
    unit_id: str
    domain_id: str
    kind: str = "retry"      # "retry" | "fallback"
    attempt: int = 1         # retry：第几次同候选重试
    candidate: int = 0       # fallback：切换后的候选序号
    model: str = ""

@dataclass
class ArtifactWritten:
    unit_id: str
    path: str
    kind: str

@dataclass
class TaskDone:
    status: str          # "done"|"partial"|"failed"|"cancelled"

@dataclass
class TaskCancelled:
    """任务取消（壳 P1 对齐项②）：协作式取消在各检查点生效后发出。"""

@dataclass
class ProgressReport:
    """进度心跳（壳 P1 对齐项⑤）：模型自报进度（节奏定义权在模型）。

    非固定定时器——未自报则壳回退事件驱动进度；不做假进度条。
    """
    unit_id: str
    domain_id: str
    stage: str = ""
    eta: str = ""

@dataclass
class UnitNeedsConfirm:
    unit_id: str
    domain_id: str
    reason: str = ""
    # M7 #7（A2）：影响清单——{tools, deliverables, depends, summary}
    impact: dict = field(default_factory=dict)
    # 重大优化清单 #2（A′）：结构化四要素视图（壳侧统一渲染；缺省回退 reason）
    view: dict = field(default_factory=dict)

@dataclass
class UnitNeedsAnswer:
    """E2-5（A10）：执行中提问挂起（内容级信息补充——与确认门边界：不改准入链）。

    questions：[{title, options, multi}]（1-3 题；首选项=推荐答案语义由壳展示）。
    """
    unit_id: str
    domain_id: str
    question_id: str
    questions: list = field(default_factory=list)
    reason: str = ""
    # 重大优化清单 #2：来源分型（""=模型提问 / "browser_access"=机制生成）
    kind: str = ""

@dataclass
class QuestionAnswered:
    """E2-5（A10）：答复回执（审计对 question_asked/question_answered）。"""
    unit_id: str
    question_id: str
    answer: str = ""
    source: str = "text"    # "option" | "text"

@dataclass
class UnitStateChanged:
    """P4 T1：单元状态机事件（Pi V2 标准——每个状态转换可观测）。

    states: idle→thinking→tool_executing→waiting→done/failed
    """
    unit_id: str
    domain_id: str
    state: str

@dataclass
class UnitConfirmed:
    """（deprecated——P13 标注）确认回放事件：定义但当前无 emit 消费，
    恢复续跑完整回放为 P7 之后的功能。"""
    unit_id: str
    approve: bool
    reason: str = ""


@dataclass
class SafetyBlocked:
    """安全拦截（壳 UI 阶段 4 · 对齐项⑪）——danger_guard / MCP 权限拦截
    以流内警示卡呈现（非弹窗）。"""
    unit_id: str
    domain_id: str
    tool: str
    command: str = ""
    reason: str = ""


@dataclass
class FscAudit:
    """FSC 60% 审计阈值事件（壳 UI 阶段 4 · 对齐项⑩）——审计指令已注入。"""
    unit_id: str
    domain_id: str
    ratio: float = 0.0


@dataclass
class FscSwitch:
    """FSC 80% 会话切换阈值事件（对齐项⑩）——旧会话归档，新会话重开。"""
    unit_id: str
    domain_id: str
    ratio: float = 0.0


@dataclass
class UnitReasoning:
    """R4-3：单元思维链事件（LLM 轮次 reasoning 文本——展示/观测用，
    不参与模型消息构造；每轮一条，文本封顶截断）。"""
    unit_id: str
    domain_id: str
    round: int = 0
    text: str = ""


@dataclass
class UnitReasoningDelta:
    """思维链流式增量事件（专项 Task 2）：LLM 思考文本的**增量**片段（非累计快照）。

    前端按 (unit_id, round) 追加渲染；单条思考累计 10k 封顶——超限由引擎
    发一条「已截断」提示并停止后续增量；整段仍以 UnitReasoning 收口（兼容旧前端）。
    """
    unit_id: str
    domain_id: str
    round: int = 0
    text: str = ""


@dataclass
class NeedsDesign:
    """循迹设计信号（双模式批 3 · 设计 §5.2）：地图不可用——本次运行未进入执行管线，
    设计轮已产出（阶段/轮次/问题清单可见）。"""
    phase: str = ""
    round: int = 0
    questions: list = field(default_factory=list)
    map_path: str = ""
    map_hash: str = ""
    reason: str = ""


@dataclass
class DesignPhaseChanged:
    """设计阶段迁移事件（二期批 1 · 软编排）：每次阶段推进可观测。"""
    session: str = ""
    from_phase: str = ""
    to_phase: str = ""
    round: int = 0


@dataclass
class MapWritten:
    """地图写入事件（二期批 1）：WUXING.md 内容变化（write_map 或文件被改写）。"""
    path: str = ""
    hash: str = ""


@dataclass
class DecisionTicketChanged:
    """决策票据事件（二期批 2）：创建/关闭（关闭=决策已入地图、票据即弃）。"""
    session: str = ""
    id: str = ""
    status: str = ""      # "open" | "closed"
    statement: str = ""


@dataclass
class SpecWritten:
    """规格写入事件（二期批 3）：.wuxing/specs/<slug>.md 生成/更新。"""
    path: str = ""
    slug: str = ""
    hash: str = ""


@dataclass
class ImplTicketChanged:
    """实施票据事件（二期批 4）：提议/发布/状态变更。"""
    id: str = ""
    status: str = ""
    spec: str = ""


# ---------------- E3-2（P1）：生命周期事件（扩展钩子时机面） ----------------

@dataclass
class SubagentStarted:
    """E3-2：子代理（delegate）启动——委托生命周期观测（父单元链）。"""
    parent_unit_id: str = ""
    goal: str = ""
    domain: str = ""


@dataclass
class SubagentStopped:
    """E3-2：子代理（delegate）结束——status=子单元终态（异常路径 error）。"""
    parent_unit_id: str = ""
    goal: str = ""
    domain: str = ""
    status: str = ""
    artifacts: int = 0


@dataclass
class PreCompact:
    """E3-2：LLM 摘要压缩尝试前（G7 链；机械链投影不发射）。"""
    unit_id: str = ""
    domain_id: str = ""
    from_round: int = 0
    to_round: int = 0
    source_tokens: int = 0


@dataclass
class PostCompact:
    """E3-2：LLM 摘要压缩结果——status=written|rejected|degraded。"""
    unit_id: str = ""
    domain_id: str = ""
    from_round: int = 0
    to_round: int = 0
    status: str = ""
    summary_tokens: int = 0


@dataclass
class UserPromptSubmit:
    """E3-2：单元提示装配完成（提交模型前）——钩子可返回 additional_context 注入。"""
    unit_id: str = ""
    domain_id: str = ""
    prompt: str = ""
