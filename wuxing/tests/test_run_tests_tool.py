"""TDD · O2-1 沙箱执行能力（run_tests：白名单 + 沙箱复用 + 物证）。"""
from wuxing.workspace import Workspace


def _mk(tmp_path):
    from wuxing.tools.run_tests_tool import RunTestsTool
    return RunTestsTool(Workspace(tmp_path))


def test_whitelist_denies_non_test_commands(tmp_path):
    t = _mk(tmp_path)
    for bad in ("rm -rf /", "python -c 'print(1)'",
                "python -m pytest && echo done",
                "python -m pytest | tee out.txt",
                "python -m pytest > out.txt",
                "curl http://127.0.0.1:1"):
        res = t.execute(command=bad)
        assert res.status == "error", bad
        assert "run_tests" in (res.error or "")


def test_run_pytest_passes(tmp_path):
    t = _mk(tmp_path)
    (tmp_path / "test_sample.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8")
    res = t.execute(command="python -m pytest -q test_sample.py")
    assert res.status == "ok", res.error
    assert "1 passed" in (res.content or "")


def test_run_unittest_passes(tmp_path):
    t = _mk(tmp_path)
    (tmp_path / "test_sample.py").write_text(
        "import unittest\n\n\nclass T(unittest.TestCase):\n"
        "    def test_ok(self):\n        self.assertTrue(True)\n",
        encoding="utf-8")
    res = t.execute(command="python -m unittest discover -s . -p test_*.py")
    assert res.status == "ok", res.error
    assert "OK" in (res.content or "")


def test_verify_user_domains_allow_run_tests():
    from wuxing.domains.defaults import DEFAULT_DOMAINS
    assert "run_tests" in DEFAULT_DOMAINS["verify"].tool_whitelist
    assert "run_tests" in DEFAULT_DOMAINS["user"].tool_whitelist
    for other in ("plan", "execute"):
        assert "run_tests" not in DEFAULT_DOMAINS[other].tool_whitelist


def test_note_evidence_run_tests_sets_run_ok(tmp_path):
    from wuxing.config import EngineConfig
    from wuxing.registry import DomainRegistry
    from wuxing.runner import Runner
    from wuxing.tools.loader import load_tools

    class _T:
        def __init__(self):
            self.events = []

        def log(self, event, *a, **k):
            self.events.append((event, k))

    cfg = EngineConfig()
    ws = Workspace(tmp_path)
    r = Runner(cfg, DomainRegistry(cfg), ws, None, load_tools(ws))
    r._current_domain_id = "verify"
    r._write_ok = r._read_ok = r._run_ok = False
    r._require_run = False
    r._deliverables = []
    r.trace = _T()
    r._note_evidence("run_tests", {"command": "python -m unittest discover"},
                     "ok", "....\nOK\n", unit_id="V-1")
    assert r._run_ok
    assert any(e == "run_evidence" and k.get("via") == "model"
               for e, k in r.trace.events)
