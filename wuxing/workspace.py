"""工作区 + 产物清单（Q8：文件为真理，清单为索引——与 git 工作树/index 同构）。

路径逃逸守卫（审查加固 2026-09）：write/read 统一经 _safe_path 归一化判定——
任何解析后落在工作区之外的路径一律拒绝（此前 write_artifact 可经 ../ 逃逸写任意文件）。
"""
import json
import logging
import os
import pathlib
import threading

from wuxing.filelock import lock_for
from wuxing.protocols import Artifact

logger = logging.getLogger(__name__)

# L4 真跑发现：引擎根级内部文件（.wuxing 之外仍泄露——模型读到缓存当上下文）
_INTERNAL_FILES = {"reply_cache.json", "shape_cache.json", "task_state.json",
                   "manifest.json", "brain_memory.json"}
# 2026-09-27 审查：Windows 大小写不敏感——比较用 normcase（.WUXING 命中同一实体）
_INTERNAL_NORM = {os.path.normcase(n) for n in _INTERNAL_FILES}

MANIFEST_FILE = "manifest.json"


def _fix_artifact(d: dict) -> Artifact:
    """json 往返后 tuple 字段会变 list——恢复为 tuple（与 state.py 同源修复）。"""
    d = dict(d)
    if isinstance(d.get("depends_on"), list):
        d["depends_on"] = tuple(d["depends_on"])
    return Artifact(**d)


def _canonical_path(p: pathlib.Path) -> pathlib.Path:
    """规范化路径（G8-M2）：剥 Windows ``\\?\\`` 扩展前缀——``resolve()`` 对同一
    路径会因存在性/并发建目录而返回带前缀/不带前缀两种形式，导致 in-root 判定误杀。"""
    s = os.path.realpath(str(p))
    s = s.removeprefix("\\\\?\\")
    return pathlib.Path(s)


class Workspace:
    def __init__(self, root: pathlib.Path,
                 permission_profile: str = "workspace-write",
                 manifest_root: pathlib.Path | None = None):
        self.root = _canonical_path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        # E3-1/R5（T2）：产物登记（manifest）可落独立状态根（缺省=root，零变化）——
        # worktree 隔离运行时交付物在 worktree、账本留主工作区。
        self.manifest_root = (_canonical_path(manifest_root)
                              if manifest_root else self.root)
        # SEC3：权限剖面（full-access 放行工作区外；内部数据面保护不豁免）
        self.permission_profile = str(permission_profile or "workspace-write")
        self._lock = threading.Lock()  # P16 多手并行：产物/manifest 并发写互斥

    def _safe_path(self, path: str) -> pathlib.Path:
        """路径逃逸守卫（单一来源）：../ 归一化后必须仍位于工作区根内。

        L4 真跑发现：屏蔽引擎内部数据——.wuxing/ 目录 + 根级内部文件（
        reply_cache/shape_cache/task_state/manifest——模型读到缓存当上下文=困惑源）。
        """
        if not path:
            raise ValueError("empty path")
        target = _canonical_path(self.root / path)
        if (self.permission_profile != "full-access"
                and not target.is_relative_to(self.root)):
            raise ValueError(f"path escapes workspace: {path}")
        # E3-1/R5（T4 实证）：root 自身路径可能含 ".wuxing" 组件（worktree 布局
        # `<主>/.wuxing/worktrees/<rid>`）——内部面扫描必须只看 **root 相对段**，
        # 否则普通交付物被误判为内部数据（internal dir hidden）。
        try:
            parts = target.relative_to(self.root).parts
        except ValueError:
            parts = target.parts   # full-access 越界路径：按全路径扫描（原语义）
        idx = next((i for i, p in enumerate(parts)
                    if os.path.normcase(p) == os.path.normcase(".wuxing")), None)
        if idx is not None:
            # G6：截断全文落盘目录——精确例外（仅 ".wuxing/truncated"；其余仍隐藏）
            # 2026-10-01：契约报告收纳目录 ".wuxing/reports" 同样例外（读写可达）
            # 2026-09-27 审查：大小写归一比较（Windows .WUXING 命中同一实体目录）
            _exposed = ("truncated", "reports")
            visible = (len(parts) > idx + 1 and os.path.normcase(parts[idx + 1])
                       in {os.path.normcase(x) for x in _exposed})
            if not visible:
                raise ValueError(f"internal dir hidden: {path}")
        if os.path.normcase(target.name) in _INTERNAL_NORM:
            raise ValueError(f"internal file hidden: {path}")
        return target

    def write_artifact(self, artifact: Artifact, content: str) -> Artifact:
        target = self._safe_path(artifact.path)
        with self._lock:  # P16：并发写产物/清单互斥
            target.parent.mkdir(parents=True, exist_ok=True)
            self._write_text_atomic(target, content)
            self._append_manifest(artifact)
        return artifact

    @staticmethod
    def _write_text_atomic(target: pathlib.Path, content: str) -> None:
        """产物原子写（tmp + os.replace——崩溃/失败不产生半写产物）。

        B 级修复（2026-09-11 审查）：与 manifest A6/S7 同源——「文件为真理」
        前提是写入不会把真理文件破坏成半写内容。PermissionError（Windows
        文件锁）重试 3 次；持续失败兜底直写（不丢产物——索引/内容优先级
        高于写入形态）。
        """
        import os
        import time as _time
        tmp = target.with_name(target.name + ".tmp")
        try:
            tmp.write_text(content, encoding="utf-8")
        except OSError:
            try:
                tmp.unlink()
            except OSError as exc:
                logger.debug("写入失败后临时文件清理失败（将抛出原异常）：%s", exc)
            raise
        for _attempt in range(3):
            try:
                os.replace(tmp, target)
                return
            except PermissionError:
                _time.sleep(0.05 * (_attempt + 1))
        try:  # 重试耗尽（读者持续持有句柄）——兜底直写，内容不丢
            target.write_text(content, encoding="utf-8")
        finally:
            try:
                tmp.unlink()
            except OSError as exc:
                logger.debug("兜底直写后临时文件清理失败（不阻断）：%s", exc)

    def read(self, path: str) -> str | None:
        try:
            p = self._safe_path(path)
        except ValueError:
            return None  # 逃逸路径按不存在处理（不泄漏信息）
        return p.read_text(encoding="utf-8") if p.exists() else None

    def manifest(self) -> list:
        """产物清单读取（A6：损坏容错——崩溃半写 → 空清单重建，不抛异常）。"""
        mp = self.manifest_root / MANIFEST_FILE
        with lock_for(mp):
            if not mp.exists():
                return []
            try:
                data = json.loads(mp.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, ValueError):
                return []  # 损坏 → 空清单（下一次写入重建——不传播崩溃）
        return [_fix_artifact(d) for d in data]

    def relocate_manifest_path(self, old: str, new: str) -> bool:
        """清单条目路径重定位（2026-10-01：契约报告归档 .wuxing/reports/ 用）。

        返回是否有条目被更新；同路径覆盖写（保留其余字段）。
        """
        mp = self.manifest_root / MANIFEST_FILE
        with lock_for(mp):
            items = self.manifest()
            changed = False
            for a in items:
                if a.path == old:
                    a.path = new
                    changed = True
            if not changed:
                return False
            tmp = self.manifest_root / (MANIFEST_FILE + ".tmp")
            tmp.write_text(
                json.dumps([a.__dict__ for a in items], ensure_ascii=False,
                           indent=2),
                encoding="utf-8")
            import os
            import time as _time
            target = self.manifest_root / MANIFEST_FILE
            for _attempt in range(3):
                try:
                    os.replace(tmp, target)
                    return True
                except PermissionError:
                    _time.sleep(0.05 * (_attempt + 1))
            try:
                tmp.unlink()
            except OSError as exc:
                logger.debug("清单临时文件清理失败（不阻断）：%s", exc)
            return False

    def _append_manifest(self, artifact: Artifact):
        # G8-M2：跨 Workspace 实例共享路径锁（多引擎同工作区写清单不丢项）
        with lock_for(self.manifest_root / MANIFEST_FILE):
            items = self.manifest()
            items = [a for a in items if a.path != artifact.path]  # 幂等：同路径覆盖
            items.append(artifact)
            # A6：原子写（tmp + os.replace——崩溃中写不产生半写损坏；与 state.py 同源）
            # S7（真实测试 beginner-1 暴露）：Windows 文件锁（Defender/索引器/并发读）
            # → os.replace 瞬时 PermissionError——重试 + 最终失败不阻断（索引非生命线）
            import os
            import time as _time
            tmp = self.manifest_root / (MANIFEST_FILE + ".tmp")
            tmp.write_text(
                json.dumps([a.__dict__ for a in items], ensure_ascii=False,
                           indent=2),
                encoding="utf-8")
            target = self.manifest_root / MANIFEST_FILE
            for _attempt in range(3):
                try:
                    os.replace(tmp, target)
                    return
                except PermissionError:
                    _time.sleep(0.05 * (_attempt + 1))
            # 重试耗尽：清理临时文件，不抛（清单更新失败不阻断产物/任务）
            try:
                tmp.unlink()
            except OSError as exc:
                logger.debug("清单临时文件清理失败（不阻断）：%s", exc)
