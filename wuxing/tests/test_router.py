from wuxing.router import extract_keywords, route_fragment


def test_extract_keywords_chinese():
    kws = extract_keywords("实现一个带用户登录的网站后端")
    assert "用户" in kws or "登录" in kws

def test_route_by_keyword():
    # 含"验证/测试"→ verify；含"方案/规划"→ plan；含"实现/开发/编写"→ execute
    assert route_fragment("编写用户系统的后端代码") == "execute"
    assert route_fragment("验证系统是否通过测试") == "verify"
    assert route_fragment("制定项目整体方案与路线") == "plan"
    assert route_fragment("定义用户验收标准与体验要求") == "user"

def test_route_fallback_execute():
    # P7 修正（112 套件数据）：无词命中 → execute（默认“干活”域），非 plan
    assert route_fragment("一件不明任务") == "execute"
