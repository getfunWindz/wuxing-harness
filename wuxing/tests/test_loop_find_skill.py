"""TDD：Skill 体系 T3——find-skill（发现→安装→立即可用；SkillRadar 可配源）。"""
import pathlib
import tempfile

from wuxing.skills import SkillRadarClient, SkillRegistry, install_skill


def test_skillradar_client_payload_and_parse():
    """客户端：payload 结构（goal/constraints/keywords/max_results）+ 响应解析。"""
    captured = {}

    class FakeUrlopen:
        def __init__(self, payload):
            self._payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            import json
            return json.dumps(self._payload).encode("utf-8")

    class FakeHttp:
        def __init__(self, payload):
            self._payload = payload

        def __call__(self, req, timeout=10):
            import json as _j
            captured["url"] = req.full_url
            captured["body"] = _j.loads(req.data.decode("utf-8"))
            captured["headers"] = dict(req.header_items())
            return FakeUrlopen(self._payload)

    http = FakeHttp({"results": [{"name": "docx-helper", "description": "Word 文档处理"}]})
    client = SkillRadarClient(base_url="https://example.test", _http=http)
    results = client.discover("写一个报告", "", "docx,报告", max_results=5)
    assert "docx-helper" in [r["name"] for r in results]
    assert captured["url"].startswith("https://example.test/discover")
    assert captured["body"] == {"task_goal": "写一个报告", "task_constraints": "",
                                "keywords": "docx,报告", "max_results": 5}
    assert "user-agent" in str(captured["headers"]).lower(), captured["headers"]


def test_skillradar_failure_returns_error():
    """服务不可达/响应异常：空结果（结构化失败——不挂引擎）。"""
    class Boom:
        def __call__(self, req, timeout=10):
            raise OSError("network down")

    client = SkillRadarClient(base_url="https://x.test", _http=Boom())
    results = client.discover("任务", "", "", 5)
    assert results == []


def test_install_skill_then_visible_in_registry():
    """安装：写用户级 skills/<name>/（SKILL.md+scripts）→ 注册表立即可见。"""
    user = pathlib.Path(tempfile.mkdtemp())
    install_skill(user_dir=user, name="zip-helper",
                  description="zip 打包处理",
                  sk_md="---\nname: zip-helper\ndescription: zip 打包处理\n---\n先 zip 再校验",
                  scripts={"pack.py": "print('pack')"})
    reg = SkillRegistry(user_dir=user, project_dir=pathlib.Path(tempfile.mkdtemp()))
    idx = reg.index()
    assert "zip-helper" in idx, idx
    assert idx["zip-helper"]["level"] == "fragment"
    assert "pack.py" in idx["zip-helper"]["scripts"]
    detail = reg.get_detail("zip-helper")
    assert "先 zip 再校验" in detail["content"]


def test_builtin_skills_layer_scanned():
    """内置层（代码分发 resources/skills/）可被注册表扫描（find-skill 内挂）。"""
    import wuxing
    builtin = pathlib.Path(wuxing.__file__).parent / "resources" / "skills"
    assert builtin.exists(), "内置技能目录必须随包分发"
    reg = SkillRegistry(user_dir=pathlib.Path(tempfile.mkdtemp()),
                        project_dir=pathlib.Path(tempfile.mkdtemp()),
                        builtin_dir=builtin)
    idx = reg.index()
    assert "find-skill" in idx, f"内置层必须可扫描：{list(idx.keys())}"


def test_install_skill_rejects_path_traversal():
    """安全坏味道修复：技能名不得逃逸用户技能目录（../ 路径遍历）。"""
    base = pathlib.Path(tempfile.mkdtemp())
    user = base / "skills"
    try:
        install_skill(user_dir=user, name="../evil-skill",
                      description="x",
                      sk_md="---\nname: evil\ndescription: x\n---\nbody")
        raise AssertionError("路径遍历技能名必须被拒绝")
    except ValueError:
        # 期望 ValueError（路径遍历拒绝）；下行断言验证未写出
        pass
    assert not (base / "evil-skill").exists(), \
        "技能不得写入用户技能目录之外"
