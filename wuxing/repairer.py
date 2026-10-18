"""修复器（Q12：失败分类→定向修复→仍败降级/终止）。

L2-4（FC 层3）升级：Repairer 从「文案级」→「指令级」：
  classify_failure(msg) -> 失败类别（param/contract/budget/tool/provider/unknown）
  repair_hint(cls, msg)  -> {action, hint} 结构化指令（可测可归因——模型可见）

失败类别语义：
  param    —— 参数错误（FC 层1 校验输出——旧归 contract 失真，L2-4 修正）
  contract —— 契约校验失败 → 校验器指出坏点，要求修正
  budget   —— 超预算           → 收紧护栏重试
  tool     —— 工具异常         → 切换执行方案
  provider —— provider 抖动（环境问题，非模型质量）→ 自动退避
"""
def classify_failure(msg: str) -> str:
    # L2-4（FC 层3）：param 类最先判定（"param:" 前缀——含 "missing"；
    # 旧顺序落 contract 分支：参数错误被误归为契约错误（归因失真））
    if "param:" in msg:
        return "param"
    if "stalled" in msg:
        # 真测裁决 W2：停滞=收敛失败（同 budget 修复语义：紧凑收敛，不扩预算）
        return "budget"
    if "budget" in msg or "预算" in msg:
        return "budget"
    if "tool" in msg or "工具" in msg:
        return "tool"
    if "contract" in msg or "契约" in msg or "missing" in msg:
        return "contract"
    # P12：provider 抖动（非 JSON/HTTP 4xx/5xx）
    if "provider" in msg or "429" in msg or "503" in msg or "500" in msg \
            or "502" in msg or "504" in msg or "JSON" in msg or "html" in msg.lower():
        return "provider"
    return "unknown"


# G7 v2（E2-2）：上下文溢出类错误（确定性——与 provider 抖动区分）
_OVERFLOW_PATTERNS = (
    "maximum context length",
    "context length",
    "context window",
    "too many tokens",
    "reduce the length",
    "token limit",
    "超出最大上下文",
    "上下文长度超出",
    "超过最大长度",
)


def is_context_overflow_error(exc) -> bool:
    """上下文溢出判据（溢出恢复用——保守；非此类不得触发重试）。"""
    text = f"{type(exc).__name__}: {exc}".lower()
    return any(p in text for p in _OVERFLOW_PATTERNS)


# L2-4：指令级修复提示（{action, hint}——替代纯文案；可测可归因）
_REPAIR_ACTIONS = {
    "param": lambda m: {"action": "fix_params",
                        "hint": f"参数错误：{m} —— 按工具 schema 修正参数后重试"},
    "contract": lambda m: {"action": "fix_output",
                           "hint": f"产出不符合契约（{m}）——修正建议：按 schema 补齐必填字段后重试"},
    "budget": lambda m: {"action": "converge",
                         "hint": "护栏收紧（轮数/调用减半）后重试——优先收敛而非扩预算"},
    "tool": lambda m: {"action": "switch_tool",
                       "hint": f"工具不可用（{m}）——切换到内置工具（write_artifact/read_dependency）后重试"},
    "provider": lambda m: {"action": "retry",
                           "hint": "provider 抖动（网络/防护页）——指数退避后重试（自动，无需人工介入）"},
    "unknown": lambda m: {"action": "stop",
                          "hint": "未知失败——标记失败并停止该单元（后续统一报告）"},
}


def repair_hint(cls: str, msg: str) -> dict:
    """失败分类 → 结构化修正指令（FC 层3 兜底——指令级而非文案级）。"""
    return _REPAIR_ACTIONS.get(cls, _REPAIR_ACTIONS["unknown"])(msg or "")


class Repairer:
    def repair(self, cls: str, msg: str) -> str:
        """（deprecated——文案级；L2-4 起用 repair_hint 指令级；保留向后兼容）。"""
        return repair_hint(cls, msg)["hint"]
