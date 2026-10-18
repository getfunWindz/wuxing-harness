"""凭据存储（R3-1 · DSH write-only 范式）。

分层（信源可信度排序，DSH `dsh-credentials-local` 对齐）：
    进程环境变量（只读，优先——CI/容器/显式传入即本次运行的明确意图）
  > ~/.wuxing/credentials.json（本模块管理，可写）

纪律：
- write-only：`describe()` 永不含值（configured/source/writable/shadowed 四个事实）
- 写入被环境变量遮蔽 → CredentialShadowed（拒绝无效写——DSH assertUnshadowed 同义）
- 文档严格解析（版本化；非法即 loud error——「存过的凭据没有效果」必须可见，绝不静默当空）
- 原子写（atomic_write_text）；POSIX 0600
- 密钥值永不进 config/日志/提交（AGENTS §2.5 口径修订见 README 决策留痕）
"""
import json
import os
import pathlib
import re

from wuxing.atomic_write import atomic_write_text

REF_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
_ENV_LINE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
DOCUMENT_VERSION = 1


class CredentialError(ValueError):
    pass


class CredentialShadowed(CredentialError):
    """写入会被环境变量遮蔽（读走 env、存储写入无效）——显式拒绝而非静默无效。"""


def credentials_path() -> pathlib.Path:
    """凭据文档路径（测试隔离钩子——conftest 与 config 同款 monkeypatch）。"""
    return pathlib.Path.home() / ".wuxing" / "credentials.json"


def validate_ref(ref: str) -> str:
    if not isinstance(ref, str) or not REF_RE.match(ref):
        raise CredentialError(
            f"非法凭据 ref：{ref!r}（需 POSIX 环境变量名，如 DEEPSEEK_API_KEY）")
    return ref


def derive_ref(name: str) -> str | None:
    """类型/供应商 id → 默认凭据 ref（deepseek → DEEPSEEK_API_KEY；mock → None）。

    单一事实来源：引擎（factory）与壳（发现端点）共用。
    """
    if not name or str(name) == "mock":
        return None
    return re.sub(r"[^A-Z0-9]+", "_", str(name).upper()) + "_API_KEY"


def validate_value(value: str) -> str:
    """与壳侧校验互为镜像（DSH 同款）：trim 非空 + 可打印 ASCII；
    拒 `NAME=value` 环境行粘贴与引号包裹。返回规范化后的值。"""
    if not isinstance(value, str):
        raise CredentialError("凭据值必须是字符串")
    v = value.strip()
    if not v:
        raise CredentialError("凭据值不能为空")
    if not all(0x21 <= ord(ch) <= 0x7E for ch in v):
        raise CredentialError("凭据值只能包含可打印 ASCII 字符（\\x21-\\x7E）")
    if _ENV_LINE_RE.match(v):
        raise CredentialError("看起来是 NAME=value 环境行——只粘贴密钥值本身")
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        raise CredentialError("凭据值不应带包裹引号")
    return v


def _load() -> dict:
    """读取存储层（缺文件 = 空；非法 = loud error，绝不当作空）。"""
    p = credentials_path()
    if not p.exists():
        return {}
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CredentialError(f"凭据文档无法解析：{p}（{exc}）") from exc
    if (not isinstance(doc, dict) or doc.get("version") != DOCUMENT_VERSION
            or not isinstance(doc.get("credentials"), dict)):
        raise CredentialError(
            f"凭据文档结构非法（需 version={DOCUMENT_VERSION} + credentials 映射）：{p}")
    values = {}
    for k, v in doc["credentials"].items():
        validate_ref(k)
        if not isinstance(v, str) or not v:
            raise CredentialError(f"凭据文档条目非法（值须为非空字符串）：{k}")
        values[k] = v
    return values


def _save(values: dict) -> None:
    p = credentials_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(p, json.dumps(
        {"version": DOCUMENT_VERSION, "credentials": values},
        ensure_ascii=False, indent=2) + "\n")
    if os.name != "nt":
        os.chmod(p, 0o600)


def resolve(ref: str, allow_store: bool = True) -> str | None:
    """信源解析：环境变量（优先）> 存储；未配置 → None。

    allow_store=False（G4 隔离装配）：仅环境变量——不触碰凭据存储文件。
    """
    validate_ref(ref)
    env = os.environ.get(ref)
    if env:
        return env
    if not allow_store:
        return None
    return _load().get(ref)


def describe(ref: str) -> dict:
    """只写视图——四项事实，永不含值。"""
    validate_ref(ref)
    if os.environ.get(ref):
        return {"ref": ref, "configured": True, "source": "env",
                "writable": False, "shadowed": True}
    if ref in _load():
        return {"ref": ref, "configured": True, "source": "store",
                "writable": True, "shadowed": False}
    return {"ref": ref, "configured": False, "source": None,
            "writable": True, "shadowed": False}


def set(ref: str, value: str) -> dict:
    """写入存储（env 遮蔽 → CredentialShadowed；非法文档 → CredentialError 不覆盖）。"""
    validate_ref(ref)
    value = validate_value(value)
    if os.environ.get(ref):
        raise CredentialShadowed(
            f"{ref} 由环境变量提供（只读）——写入存储不会生效，已拒绝")
    values = _load()
    values[ref] = value
    _save(values)
    return describe(ref)


def unset(ref: str) -> dict:
    """移除存储条目（幂等；不动环境变量）。"""
    validate_ref(ref)
    values = _load()
    if values.pop(ref, None) is not None:
        _save(values)
    return describe(ref)
