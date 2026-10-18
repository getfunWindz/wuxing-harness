"""TDD · 真实测试（多画像剧本 + 自动注入规则 + 双口径度量）。

依据：用户「真实测试.txt」+ 四项确认（规则化/双口径/失败继续/重复样本）。
"""
import pathlib
import tempfile

# ---------- Task 1: 自动注入规则 ----------

def test_auto_next_plan_review_fallback():
    """规则化注入：计划词→按计划执行；审查词→接受建议；其余→继续。"""
    from wuxing.real_test import auto_next
    assert auto_next("实现步骤：1. 初始化项目 2. 开发模块") == "好的，按计划执行"
    assert auto_next("这是我给的方案：略") == "好的，按计划执行"
    assert auto_next("建议修改以下问题：缺陷A、缺陷B") == "接受建议，开始修改"
    assert auto_next("发现一个 bug，需要修复") == "接受建议，开始修改"
    assert auto_next("今天天气不错") == "继续"


def test_auto_next_plan_takes_priority():
    """规则优先级：计划词 > 审查词（用户方案描述顺序——先计划后审查）。"""
    from wuxing.real_test import auto_next
    assert auto_next("计划如下，其中建议有两个阶段") == "好的，按计划执行"


# ---------- Task 2: 画像剧本 ----------

def test_profiles_present_and_shaped():
    """四基础画像 + 四通用画像（2026-09-11 扩展）：novice/expert/beginner/
    precise + writer/analyst/planner/scripter。"""
    from wuxing.real_test import PROFILES
    assert set(PROFILES) == {"novice", "expert", "beginner", "precise",
                             "writer", "analyst", "planner", "scripter"}
    nov = PROFILES["novice"]["turns"]
    assert len(nov) == 9
    assert sum(1 for t in nov if t["kind"] == "auto") == 3   # 第 5/6/7 轮
    assert nov[0]["kind"] == "static"
    assert "springboot" in nov[0]["text"].lower() or "SpringBoot" in nov[0]["text"]
    # 特定功能型：单点深度
    pre = PROFILES["precise"]["turns"]
    assert 3 <= len(pre) <= 5


def test_expert_profile_long_prompts_with_overview():
    """expert 重写（用户裁决）：首轮=项目概况（长提示——真实形状化素材）；
    每轮尽量扩充（行家画像标准——全部长提示）。"""
    from wuxing.real_test import PROFILES
    exp = PROFILES["expert"]["turns"]
    assert len(exp) >= 5
    first = exp[0]["text"]
    assert len(first) > 200, f"首轮项目概况必须长（实际 {len(first)}）"
    for k in ("背景", "技术栈", "模块", "验收"):
        assert k in first, f"项目概况必须含「{k}」"
    # 每轮尽量扩充（静态轮全部 >100 字符）
    for t in exp:
        if t["kind"] == "static":
            assert len(t["text"]) > 100, f"行家每轮扩充（实际 {len(t['text'])}）"


def test_beginner_profile_short_prompts_bug_checks():
    """beginner 新增（用户裁决）：新手型=学校作业/极短单需求/每两轮 bug 检查。"""
    from wuxing.real_test import PROFILES
    beg = PROFILES["beginner"]["turns"]
    assert 6 <= len(beg) <= 8
    # 极短提示（新手——单次需求 ≤30 字符）
    shorts = [t for t in beg if t["kind"] == "static" and "不要出bug" not in t["text"]]
    assert len(shorts) >= 3
    assert all(len(t["text"]) <= 30 for t in shorts),         f"新手提示必须极短：{[len(t['text']) for t in shorts]}"
    # 每两轮一次「全面检查一下代码，不要出bug」（中间隔 2 轮需求）
    checks = [i for i, t in enumerate(beg) if t["kind"] == "static"
              and "不要出bug" in t["text"]]
    assert len(checks) >= 2, "新手必须定期 bug 检查"
    assert checks[1] - checks[0] == 3,         f"检查应每两轮需求一次（实际间隔 {checks[1] - checks[0]}）"


# ---------- Task 3: Runner 核心 ----------

def test_run_profile_mock_full_flow(tmp_path=None):
    """mock 全流程：9 轮跑通、双口径度量齐、报告落盘、失败继续。"""
    from wuxing.real_test import run_profile
    wd = pathlib.Path(tmp_path or tempfile.mkdtemp())
    rows = run_profile("novice", workdir=wd, llm=None, real_shape=False)
    assert len(rows) == 9
    r0 = rows[0]
    for k in ("round", "status", "input", "cache_read", "cache_read_ratio",
              "cumulative_ratio", "context_tokens", "injected", "artifacts"):
        assert k in r0, f"轮次度量缺字段 {k}"
    assert r0["injected"] == "static"
    assert rows[4]["injected"] in ("auto",)  # 第 5 轮 auto（注入内容视输出规则）
    assert (wd / "real_test_report.json").exists()
    assert (wd / "real_test_report.csv").exists()


def test_cli_list_and_smoke():
    """CLI 薄壳：--list 列出三画像；mock 冒烟带 --max-turns。"""
    import os
    import subprocess
    import sys
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    r = subprocess.run(
        [sys.executable, "-m", "scripts.real_test_runner", "--list"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=60, env=env, check=False)
    assert r.returncode == 0
    out = r.stdout or ""
    assert "novice" in out and "expert" in out and "precise" in out
    assert "[自动注入]" in out


def test_run_profile_parallel_param_smoke():
    """S3：max_parallel 参数冒烟（并行度实验支持——mock 跑通 2 轮）。"""
    from wuxing.real_test import run_profile
    wd = pathlib.Path(tempfile.mkdtemp())
    rows = run_profile("precise", workdir=wd, llm=None, real_shape=False,
                       max_turns=2, max_parallel=4)
    assert len(rows) == 2


def test_run_profile_reports_efficiency_metrics():
    """N2：报告必须含效率指标（每 done 耗时/有效轮均值）——「快」的主指标。"""
    from wuxing.real_test import run_profile
    wd = pathlib.Path(tempfile.mkdtemp())
    _ = run_profile("precise", workdir=wd, llm=None, real_shape=False,
                    max_turns=2)
    import json
    payload = json.loads((wd / "real_test_report.json").read_text(encoding="utf-8"))
    summary = payload.get("summary", {})
    assert "done" in summary, "报告必须含 done 计数"
    assert "sec_per_done" in summary, "报告必须含每 done 耗时（快的主指标）"
    assert "avg_effective_ratio" in summary, "报告必须含有效轮均值"


# ---------- 通用化画像（用户裁决 2026-09-11） ----------

def test_general_profiles_present():
    """通用画像：writer（写作型）/analyst（分析型）/planner（规划型）/
    scripter（脚本型）——面向通用场景，保留编程强势。"""
    from wuxing.real_test import PROFILES
    for name in ("writer", "analyst", "planner", "scripter"):
        assert name in PROFILES, f"缺少通用画像 {name}"
    # 写作型：非代码文档任务（方案/推文）
    wr = PROFILES["writer"]["turns"]
    assert 4 <= len(wr) <= 7
    assert any("方案" in t["text"] for t in wr if t["kind"] == "static")
    # 分析型：数据处理（CSV/统计） + 报告产出
    an = PROFILES["analyst"]["turns"]
    assert any("csv" in t["text"].lower() for t in an)
    assert any("报告" in t["text"] for t in an)
    # 规划型：非编程（学习计划/资源/追赶方案）
    pl = PROFILES["planner"]["turns"]
    assert 4 <= len(pl) <= 7
    assert any("计划" in t["text"] for t in pl)
    # 脚本型：小工具 + 测试 + 自检
    sc = PROFILES["scripter"]["turns"]
    assert any("脚本" in t["text"] for t in sc)
    assert any("测试" in t["text"] for t in sc)


def test_run_profile_reports_request_level_cache_metric():
    """口径固化（用户裁决 2026-09-11）：报告同时含请求级命中率与 token 级
    命中率——控制台 99.5%（请求级）与报告 64.7%（token 级）不再混淆。"""
    import json

    from wuxing.real_test import run_profile
    wd = pathlib.Path(tempfile.mkdtemp())
    run_profile("precise", workdir=wd, llm=None, real_shape=False, max_turns=2)
    payload = json.loads((wd / "real_test_report.json").read_text(encoding="utf-8"))
    summary = payload.get("summary", {})
    assert "request_hit_rate" in summary, "摘要必须含请求级命中率"
    assert "token_hit_rate" in summary, "摘要必须含 token 级命中率"
    row = payload["turns"][0]
    for k in ("llm_calls", "hit_calls", "request_hit_rate"):
        assert k in row, f"轮级必须含字段 {k}"
    for r in payload["turns"]:
        if r.get("llm_calls"):
            assert 0 <= r["hit_calls"] <= r["llm_calls"]


def test_precise_profile_wide_turns():
    """precise 修订（用户裁决 2026-09-11）：对标行家第一轮——每轮均为宽任务
    （多个独立子任务并行交付），保持 3 轮。"""
    from wuxing.real_test import PROFILES
    pre = PROFILES["precise"]["turns"]
    assert len(pre) == 3
    for t in pre:
        text = t["text"]
        assert "独立" in text, f"每轮必须明示独立子任务：{text[:40]}"
        assert text.count("①") + text.count("②") + text.count("③") >= 3


def test_general_profiles_professional_terms():
    """通用画像修订（用户裁决）：专业术语陈述（非口语）——考察 harness 区分能力。"""
    from wuxing.real_test import PROFILES
    joined = {name: "\n".join(t["text"] for t in PROFILES[name]["turns"])
              for name in ("writer", "analyst", "planner", "scripter")}
    assert "KPI" in joined["writer"] and "调性" in joined["writer"]
    assert "描述性统计" in joined["analyst"] and "口径" in joined["analyst"]
    assert "里程碑" in joined["planner"] and "资源矩阵" in joined["planner"]
    assert "幂等" in joined["scripter"] and "退出码" in joined["scripter"]
