"""碎片间缓存共享（2026-09-06 用户核心愿景——快准省的协作杠杆）。

L1 FileCache：产物内容注入缓存（一次读取+截断——多碎片重复读同一产物免 I/O）。
L3 SharedContext：任务级共享区——已完成碎片的三要素（有向增量——只注入后续碎片）：
  - deliverable_analysis：交付物分析（收口文本截断 500）
  - tool_sequence：任务实现的工具调用顺序（logs [tool] 行）
  - fingerprint：碎片特征值（fragment hash + 域——供循迹）
全部确定性提取（机制裁决——不依赖 LLM）；容量上限（防 prompt 膨胀）。
"""
import hashlib
import pathlib
import threading


class FileCache:
    """产物内容缓存（L1：read+截断——进程内确定性；脏读语义=快照约束）。

    B5（审查）：缓存原语拆分——get/put（纯内存，路径由调用方正确解析——
    原 read(path) 直接读盘：相对路径无 workspace 语义（读 CWD——依赖注入
    全部失效）；read 保留向后兼容（截断语义），新路径走 get/put。
    """

    def __init__(self, max_chars: int = 1000, max_entries: int = 64):
        self.max_chars = max_chars
        self.max_entries = max_entries
        self._cache = {}
        self._lock = threading.Lock()

    def get(self, path: str) -> str | None:
        """只读缓存（不读盘——由调用方解析路径后填充）。"""
        with self._lock:
            return self._cache.get(path)

    def put(self, path: str, content: str) -> None:
        """写入缓存（LRU 逐出——容量不无界）。"""
        with self._lock:
            if len(self._cache) >= self.max_entries and path not in self._cache:
                self._cache.pop(next(iter(self._cache)))
            self._cache[path] = content

    def invalidate(self, path: str) -> None:
        """失效单条目（写入边界调用——保持脏读快照语义的同时避免跨单元
        陈旧读；真测 REAL-4：单元重写产物后后续注入必须读新内容）。"""
        with self._lock:
            self._cache.pop(path, None)

    def read(self, path: str) -> str | None:
        """（back-compat）读盘+截断缓存——相对路径无 workspace 语义，新代码用 get/put。"""
        with self._lock:
            if path in self._cache:
                return self._cache[path]
        try:
            content = pathlib.Path(path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            # 读不到/解码失败 → None（共享文件跳过，不注入）
            return None
        if len(content) > self.max_chars:
            content = content[:self.max_chars] + "…"
        with self._lock:
            if len(self._cache) >= self.max_entries and path not in self._cache:
                self._cache.pop(next(iter(self._cache)))
            self._cache[path] = content
        return content

    def clear(self):
        with self._lock:
            self._cache = {}


class SharedContext:
    """任务级共享区（L3——三要素；有向增量：仅已完成碎片 → 后续碎片）。"""

    ANALYZE_LIMIT = 500
    MEMBER_LIMIT = 5

    def __init__(self, max_chars: int = 2048):
        self.max_chars = max_chars
        self._records = []   # [{fragment_id, domain, deliverable_analysis, tool_sequence, fingerprint}]
        self._lock = threading.Lock()

    def record(self, result, fragment_key: str, ws=None) -> dict | None:
        """碎片完成后记录三要素（确定性提取；失败碎片也记录——归因供循迹）。"""
        if result is None:
            return None
        # 工具顺序（logs [tool] 行）
        PREFIXES = ("[tool]", "[tool:error]", "[guard]", "[warn]")
        seq = [l for l in (getattr(result, "logs", None) or [])
               if l.startswith(PREFIXES)]
        # 交付物分析：真实交付物或契约产物内容（截断）
        analysis = ""
        candidates = list(getattr(result, "deliverables", None) or []) + \
            [a.path for a in (getattr(result, "artifacts", None) or [])]
        if candidates and ws is not None:
            content = ws.read(candidates[0]) or ""
            analysis = content[:self.ANALYZE_LIMIT]
        rec = {
            "fragment_id": getattr(result, "unit_id", ""),
            "domain": getattr(result, "domain_id", ""),
            "status": getattr(result, "status", ""),
            "deliverable_analysis": analysis,
            "tool_sequence": "\n".join(seq[-self.MEMBER_LIMIT:]),
            "fingerprint": {
                "fragment": fragment_key or "",
                "hash": hashlib.sha256((fragment_key or "").encode("utf-8")).hexdigest()[:8],
                "domain": getattr(result, "domain_id", ""),
                "status": getattr(result, "status", ""),
            },
        }
        with self._lock:
            self._records = [r for r in self._records
                             if r["fragment_id"] != rec["fragment_id"]]
            self._records.append(rec)
        return rec

    def for_next(self, current_fragment_id: str) -> str:
        """共享段文本（供后续碎片注入——过滤自身/未完成；容量上限）。"""
        parts = []
        for r in self._records:
            if r["fragment_id"] == current_fragment_id:
                continue
            if r.get("status") not in ("ok", "failed"):
                continue
            head = f"[碎片 {r['fragment_id']} {r['domain']}/{r['status']} 经验]"
            body = []
            if r["deliverable_analysis"]:
                body.append(f"交付物分析：{r['deliverable_analysis'][:200]}")
            if r["tool_sequence"]:
                body.append(f"工具顺序：{r['tool_sequence'][:200]}")
            if r["fingerprint"]["hash"]:
                body.append(f"特征值：{r['fingerprint']['hash']}（域 {r['domain']}）")
            parts.append(head + "\n" + "\n".join(body))
        text = "\n\n".join(parts)
        return text[:self.max_chars] if len(text) > self.max_chars else text
