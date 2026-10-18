"""Fragment→域 确定性路由（Q5：开放标签聚合到封闭域——关键词规则，非 LLM 推理；
    映射规则待测试集验证阶段用数据校准）。"""
import jieba

RULES = [
    # 优先级：verify/plan 语义词先于 execute（真 LLM 冒烟发现：
    # “开发/实现”词会抢走验证/规划语义的碎片）
    ("verify", ("验证", "测试", "审查", "校验", "检查", "check", "test", "verif", "review")),
    ("plan",   ("方案", "规划", "计划", "路线", "design")),
    # user 收窄：专用短语（避免“用户系统”被误路由——“用户系统”应归 execute）
    ("user",   ("用户视角", "用户体验", "验收标准", "用户需求", "requirement")),
    ("execute",("实现", "开发", "编写", "撰写", "整理", "收集", "构建", "完成",
                "分析", "implement", "build", "write", "fix", "add")),
]

# REAL-3（真测 2026-09-26）：构造测试/样例资产是执行工作——「编写/创建/生成 + 测试/用例/test」
# 不得被验证语义抢走（如「创建 sample.txt；编写 test_wordcount.py；运行 pytest」）。
# 其余场景保持验证优先（test_verify_kw_not_stolen_by_execute：实现接口并验证登录 → verify）。
_ASSET_VERBS = ("编写", "撰写", "创建", "实现", "开发", "构建", "生成", "新增", "添加",
                "write", "create", "implement", "build", "add", "generate")
_TEST_NOUNS = ("测试", "用例", "test", "spec")


def _kw_hit(low: str, word: str) -> bool:
    """命中判定：英文词边界（\btest\b 不匹配 latest/contest），中文子串。"""
    if word and word.isascii():
        import re as _re
        return _re.search(r"\b" + _re.escape(word) + r"\b", low) is not None
    return word in low


def builds_test_assets(text: str) -> bool:
    """构造性动作 + 测试/用例对象（execute 语义——验收对象是测试资产本身）。"""
    low = str(text or "").lower()
    return (any(_kw_hit(low, v) for v in _ASSET_VERBS)
            and any(_kw_hit(low, n) for n in _TEST_NOUNS))

def extract_keywords(text: str) -> list:
    """jieba 分词（复用 golden_ratio 词法能力）。"""
    return [w for w in jieba.lcut(text) if len(w) >= 2]

def route_fragment(text: str, active: set | None = None) -> str:
    """Fragment→域 确定性路由。

    active：任务级启用域集（P8.1 条件域）——未启用域的命中回退到最近语义域。
    C5：英文词边界（\btest\b 等——'test' 不得命中 'latest'/'contest' 子串）。
    """
    low = text.lower()
    fallback = "execute"
    _asset_creation = builds_test_assets(low)
    for domain, words in RULES:
        if domain == "verify" and _asset_creation:
            continue  # 构造测试资产 → 执行语义（REAL-3）
        for w in words:
            if w and w.encode("ascii", "ignore").isascii() and w.isascii():
                # 英文词：词边界匹配（\b——防 latest/add 子串误路由）
                import re as _re
                if _re.search(r"\b" + _re.escape(w) + r"\b", low):
                    return _route_hit(domain, active, fallback)
            elif w in low:
                return _route_hit(domain, active, fallback)
    # 兜底 execute（P7 修正：默认“干活”域——原兜底 plan 导致 656/764 节点误归 plan，
    # 112 套件评估暴露；plan 只接明确规划词）
    if active is not None and "execute" not in active:
        return next((d for d in ("plan", "verify") if d in active), "execute")
    return "execute"


def _route_hit(domain: str, active: set | None, fallback: str) -> str:
    """命中域判定：条件域启用检查 + 回退。"""
    if active is None or domain in active:
        return domain
    # 条件域未启用 → 回退（默认 execute——干活域最近语义）
    candidates = [d for d in ("execute", "plan", "verify")
                  if d in (active or set())]
    return candidates[0] if candidates else fallback
