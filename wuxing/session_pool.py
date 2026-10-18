"""碎片会话延续（FSC）——跨轮工作流键匹配 + 三重成本闸门。

设计：docs/WUXING_碎片会话延续_FSC_设计_2026-09-11.md
键：domain + 目录/标签集合（Top-2 前缀，来自碎片文本路径提及 + 依赖产物路径
+ C 通道工作流标签）；匹配：同域**精确键相等**（方案2 用户裁决 2026-09-12——
推翻初稿 Jaccard，见设计修订记录）；保留 K 轮（用户裁决 4）；
闸门：单会话字符上限 / 复用次数上限 / 池总预算；无键不发动（保守）；
同键并发由 key_lock 串行（orchestrator 持有锁执行单元）。
"""
import re
import threading

_DIR_RE = re.compile(r"(?<![\w./\\-])([\w.-]+(?:/[\w.-]+)+)(?![\w./\\-])")
_EXT_RE = re.compile(r"\.[A-Za-z0-9]{1,8}$")
# C（用户裁决 2026-09-11）：显式工作流标签通道——plan 标注后碎片可直接键控
_TAG_RE = re.compile(r"(?:workstream[:：]|工作流[:：])\s*([\w\-./]+)")


def extract_dirs(*texts) -> set:
    """文本路径提及 → 目录前缀集合（文件去尾取父目录，再取 Top-2）。"""
    dirs = set()
    for t in texts:
        for m in _DIR_RE.finditer(str(t or "")):
            parts = m.group(1).strip("/").split("/")
            if len(parts) >= 2 and _EXT_RE.search(parts[-1]):
                parts = parts[:-1]  # 文件路径 → 取父目录（docs/api.md → docs）
            if parts:
                dirs.add("/".join(parts[:2]))
    return dirs


def extract_tags(*texts) -> set:
    """显式工作流标签（workstream:xxx / 工作流：xxx）——C 通道。"""
    tags = set()
    for t in texts:
        for m in _TAG_RE.finditer(str(t or "")):
            tags.add(m.group(1).strip("/"))
    return tags


def fsc_key(domain: str, frag_text: str, dep_paths: str):
    """工作流键 = (domain, 路径集合 ∪ 显式标签集合)；无键源 → None（不发动）。

    键源：碎片文本路径 / 依赖产物路径 / 显式工作流标签（C 通道）。
    """
    parts = extract_dirs(frag_text, dep_paths) | extract_tags(frag_text, dep_paths)
    if not parts:
        return None
    return (domain, frozenset(parts))


def _alnum_tokens(text: str) -> set:
    """词元集合（过滤纯标点——防「——」类 token 误配；jieba 缓存复用）。"""
    from wuxing.cache import _tokens_for_sim
    return {t for t in _tokens_for_sim(str(text or ""))
            if any(ch.isalnum() for ch in t)}


def extract_tag_contexts(text: str) -> list:
    """标签 + 上下文行（C 通道注入依据）——逐行扫描，去重保序（首行上下文）。"""
    out, seen = [], set()
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        for m in _TAG_RE.finditer(line):
            tag = m.group(1).strip("/")
            if tag and tag not in seen:
                seen.add(tag)
                out.append((tag, line))
    return out


def assign_tags(frags: list, items: list) -> dict:
    """标签 → 碎片分配（C 通道，A 阶段）：token 重叠取最高分；单标签全量兜底。

    - 多标签：各自寻最高分碎片（>0 才分配——宁缺毋滥，防强行合并幻觉）
    - 单标签：视为同一工作流——全量继承（使 execute 碎片继承标签）
    返回 {fragment_id: [tag, ...]}（保序）。
    """
    result = {f.get("fragment_id"): [] for f in frags}
    if not frags or not items:
        return result
    if len(items) == 1:
        tag = items[0][0]
        for f in frags:
            result[f.get("fragment_id")].append(tag)
        return result
    for tag, ctx in items:
        q = _alnum_tokens(ctx)
        best_fid, best = None, 0
        for f in frags:
            sim = len(q & _alnum_tokens(f.get("text", "")))
            if sim > best:
                best, best_fid = sim, f.get("fragment_id")
        if best_fid is not None and best > 0:
            result[best_fid].append(tag)
    return result


class FragmentSession:
    __slots__ = (
        "audit_pending",
        "audited",
        "chars",
        "created_round",
        "domain",
        "key",
        "last_round",
        "messages",
        "reuse",
        "unit_id",
    )

    def __init__(self, key, domain, messages, unit_id, current_round, reused):
        self.key = key
        self.domain = domain
        self.messages = messages
        self.unit_id = unit_id
        self.created_round = current_round
        self.last_round = current_round
        self.chars = sum(len(str(m.get("content", ""))) for m in messages)
        self.reuse = 1 if reused else 0
        self.audited = False        # 60% 审计已注入（一次）
        self.audit_pending = False  # 本次匹配时需注入审计指令


class SessionPool:
    def __init__(self, retention_rounds: int = 4,
                 max_session_chars: int = 65536, max_reuse: int = 3,
                 total_char_budget: int = 262144,
                 context_window: int = 200000,
                 audit_ratio: float = 0.6, switch_ratio: float = 0.8):
        self.retention_rounds = retention_rounds
        self.max_session_chars = max_session_chars
        self.max_reuse = max_reuse
        self.total_char_budget = total_char_budget
        # 上下文窗口机制（2026-09-11 设计）：会话单独计算占用率
        self.context_window = max(1, int(context_window))
        self.audit_ratio = audit_ratio
        self.switch_ratio = switch_ratio
        self._sessions = {}          # key -> FragmentSession（同键一条）
        self._locks = {}             # key -> threading.Lock（同键串行）
        self._guard = threading.Lock()
        self._events = []            # 窗口事件队列（编排层 drain 落 trace）
        self._switched = set()       # 刚触发切换的键（编排层 80% 询问判定）
        self._stats = {"matched": 0, "reused": 0, "evicted": 0,
                       "over_window": 0, "pool_size": 0,
                       "audited": 0, "switched": 0,
                       "keyed": 0, "unkeyed": 0}

    def key_lock(self, key) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(key, threading.Lock())

    def mark_audited(self, key):
        """审计指令已注入（一次）——清除待办，后续不重复。"""
        with self._guard:
            s = self._sessions.get(key)
            if s is not None:
                s.audited = True
                s.audit_pending = False
                self._stats["audited"] += 1

    def drain_events(self) -> list:
        """取走窗口事件（编排层落 trace）。"""
        with self._guard:
            ev, self._events = self._events, []
            return ev

    def match(self, domain, key, current_round):
        """匹配保留会话：同域 + 轮龄/字符/复用闸门内；窗口双阈值：
        60% 标记审计（一次）；80% 切换（不再延续 + 事件）。"""
        if key is None:
            return None
        with self._guard:
            s = self._sessions.get(key)
        if s is None or s.domain != domain:
            return None
        if current_round - s.last_round > self.retention_rounds:
            self._evict(s.key, "age")
            return None
        if s.chars > self.max_session_chars or s.reuse >= self.max_reuse:
            return None
        ratio = s.chars / self.context_window
        if ratio >= self.switch_ratio:
            # 80%：切换新会话（旧会话归档不复用；共享机制在新会话交接）
            self._evict(s.key, "switch")
            with self._guard:
                self._stats["switched"] += 1
                self._switched.add(s.key)
                self._events.append({"event": "session_switched", "key": s.key,
                                     "ratio": round(ratio, 3)})
            return None
        s.audit_pending = bool(ratio >= self.audit_ratio and not s.audited)
        with self._guard:
            self._stats["matched"] += 1
        return s

    def note_fragment(self, keyed: bool) -> None:
        """碎片键覆盖口径（A2）：每次单元运行登记一次。

        覆盖率 = keyed/(keyed+unkeyed)——mock 验收与真机报告共用同一口径。
        """
        with self._guard:
            self._stats["keyed" if keyed else "unkeyed"] += 1

    def consume_switched(self, key) -> bool:
        """取走该键的「刚发生切换」标记（编排层 80% 询问判定——至多一次）。

        B4（六轮审查）：设计 §4——auto_confirm=False 时应询问用户；
        该标记使编排层可区分「未命中」与「切换」。
        """
        with self._guard:
            if key in self._switched:
                self._switched.discard(key)
                return True
            return False

    def retain(self, key, domain, messages, unit_id, current_round, reused=False):
        """保留（或更新）会话——延续时继承创建轮与复用计数。"""
        if key is None:
            return None
        msgs = [dict(m) for m in messages]
        old = self._sessions.get(key)
        s = FragmentSession(key, domain, msgs, unit_id, current_round, reused)
        if reused and old is not None:
            s.created_round = old.created_round
            s.reuse = old.reuse + 1
            # B1（六轮审查）：审计「一次」语义跨换代保持——retain 新建对象
            # 若不继承 audited，60% 审计会在每次延续时重复注入
            s.audited = old.audited
        with self._guard:
            self._sessions[key] = s
            self._stats["reused"] += 1 if reused else 0
            self._evict_budget()
            self._stats["pool_size"] = len(self._sessions)
            # C1（六轮审查）：统计自增必须在 _guard 内（并发口径）
            if s.chars > self.max_session_chars * 0.6:
                self._stats["over_window"] += 1
        return s

    def _evict_locked(self, key):
        """淘汰（调用方持 _guard）。"""
        if self._sessions.pop(key, None) is not None:
            self._stats["evicted"] += 1
            self._stats["pool_size"] = len(self._sessions)

    def _evict(self, key, reason):
        with self._guard:
            self._evict_locked(key)

    def _evict_budget(self):
        """池总预算淘汰（调用方必须持 _guard——避免重入死锁）。"""
        while (sum(s.chars for s in self._sessions.values())
               > self.total_char_budget) and self._sessions:
            oldest = min(self._sessions.values(), key=lambda x: x.last_round)
            self._evict_locked(oldest.key)

    def stats(self) -> dict:
        with self._guard:
            self._stats["pool_size"] = len(self._sessions)
            return dict(self._stats)
