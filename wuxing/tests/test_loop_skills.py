"""TDD：Skill 体系 T1——协议与注册表（双层扫描/索引/详情/破损容错）。"""
import pathlib
import tempfile

from wuxing.skills import SkillRegistry


def _write_skill(root: pathlib.Path, name: str, meta: dict, body: str = "## 流程\n知识"):
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    fm = "\n".join(f"{k}: {v}" for k, v in meta.items())
    (d / "SKILL.md").write_text(f"---\n{fm}\n---\n{body}", encoding="utf-8")
    return d


def test_registry_scans_user_and_project_layers():
    """两层扫描（用户级+项目级）→ 索引完整；level 默认 fragment。"""
    user = pathlib.Path(tempfile.mkdtemp())
    proj = pathlib.Path(tempfile.mkdtemp()) / "workdir"
    proj.mkdir()
    _write_skill(user, "pdf-helper", {"name": "pdf-helper",
                                      "description": "PDF 处理知识",
                                      "level": "domain"})
    _write_skill(proj, "git-tips", {"name": "git-tips",
                                    "description": "git 流程知识"})
    reg = SkillRegistry(user_dir=user, project_dir=proj)
    idx = reg.index()
    assert "pdf-helper" in idx, idx
    assert "git-tips" in idx, idx
    assert idx["pdf-helper"]["level"] == "domain"
    assert idx["git-tips"]["level"] == "fragment", "缺省 level 必须为 fragment"


def test_registry_skips_broken_skills():
    """破损 skill（无 frontmatter/非法）跳过不阻塞；警告可追踪。"""
    d = pathlib.Path(tempfile.mkdtemp())
    broken = d / "broken" / "SKILL.md"
    broken.parent.mkdir(parents=True)
    broken.write_text("没有 frontmatter 的内容", encoding="utf-8")
    _write_skill(d, "good", {"name": "good", "description": "ok"})
    reg = SkillRegistry(user_dir=d, project_dir=pathlib.Path(tempfile.mkdtemp()))
    idx = reg.index()
    assert "good" in idx
    assert "broken" not in idx, "破损 skill 不得入索引"


def test_get_detail_returns_full_and_scripts():
    """get_detail：SKILL.md 全文 + scripts 清单（渐进披露第二层材料）。"""
    d = pathlib.Path(tempfile.mkdtemp())
    sd = _write_skill(d, "tool-x", {"name": "tool-x", "description": "x 处理"})
    sdir = sd / "scripts"
    sdir.mkdir()
    (sdir / "run.py").write_text("print(1)", encoding="utf-8")
    reg = SkillRegistry(user_dir=d, project_dir=pathlib.Path(tempfile.mkdtemp()))
    detail = reg.get_detail("tool-x")
    assert detail is not None
    assert "## 流程" in detail["content"]
    assert "run.py" in detail["scripts"]
    assert reg.get_detail("nonexistent") is None


def test_skill_index_cached_until_mtime_change():
    """D2：技能索引热路径缓存——index() 重复调用返回同一缓存对象（不重新读盘）；
    SKILL.md mtime 变更 → 重建（显式 utime——不依赖 sleep 时序）。"""
    import os
    import pathlib
    import tempfile
    import time

    from wuxing.skills import SkillRegistry

    tmp = pathlib.Path(tempfile.mkdtemp())
    sdir = tmp / "demo-skill"
    sdir.mkdir()
    sp = sdir / "SKILL.md"
    sp.write_text(
        "---\nname: demo\ndescription: 测试技能\nlevel: fragment\n---\n正文",
        encoding="utf-8")
    reg = SkillRegistry(user_dir=tmp)

    i1 = reg.index()
    i2 = reg.index()
    assert "demo" in i1
    assert i1 is i2, "重复 index() 必须命中缓存（同一对象——不重新读盘）"
    # 显式推进 mtime → 失效重建（os.utime 未来时间——无 sleep 时序依赖）
    future = time.time() + 10
    os.utime(sp, (future, future))
    i3 = reg.index()
    assert i3 is not i2, "mtime 变更必须重建索引"
    assert i3["demo"]["description"] == "测试技能"
