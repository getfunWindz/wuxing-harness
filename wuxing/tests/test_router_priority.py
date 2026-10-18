from wuxing.router import route_fragment


def test_test_asset_creation_routes_execute():
    """真测 REAL-3（方案 a）：构造测试/样例资产是执行工作——验证语义不得抢走。

    T1 实况：节点「创建 sample.txt；编写 test_wordcount.py；运行 pytest 并确认…」
    被 verify 关键词抢走 → verify 无产物可读、轮数耗尽 → 任务失败。
    """
    assert route_fragment(
        "创建 sample.txt 样例文本；编写 test_wordcount.py；运行 pytest 并确认全部测试通过"
    ) == "execute"
    assert route_fragment("编写测试用例覆盖边界场景") == "execute"
    assert route_fragment("生成测试数据文件") == "execute"


def test_verification_priority_kept_without_test_asset_creation():
    """既有设计不回归：非构造测试资产的验证语义仍然优先。"""
    assert route_fragment("实现注册接口并验证登录流程") == "verify"
    assert route_fragment("验证测试用例的覆盖率") == "verify"
    assert route_fragment("运行测试并确认全部通过") == "verify"


def test_verify_kw_not_stolen_by_execute():
    # 含"验证/测试"的碎片 → verify（即使也含"实现"——验证语义优先）
    assert route_fragment("实现注册接口并验证登录流程") == "verify"

def test_plan_kw_not_stolen_by_execute():
    # 含"方案/规划" → plan
    assert route_fragment("规划系统架构并实现模块") == "plan"

def test_execute_only_when_clear():
    # 无验证/规划词的纯实现 → execute
    assert route_fragment("编写用户系统的后端代码") == "execute"
