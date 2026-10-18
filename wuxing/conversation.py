"""会话状态（B 模式：同一任务内多轮交互——append-only 历史 + 交付物累计）。

用户裁决（2026-09-07）：会话式交互用于吃满上下文窗口并保持缓存命中——
历史段逐轮追加（前缀只增不改——服务端前缀缓存的前提），交付物跨轮复用。

设计红线：
  1. append-only：历史轮次内容永不改写（前缀缓存的前提）
     ——唯一例外：终态重写（v35 用户裁决·专项同批）——确认/续跑完成后
     把 pending 快照行补全为终态（summary/reply/thoughts/artifacts）；
     user_text/round/ts 不变，其余历史行零触碰
  2. 确定性：同状态同 context_text 输出（跨碎片逐字节一致）
  3. 有界：context_text 超限从最旧轮次折叠（保留最近）
  4. 韧性：JSONL 单行损坏跳过（与 session/provenance 惯例一致）
"""
import json
import logging
import os
import pathlib
import threading
import time

logger = logging.getLogger(__name__)

# 跨实例文件互斥（每 run 一个 Engine/ConversationState 实例——同文件多实例时
# 追加与重写必须串行，否则重写的读-改-写会吞掉并发追加行）
_FILE_LOCKS: dict = {}
_FILE_LOCKS_GUARD = threading.Lock()


def _file_lock(path) -> threading.Lock:
    key = str(pathlib.Path(path).resolve())
    with _FILE_LOCKS_GUARD:
        lock = _FILE_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _FILE_LOCKS[key] = lock
        return lock

_TURN_TEXT_LIMIT = 200
_TURN_SUMMARY_LIMIT = 120


def _turn_round(turn: dict) -> int:
    try:
        return int(turn.get("round") or 0)
    except (TypeError, ValueError):
        # 轮次字段缺失/非法 → 0：读侧容错，不阻断会话加载
        return 0


_BRANCH_MODE_LABEL = {"redo": "重做", "continue": "继续"}


def is_branch_row(row: dict) -> bool:
    """承接行判定（G1）：分支派生时写入的元数据行——不占轮次、不渲染为轮。"""
    return str((row or {}).get("type") or "") == "branch"


def is_compaction_row(row: dict) -> bool:
    """压缩行判定（G7）：历史压缩元数据行——不占轮次、不渲染为轮。"""
    return str((row or {}).get("type") or "") == "compaction"


def _compaction_block(row: dict) -> str:
    """压缩块（context_text 注入；置历史首位——覆盖最旧轮次）。"""
    summary = " ".join(str(row.get("summary") or "").split())
    return (f"[历史压缩] 第{row.get('from_round', '?')}-"
            f"{row.get('to_round', '?')}轮摘要：{summary}")


def _branch_block(row: dict) -> str:
    """承接块（context_text 注入；仅在有摘要时输出——G1）。"""
    mode = _BRANCH_MODE_LABEL.get(str(row.get("mode") or ""),
                                  str(row.get("mode") or ""))
    summary = " ".join(str(row.get("summary") or "").split())
    return (f"[分支承接] 来源《{row.get('source', '')}》"
            f"第 {row.get('from_round', '?')} 轮（{mode}）；"
            f"被放弃路径小结：{summary}")


def turn_block(turn: dict) -> str:
    """单轮上下文块（context_text 与投影共用——保证「投影=实际」）。"""
    text = turn.get("user_text", "")[:_TURN_TEXT_LIMIT]
    summary = turn.get("summary", "")[:_TURN_SUMMARY_LIMIT]
    arts = turn.get("artifacts", [])
    block = f"第{turn.get('round', '?')}轮：{text}"
    if arts:
        block += f"\n  交付物：{', '.join(arts[:5])}"
    # B2：产物内容摘录（跨轮继承——前缀只追加）
    for e in (turn.get("artifact_excerpts") or [])[:3]:
        exc = str(e.get("excerpt", ""))[:200]
        if exc:
            block += f"\n  产物摘录[{e.get('path', '')}]：{exc}"
    if summary:
        block += f"\n  小结：{summary}"
    return block


class ConversationState:
    """会话轮次历史（持久化：workdir/.wuxing/conversation.jsonl）。"""

    def __init__(self, path):
        self.path = pathlib.Path(path)
        self._lock = threading.Lock()
        self.turns = []
        self._load()
        self._edits = self._load_edits()

    def _load_edits(self) -> dict:
        """投影层编辑（context-edits.jsonl；append-only，同轮最新生效）。

        记录格式：{conversation, round, op: "omit"|"replace", content?, ts}。
        仅影响上下文投影（context_text/prev_digest/turn_views）——会话日志零改写。
        """
        path = self.path.parent / "context-edits.jsonl"
        edits: dict = {}
        if not path.is_file():
            return edits
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return edits
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue  # 坏行跳过（韧性惯例）
            if str(row.get("conversation") or "") != self.path.name:
                continue
            try:
                rnd = int(row.get("round"))
            except (TypeError, ValueError):
                continue
            op = str(row.get("op") or "")
            if op == "omit":
                edits[rnd] = {"op": "omit", "content": ""}
            elif op == "replace":
                edits[rnd] = {"op": "replace",
                              "content": str(row.get("content") or "")}
            elif op == "restore":
                # G3：回到原文（append-only 审计保留；同轮后续仍可再叠加）
                edits.pop(rnd, None)
        return edits

    def _load(self):
        if not self.path.exists():
            return
        try:
            for line in self.path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    self.turns.append(json.loads(line))
                except json.JSONDecodeError:
                    continue  # 单行损坏跳过（韧性惯例）
        except OSError:
            self.turns = []

    def append_turn(self, round_no: int, user_text: str, artifacts: list,
                    summary: str = "", artifact_excerpts: list | None = None,
                    fragment_digest: str = "", unit: str = "",
                    reply: str = "", thoughts: list | None = None) -> dict:
        """追加一轮（append-only——不覆写历史）。

        artifact_excerpts（B2）：本轮产物内容摘录 [{path, excerpt}]——
        跨轮上下文继承原料（前缀只追加不变）。
        fragment_digest（FSC 低匹配回退 2026-09-12）：本轮全部碎片上下文压缩
        （供下一轮低匹配碎片作前缀注入——确定性 + 缓存友好）。
        unit（碎片会话后半程 2026-09-22）：碎片会话内提交的轮次标记——
        该轮不计入主会话上下文窗口（context_text/prev_digest 跳过）；
        空串不落键（旧轮次字节不变——缓存前缀纪律）。
        reply/thoughts（Task 4-2 流式专项）：模型总体回复 + 本轮思维链
        （完成轮卡片/历史回看数据面）；**空不落键**（旧行字节形状不变——
        且不入模型上下文——turn_block 不投影这两键）。
        """
        row = {"round": round_no, "user_text": str(user_text or ""),
               "artifacts": [str(a) for a in (artifacts or [])],
               "summary": str(summary or ""), "ts": round(time.time(), 3)}
        if unit:
            row["unit"] = str(unit)
        if reply:
            row["reply"] = str(reply)
        if thoughts:
            row["thoughts"] = [
                {"unit_id": str(t.get("unit_id", "")),
                 "round": int(t.get("round", 0) or 0),
                 "text": str(t.get("text", ""))[:4000]}
                for t in thoughts][:30]
        if fragment_digest:
            row["fragment_digest"] = str(fragment_digest)
        if artifact_excerpts:
            row["artifact_excerpts"] = [
                {"path": str(e.get("path", "")),
                 "excerpt": str(e.get("excerpt", ""))[:400]}
                for e in artifact_excerpts][:5]
        with self._lock:
            self.turns.append(row)
            with _file_lock(self.path):
                try:
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                    with open(self.path, "a", encoding="utf-8") as f:
                        f.write(json.dumps(row, ensure_ascii=False) + "\n")
                except OSError as exc:
                    logger.debug("会话回合持久化失败（不阻断）：%s", exc)
        return row

    def append_row(self, row: dict) -> dict:
        """追加元数据行（G7 压缩行等——同锁；不参与轮次编号）。"""
        with self._lock:
            self.turns.append(row)
            with _file_lock(self.path):
                try:
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                    with open(self.path, "a", encoding="utf-8") as f:
                        f.write(json.dumps(row, ensure_ascii=False) + "\n")
                except OSError as exc:
                    logger.debug("会话元数据行持久化失败（不阻断）：%s", exc)
        return row

    def rewrite_turn(self, round_no: int, *, summary: str | None = None,
                     reply: str | None = None, thoughts: list | None = None,
                     artifacts: list | None = None) -> dict | None:
        """终态重写某一轮（append-only 的唯一例外——v35 用户裁决）。

        场景：确认/续跑把一次 send 拦停为 pending——行已写入（写入时刻快照），
        真正终态在后续续跑里产出；本方法把该行补全为终态。
        纪律：只改目标轮行、只改显式传入的键（None → 不动；空串不落键）；
        user_text/round/ts/unit 等原键保持；文件按行改写（同路径互斥）。
        """
        with self._lock:
            idx = None
            for i in range(len(self.turns) - 1, -1, -1):
                if int(self.turns[i].get("round", -1) or -1) == int(round_no):
                    idx = i
                    break
            if idx is None:
                return None
            row = dict(self.turns[idx])
            if summary is not None:
                row["summary"] = str(summary)
            if reply:
                row["reply"] = str(reply)
            if thoughts:
                # 合并旧 + 新（确认/续跑只采集到本轮增量——旧思维链不得丢）
                merged: list = []
                seen: set = set()
                for t in list(row.get("thoughts") or []) + list(thoughts):
                    key = (str(t.get("unit_id", "")),
                           int(t.get("round", 0) or 0),
                           str(t.get("text", ""))[:4000])
                    if key in seen:
                        continue
                    seen.add(key)
                    merged.append({"unit_id": key[0], "round": key[1],
                                   "text": key[2]})
                row["thoughts"] = merged[-30:]
            if artifacts:
                row["artifacts"] = [str(a) for a in artifacts]
            self.turns[idx] = row
            with _file_lock(self.path):
                try:
                    lines = self.path.read_text(encoding="utf-8").splitlines()
                except OSError:
                    lines = []
                for i in range(len(lines) - 1, -1, -1):
                    try:
                        rec = json.loads(lines[i])
                    except ValueError:
                        continue
                    if int(rec.get("round", -1) or -1) == int(round_no):
                        lines[i] = json.dumps(row, ensure_ascii=False)
                        break
                try:
                    tmp = self.path.with_suffix(self.path.suffix + ".tmp")
                    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
                    os.replace(tmp, self.path)
                except OSError as exc:
                    logger.debug("会话行终态重写失败（不阻断）：%s", exc)
            return row

    def reload(self) -> None:
        """I2（v65）：从磁盘重读轮次（压缩互斥后刷新跨实例视图）。"""
        with self._lock:
            self.turns = []
            self._load()

    def compaction_guard(self):
        """I2（v65）：压缩读-改-写互斥（按会话路径；跨实例）。"""
        return _file_lock(pathlib.Path(str(self.path) + ".compact"))

    def last_compaction(self) -> dict | None:
        """最近一次压缩行（G7：生效链=最后一个——迭代摘要已含更早内容）。"""
        for t in reversed(self.turns):
            if is_compaction_row(t):
                return t
        return None

    def artifacts(self) -> list:
        """去重累计交付物路径（按出现顺序——跨轮复用清单）。"""
        seen, out = set(), []
        for t in self.turns:
            for a in t.get("artifacts", []):
                if a and a not in seen:
                    seen.add(a)
                    out.append(a)
        return out

    def context_text_meta(self, max_chars: int = 4000) -> tuple[str, int]:
        """会话历史段 + 折叠元数据（S5-B：折叠事件机械化的数据源）。

        返回 (text, folded)：folded = 本次装配折叠掉的旧轮次数（0=未折叠）。
        文本构造与 context_text 同源（后者兼容转出）。

        碎片轮次（unit 标记）不计入主会话上下文窗口（用户硬要求 2026-09-21）：
        碎片会话内提交的轮次对会话上下文完全隔离（含 FSC 回退摘要）；
        碎片自身的多轮延续（按 unit 过滤的上下文）属后续大优化项。
        """
        if not self.turns:
            return "", 0
        blocks = []
        comp = self.last_compaction()
        covered = int(comp.get("to_round") or 0) if comp is not None else 0
        if comp is not None:
            blocks.append(_compaction_block(comp))
        for t in self.turns:
            if is_branch_row(t):
                if str(t.get("summary") or "").strip():
                    blocks.append(_branch_block(t))
                continue  # 承接行：不占轮次；有摘要则注入承接块（G1）
            if is_compaction_row(t):
                continue  # G7：压缩行本身不渲染（摘要块已置首）
            if covered and _turn_round(t) <= covered:
                continue  # G7：被压缩轮不注入
            if str(t.get("unit") or ""):
                continue  # 碎片轮次——隔离（不入主会话上下文）
            edit = self._edits.get(_turn_round(t))
            if edit and edit["op"] == "omit":
                continue  # 编辑层：省略（仅投影生效）
            if edit and edit["op"] == "replace":
                t = {**t, "user_text": edit["content"]}
            blocks.append(turn_block(t))
        # 从最旧开始折叠直到满足上限（保留最近轮次——「吃满上下文」的最近优先）
        folded = 0
        while blocks:
            text = ("[会话历史]\n" + "\n".join(blocks))
            if folded:
                text = f"[会话历史]（早期 {folded} 轮已折叠）\n" + "\n".join(blocks)
            if len(text) <= max_chars or len(blocks) == 1:
                return text, folded
            blocks.pop(0)
            folded += 1
        return "", 0

    def context_text(self, max_chars: int = 4000) -> str:
        """会话历史段（确定性——跨碎片逐字节一致；超限折叠最旧轮次）。"""
        return self.context_text_meta(max_chars)[0]

    @property
    def round_no(self) -> int:
        """已完成轮次数（G1：承接行不占轮次号）。"""
        return sum(1 for t in self.turns if "round" in t)

    def turn_views(self, estimator=None) -> list:
        """轮次视图（投影/裁剪 UI 用）——chars = 该轮实际进入上下文的块长度。

        estimator：可选 token 估算函数（由调用方注入——避免 conversation 依赖投影模块）；
        unit_marked=True 的轮次已被隔离（不进 context_text）；omitted/replaced 由
        context-edits.jsonl 编辑层决定（B 期：投影层生效，日志零改写）。
        """
        out = []
        comp = self.last_compaction()
        covered = int(comp.get("to_round") or 0) if comp is not None else 0
        for t in self.turns:
            if is_branch_row(t):
                continue  # 承接行不是轮次（G1）
            if is_compaction_row(t):
                continue  # G7：压缩行不是轮次
            rnd = _turn_round(t)
            edit = self._edits.get(rnd)
            block = turn_block({**t, "user_text": edit["content"]}
                               if edit and edit["op"] == "replace" else t)
            out.append({
                "round": rnd,
                "user_text": str(t.get("user_text") or ""),
                "summary": str(t.get("summary") or ""),
                "chars": len(block),
                "est_tokens": int(estimator(block)) if estimator else 0,
                "unit_marked": bool(t.get("unit")),
                "omitted": bool(edit and edit["op"] == "omit"),
                "replaced": bool(edit and edit["op"] == "replace"),
                "compacted": bool(covered and rnd <= covered),
            })
        return out

    def prev_digest(self) -> str:
        """上一轮（最近已记录轮次）的碎片摘要——严格「上一轮」语义（空则空）。

        碎片轮次（unit 标记）不计入主会话上下文（与 context_text 同口径）：
        从尾部取最近一条无标记轮次的摘要；无 → 空。
        """
        with self._lock:
            comp = self.last_compaction()
            covered = int(comp.get("to_round") or 0) if comp is not None else 0
            for t in reversed(self.turns):
                if is_branch_row(t) or is_compaction_row(t) \
                        or str(t.get("unit") or ""):
                    continue
                if covered and _turn_round(t) <= covered:
                    continue  # G7：被压缩轮不回流
                edit = self._edits.get(_turn_round(t))
                if edit and edit["op"] == "omit":
                    continue  # 已移出上下文的轮不得经摘要回流
                return str(t.get("fragment_digest", "") or "")
            return ""


def build_turn_digest(fragments: list, units: list,
                      max_chars: int = 2000) -> str:
    """FSC 低匹配回退：上一轮**全部碎片**上下文压缩（用户裁决 2026-09-12）。

    确定性：碎片输入序 + 固定截断（同输入同输出——跨碎片缓存前缀前提）。
    内容：域/目标（≤完整行均分预算）/状态/结果摘录/产物路径。
    """
    by_id = {getattr(u, "unit_id", ""): u for u in (units or [])}
    items = []
    for f in (fragments or []):
        uid = str(f.get("fragment_id", ""))
        dom = str(f.get("domain", ""))
        text = str(f.get("text", ""))[:120]
        u = by_id.get(uid)
        status = str(getattr(u, "status", "?")) if u is not None else "?"
        line = f"- [{dom}] {text} → {status}"
        excerpt = ""
        for x in reversed(getattr(u, "logs", None) or []):
            s = str(x).strip()
            if s and not s.startswith("["):
                excerpt = s[:150]
                break
        if excerpt:
            line += f"；结果：{excerpt}"
        dels = [str(p) for p in (getattr(u, "deliverables", None) or [])][:3]
        if dels:
            line += f"；产物：{', '.join(dels)}"
        items.append(line)
    if not items:
        return ""
    header = "[上一轮碎片上下文]\n"
    budget = max(20, int(max_chars) - len(header))
    per = max(40, budget // len(items) - 8)
    body = [ln[:per] + ("…" if len(ln) > per else "") for ln in items]
    text = header + "\n".join(body)
    if len(text) > max_chars:
        text = text[:max_chars]
    return text


def build_branch_digest(turns: list, max_chars: int = 2000) -> str:
    """被放弃路径的机械摘要（G1 对话分支；确定性——同输入同输出）。"""
    lines = []
    for t in (turns or []):
        if is_branch_row(t) or "round" not in t:
            continue
        rnd = t.get("round", "?")
        text = " ".join(str(t.get("user_text") or "").split())[:120]
        summary = " ".join(str(t.get("summary") or "").split())[:80]
        line = f"- 第{rnd}轮：{text}" if text else f"- 第{rnd}轮"
        if summary:
            line += f" → {summary}"
        arts = [str(a) for a in (t.get("artifacts") or [])][:3]
        if arts:
            line += f"；产物：{', '.join(arts)}"
        lines.append(line)
    text = "\n".join(lines)
    if max_chars > 0 and len(text) > max_chars:
        text = text[:max(0, max_chars - 1)] + "…"
    return text


def new_conversation_name(directory) -> str:
    """新会话文件名（与壳 _prepare_session 同口径：conversation-<ts> + 冲突加序）。"""
    d = pathlib.Path(directory)
    stamp = int(time.time())
    name = f"conversation-{stamp}.jsonl"
    n = 2
    while (d / name).exists():
        name = f"conversation-{stamp}-{n}.jsonl"
        n += 1
    return name
