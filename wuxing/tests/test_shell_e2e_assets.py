"""U14：壳 E2E 入库资产（e2e/）的结构 / 可移植性 / 关键能力守卫。

口径：机械约束——资产在位、无机器专有路径、夹具可运行时生成、
.gitignore 覆盖运行产物。不依赖浏览器（E2E 断言由 run_all 承担）。
"""
import importlib.util
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
E2E_SHELL = ROOT / "e2e" / "shell"

REQUIRED = [
    "README.md",  # e2e/ 顶层
    "shell/serve_fake.py",
    "shell/serve_fake_modes.py",
    "shell/g8_seed.py",
    "shell/restart_fixture.py",
    "shell/run_all.py",
    "shell/package.json",
    "shell/package-lock.json",
    "shell/.gitignore",
    "shell/wayfinder_check.js",
    "shell/modes_check.js",
    "shell/check_next_slice.js",
    "shell/context_check.js",
    "shell/e2_ui_check.js",
    "shell/g8_m3_check.js",
    "shell/u5_remaining_check.js",
    "shell/ui_fixes_check.js",
    "shell/check_slice_robust.js",
    "shell/g1_branch_check.js",
]

_MACHINE_PATH = re.compile(r"(?i)[A-Z]:[\\/]Users[\\/]")


def _load_serve_fake():
    spec = importlib.util.spec_from_file_location(
        "e2e_serve_fake", E2E_SHELL / "serve_fake.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_required_assets_present():
    missing = [p for p in REQUIRED if not (ROOT / "e2e" / p).is_file()]
    assert missing == [], f"缺少资产：{missing}"


def test_no_machine_specific_paths():
    bad = []
    for path in sorted(E2E_SHELL.glob("*")):
        if path.suffix not in (".js", ".py"):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if _MACHINE_PATH.search(text):
            bad.append(path.name)
    assert bad == [], f"含机器专有路径：{bad}"


def test_package_declares_puppeteer():
    import json
    pkg = json.loads((E2E_SHELL / "package.json").read_text(encoding="utf-8"))
    assert "puppeteer-core" in pkg.get("dependencies", {})


def test_gitignore_covers_runtime_artifacts():
    text = (E2E_SHELL / ".gitignore").read_text(encoding="utf-8")
    for pat in ("node_modules/", "fake-ws/", "fake-ws2/", "fake-ws-keep/",
                "g8-par-ws/", "g8-claim-ws/", ".runtime/", "visual/"):
        assert pat in text, f".gitignore 缺 {pat}"


def test_serve_fake_branch_support():
    mod = _load_serve_fake()
    assert hasattr(mod.FakeEngine, "branch_conversation")
    assert hasattr(mod.FakeEngine, "_llm_is_mock")


def test_seed_fixture2_writes_round_conversation(tmp_path):
    mod = _load_serve_fake()
    base2 = tmp_path / "fake-ws2"
    mod._seed_fixture2(base2)
    conv = base2 / ".wuxing" / "conversation-1710000400.jsonl"
    assert conv.is_file()
    import json
    row = json.loads(conv.read_text(encoding="utf-8").splitlines()[0])
    assert row["round"] == 1 and "user_text" in row


def test_title_stub_delay_env(monkeypatch):
    mod = _load_serve_fake()
    monkeypatch.setenv("FAKE_TITLE_DELAY_MS", "1")
    assert mod._title_stub(pathlib.Path("conversation-1710000000.jsonl"))


def test_branch_conversation_accepts_str_workdir(tmp_path):
    """夹具引擎必须容忍 manager 传入的 str workdir（g1 分支 500 的历史根因）。"""
    import json
    mod = _load_serve_fake()
    ws = tmp_path / "ws"
    (ws / ".wuxing").mkdir(parents=True)
    (ws / ".wuxing" / "conversation-1710000100.jsonl").write_text(
        json.dumps({"round": 1, "user_text": "任务", "summary": "done",
                    "artifacts": [], "ts": 1.0}, ensure_ascii=False) + "\n",
        encoding="utf-8")
    eng = mod.FakeEngine(str(ws), False)
    out = eng.branch_conversation("conversation-1710000100.jsonl", 1,
                                  mode="redo", summary="mech")
    assert out["mode"] == "redo" and out["summary_mode"] == "mech"


def test_discover_models_patch_targets_route_module():
    """Q1 拆分（api_routes）后，夹具的 discover_models 打桩目标必须是路由模块。"""
    text = (E2E_SHELL / "serve_fake.py").read_text(encoding="utf-8")
    assert "api_routes.providers" in text
    assert "api_mod.discover_models" not in text


def test_modes_fixture_run_task_accepts_overrides():
    """A 套件夹具需兼容 manager 现行 run_task 调用（overrides kwarg）。"""
    import inspect
    spec = importlib.util.spec_from_file_location(
        "e2e_serve_fake_modes", E2E_SHELL / "serve_fake_modes.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert "overrides" in inspect.signature(mod.FakeEngine.run_task).parameters
