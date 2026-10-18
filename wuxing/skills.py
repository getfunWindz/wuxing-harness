"""Skill 体系（P5-SK/T1：协议 + 注册表——双层扫描/索引/详情/破损容错）。

用户裁决（2026-09-05）：没有 skill 的 harness 无法称为合格的 harness。
协议：SKILL.md = frontmatter(name/description/level[domain|fragment]/version?) + markdown 正文 + 可选 scripts/。
披露：索引（name: desc——稳定段）+ get_detail（渐进披露第二层材料）。
"""
import logging
import pathlib
import re

logger = logging.getLogger(__name__)

_UNSET = object()  # 哨兵：user_dir 未提供（默认 → ~/.wuxing/skills）；显式 None = 不扫用户层

# E2-1 格式契约（设计 §2）：名称 kebab-case ≤40；描述必填；level 枚举。
NAME_MAX = 40
DESCRIPTION_MAX = 500
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
_LEVELS = ("domain", "fragment")


class SkillRegistry:
    """技能注册表：内置层（代码分发）+ 用户级（~/.wuxing/skills）+ 项目级（<workdir>/.skills）。

    G4（2026-09-26）：`user_dir=_UNSET` 保持现行为；显式 `user_dir=None` → 用户层
    不扫描（隔离装配——最小运行时零隐式继承）。
    """

    def __init__(self, user_dir: pathlib.Path | None = _UNSET,
                 project_dir: pathlib.Path | None = None,
                 builtin_dir: pathlib.Path | None = None):
        import os
        if user_dir is _UNSET:
            user_dir = pathlib.Path(os.path.expanduser("~")) / ".wuxing" / "skills"
        self.user_dir = pathlib.Path(user_dir) if user_dir else None
        self.project_dir = pathlib.Path(project_dir) if project_dir else None
        self.builtin_dir = pathlib.Path(builtin_dir) if builtin_dir else None
        self._index_cache = None
        self._index_fp = None  # D2：mtime 指纹（索引缓存失效判据）

    def _skill_dirs(self) -> list:
        dirs = []
        if self.builtin_dir is not None:
            dirs.append(self.builtin_dir)
        if self.user_dir is not None:
            dirs.append(self.user_dir)
        if self.project_dir is not None:
            dirs.append(self.project_dir)
        return dirs

    def index(self) -> dict:
        """扫描全部技能 → {name: {name, description, level, path, scripts}}。

        破损（无有效 frontmatter/缺 name）跳过；项目层覆盖用户层同名（merge 语义）。
        D2（2026-09-07）：mtime 失效缓存——重复 index()（每 run_unit 一次）不
        重新读盘；技能目录变更（SKILL.md mtime 指纹）→ 重建。
        """
        fingerprint = self._mtime_fingerprint()
        if self._index_cache is not None and self._index_fp == fingerprint:
            return self._index_cache
        idx = {}
        for d in self._skill_dirs():
            if not d.exists():
                continue
            for skill_dir in sorted(d.iterdir()):
                if not skill_dir.is_dir():
                    continue
                info = self._parse_skill_dir(skill_dir)
                if info is None:
                    continue
                if info["name"] in idx:
                    logger.warning("覆盖同名技能 %s（项目层优先）", info["name"])
                idx[info["name"]] = info
        self._index_cache = idx
        self._index_fp = fingerprint
        return idx

    def _mtime_fingerprint(self) -> tuple:
        """技能目录 mtime 指纹（SKILL.md 变更感知——无变更零重建）。"""
        parts = []
        for d in self._skill_dirs():
            if not d.exists():
                continue
            try:
                for skill_dir in sorted(d.iterdir()):
                    sp = skill_dir / "SKILL.md"
                    if sp.exists():
                        parts.append((str(sp), sp.stat().st_mtime_ns))
            except OSError:
                continue
        return tuple(parts)

    @staticmethod
    def _parse_skill_dir(skill_dir: pathlib.Path) -> dict | None:
        """解析单个技能目录 → 索引条目；破损/契约违规返回 None（容错——不阻塞）。

        E2-1：字段校验 loud（warning 可追踪）；调用策略非法 fail-closed
        （model/user 双 false + policy_error——管理面可见可修复）。
        """
        sp = skill_dir / "SKILL.md"
        if not sp.exists():
            return None
        try:
            text = sp.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            # SKILL.md 读不到/解码失败 → None（技能跳过）
            return None
        fm = _parse_frontmatter(text)
        if not fm:
            logger.warning("技能跳过（无有效 frontmatter）：%s", skill_dir.name)
            return None
        errors, warnings = validate_skill_fields(fm)
        for w in warnings:
            logger.warning("技能字段告警（%s）：%s", skill_dir.name, w)
        if errors:
            logger.warning("技能跳过（字段非法 %s）：%s",
                           skill_dir.name, "；".join(errors))
            return None
        policy = parse_invocation(fm)
        if policy["policy_error"]:
            logger.warning("技能调用策略非法——fail-closed（%s）：%s",
                           skill_dir.name, policy["policy_error"])
        level = str(fm.get("level", "")).strip()
        if level not in _LEVELS:
            level = "fragment"
        scripts = []
        scripts_dir = skill_dir / "scripts"
        if scripts_dir.is_dir():
            scripts = sorted(p.name for p in scripts_dir.iterdir() if p.is_file())
        return {
            "name": str(fm["name"]).strip(),
            "description": str(fm.get("description", "")).strip(),
            "level": level,
            "path": str(skill_dir),
            "scripts": scripts,
            "model_invocable": policy["model_invocable"],
            "user_invocable": policy["user_invocable"],
            "policy_error": policy["policy_error"],
            "allowed_tools": parse_allowed_tools(fm),
        }

    def get_detail(self, name: str) -> dict | None:
        """渐进披露第二层：SKILL.md 全文 + scripts 清单；不存在返回 None。"""
        info = self.index().get(name)
        if info is None:
            return None
        try:
            content = (pathlib.Path(info["path"]) / "SKILL.md").read_text(
                encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            # SKILL.md 读不到/解码失败 → None（技能内容缺失降级）
            return None
        return {"name": name, "content": content, "scripts": info["scripts"]}


def _parse_frontmatter(text: str) -> dict | None:
    """最小 frontmatter 解析（--- 包裹的 key: value 行）；非 YAML 子集返回 None。"""
    m = re.match(r"^---\s*\n(.*?)\n---\s*(\n|$)", text, re.DOTALL)
    if not m:
        return None
    fm = {}
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            return None  # 非简单键值 → 视为破损（不猜测）
        k, v = line.split(":", 1)
        fm[k.strip()] = v.strip().strip("\"'")
    return fm


def _parse_bool(value) -> bool | None:
    """严格布尔解析：'true'/'false'（忽略大小写）→ bool；其余 None（非法）。"""
    v = str(value or "").strip().lower()
    if v == "true":
        return True
    if v == "false":
        return False
    return None


def parse_allowed_tools(fm: dict) -> list[str]:
    """A14：`allowed-tools` 声明解析（Phase 1——只声明不授权）。

    格式：逗号分隔工具名（兼容 `[a, b]` 括号写法；引号/空白容错）；
    去重保序；缺省/空值 → []（零行为）。未知工具的清点归引擎面
    （域白名单并集——`engine_skills._allowed_tools_missing`）。
    """
    raw = str(fm.get("allowed-tools", "") or "").strip()
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1]
    out: list[str] = []
    for part in raw.split(","):
        name = part.strip().strip("\"'")
        if name and name not in out:
            out.append(name)
    return out


def validate_skill_fields(fm: dict) -> tuple[list, list]:
    """格式契约校验（E2-1 设计 §2）：(errors, warnings)。

    errors → 不入索引（破损）；warnings → 入索引但 loud 可见。
    """
    errors, warnings = [], []
    name = str(fm.get("name", "")).strip()
    if not name:
        errors.append("name 必填")
    elif not _NAME_RE.match(name):
        errors.append(f"name 非法（须 kebab-case，≤{NAME_MAX}）：{name!r}")
    desc = str(fm.get("description", "")).strip()
    if not desc:
        errors.append("description 必填")
    elif len(desc) > DESCRIPTION_MAX:
        warnings.append(
            f"description 超长（{len(desc)}>{DESCRIPTION_MAX}，索引截断显示）")
    level = str(fm.get("level", "")).strip()
    if level and level not in _LEVELS:
        warnings.append(f"level 非法（{level!r}）——回落 fragment")
    if "allowed-tools" in fm and not parse_allowed_tools(fm):
        warnings.append("allowed-tools 为空（忽略）")
    return errors, warnings


def parse_invocation(fm: dict) -> dict:
    """调用策略（B5）：model/user 双开关；非法值 fail-closed（皆 false）。"""
    out = {"model_invocable": True, "user_invocable": True, "policy_error": ""}
    errs = []
    for key in ("model_invocable", "user_invocable"):
        if key not in fm:
            continue
        val = _parse_bool(fm.get(key))
        if val is None:
            errs.append(f"{key}={str(fm.get(key)).strip()!r} 非法")
        else:
            out[key] = val
    if errs:
        # fail-closed：任一非法 → 双开关皆禁（策略块整体不可信）
        out["model_invocable"] = False
        out["user_invocable"] = False
    out["policy_error"] = "；".join(errs)
    return out


class SkillRadarClient:
    """SK T3：SkillRadar Discover 客户端（find-skill 查询源——base_url 可配）。"""

    def __init__(self, base_url: str = "https://api.skillradar.quest",
                 _http=None, timeout: float = 15.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._http = _http  # 测试注入

    def discover(self, task_goal: str, task_constraints: str = "",
                 keywords: str = "", max_results: int = 5) -> list:
        """查询候选技能；网络/解析失败返回 []（结构化失败——不挂引擎）。"""
        import json
        from urllib.request import Request
        payload = {"task_goal": task_goal, "task_constraints": task_constraints,
                   "keywords": keywords, "max_results": max_results}
        req = Request(
            f"{self.base_url}/discover",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "User-Agent": "wuxing-find-skill/0.1"},
            method="POST")
        try:
            opener = self._http or __import__("urllib.request", fromlist=["urlopen"]).urlopen
            with opener(req, timeout=self.timeout) as resp:
                raw = resp.read()
        except Exception:
            return []
        try:
            data = json.loads(raw.decode("utf-8"))
            return data.get("results", [])
        except (ValueError, UnicodeDecodeError):
            return []


def install_skill(user_dir: pathlib.Path, name: str, description: str,
                  sk_md: str, scripts: dict | None = None) -> pathlib.Path:
    """安装技能到用户级目录（SKILL.md + scripts/）——立即进入注册表可见。

    调用方（find-skill 流程）负责用户确认（人工介入哲学——安装影响后续所有任务）。
    E2-1 契约：名称须 kebab-case；SKILL.md 须含合法 frontmatter 且 name 一致；
    非法输入 loud 失败（不静默写坏文件）。
    """
    if not name or not sk_md:
        raise ValueError("install_skill: name 与 SKILL.md 内容必填")
    # 安全修复（2026-09-11 审查）：技能名不得逃逸用户技能目录（路径遍历）
    name = str(name).strip()
    if name in (".", "..") or "/" in name or "\\" in name:
        raise ValueError(
            f"install_skill: 非法技能名 {name!r}（不得含路径分隔符/相对路径）")
    if not _NAME_RE.match(name):
        raise ValueError(
            f"install_skill: 非法技能名 {name!r}（须 kebab-case，≤{NAME_MAX}）")
    fm = _parse_frontmatter(sk_md)
    if fm is None:
        raise ValueError("install_skill: SKILL.md 缺少合法 frontmatter")
    errors, _warnings = validate_skill_fields(fm)
    if errors:
        raise ValueError("install_skill: " + "；".join(errors))
    if str(fm.get("name", "")).strip() != name:
        raise ValueError(
            "install_skill: frontmatter name 与安装参数不一致"
            f"（{str(fm.get('name', '')).strip()!r} != {name!r}）")
    target = pathlib.Path(user_dir) / name
    target.mkdir(parents=True, exist_ok=True)
    (target / "SKILL.md").write_text(sk_md, encoding="utf-8")
    for sname, scontent in (scripts or {}).items():
        sdir = target / "scripts"
        sdir.mkdir(exist_ok=True)
        (sdir / sname).write_text(scontent, encoding="utf-8")
    return target
