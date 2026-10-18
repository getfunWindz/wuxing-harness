from wuxing.task_miner import DEFAULT_REPOS, clean_task_text, mine_tasks


def test_clean_task_text_removes_boilerplate():
    raw = "## Description\n\n我们需要修复登录bug\n\n<!-- This is a comment -->\nFixes #123"
    out = clean_task_text(raw)
    assert "登录" in out
    assert "<!--" not in out

def test_clean_truncates():
    raw = "x" * 10000
    assert len(clean_task_text(raw)) <= 2000

def test_mine_tasks_with_fake_fetcher():
    tasks = mine_tasks(repos=["fake/repo"], fetcher=lambda repo: [
        {"title": "修复登录验证", "body": "用户登录后 403", "url": "https://github.com/a/b/issues/1"},
    ])
    assert len(tasks) == 1
    # clean 单空格规范化，断言语义（标题+正文都在）
    assert "修复登录验证" in tasks[0]["task_text"]
    assert "用户登录后 403" in tasks[0]["task_text"]

def test_default_repos_configured():
    assert len(DEFAULT_REPOS) >= 5
