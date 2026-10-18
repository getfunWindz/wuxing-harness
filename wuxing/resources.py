"""resources 生态（配置生态面——声明/校验/解析；2026-09-05 用户裁决必备）。

配置形态（config.jsonc resources 字段——EngineConfig.resources 双写）：
  resources: {
    "<name>": {"type": "file|dir|url", "path": "...", "optional": bool}
  }
语义：非 optional 缺失 = 配置错误（早报 fail-fast）；optional 缺失 = warn（可运行时创建）。
"""
import pathlib

VALID_TYPES = {"file", "dir", "url"}


class ResourceError(ValueError):
    """资源声明错误（畸形/缺失必填资源）。"""


class ResourceRegistry:
    def __init__(self, specs: dict | None = None, workdir: pathlib.Path | None = None):
        self.specs = dict(specs or {})
        self.workdir = pathlib.Path(workdir) if workdir else pathlib.Path.cwd()

    @staticmethod
    def _validate_spec(name: str, spec: dict):
        if not isinstance(spec, dict):
            raise ResourceError(f"resources.{name}: 声明必须是对象")
        rtype = spec.get("type")
        if rtype not in VALID_TYPES:
            raise ResourceError(f"resources.{name}: 未知 type {rtype!r}（合法值 {sorted(VALID_TYPES)}）")
        if not spec.get("path"):
            raise ResourceError(f"resources.{name}: path 必填")

    def resolve(self, name: str) -> pathlib.Path | str | None:
        """资源解析：file/dir → 工作区相对绝对路径；url → 原串。"""
        spec = self.specs.get(name)
        if spec is None:
            raise ResourceError(f"resources: 未声明 {name}")
        self._validate_spec(name, spec)
        if spec["type"] == "url":
            return spec["path"]
        return (self.workdir / spec["path"]).resolve()

    def check(self) -> list:
        """校验全部声明：返回 warn 列表（optional 缺失）；非 optional 缺失抛 ResourceError。"""
        warns = []
        for name, spec in self.specs.items():
            self._validate_spec(name, spec)
            if spec["type"] == "url":
                continue
            target = (self.workdir / spec["path"]).resolve()
            exists = target.exists() if spec["type"] == "dir" else target.is_file()
            if not exists:
                if spec.get("optional"):
                    warns.append(f"resources.{name}: 缺失（optional——可运行时创建）: {target}")
                else:
                    raise ResourceError(
                        f"resources.{name}: 缺失（非 optional——配置早报）: {target}")
        return warns
