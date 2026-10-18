"""GitHub 任务采集（P8：训练集扩展——真实 issue/PR → harness 域评估任务文本）。

公开 API 限速 60/h（无 token）；提供 GITHUB_TOKEN → 5000/h。
fetcher 可注入（测试离线）。清洗：去 HTML 注释/样板、截断 2000 字。
"""
import json
import pathlib
import re

import requests

DEFAULT_REPOS = [
    "pallets/flask", "psf/requests", "django/django", "pandas-dev/pandas",
    "numpy/numpy", "scikit-learn/scikit-learn", "pytest-dev/pytest",
    "sphinx-doc/sphinx", "microsoft/vscode", "rust-lang/rust",
]

def fetch_repo_issues(repo, token=None, limit=30) -> list:
    """拉取 repo 的 open issues（issue 列表含 PR，过滤掉）。"""
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = f"https://api.github.com/repos/{repo}/issues"
    r = requests.get(url, params={"state": "open", "per_page": limit},
                     headers=headers, timeout=30)
    r.raise_for_status()
    return [{"title": i.get("title", ""), "body": i.get("body") or "",
             "url": i.get("html_url", "")} for i in r.json()
            if "pull_request" not in i]  # 排除 PR（issue 列表含 PR）

def clean_task_text(raw: str, max_len: int = 2000) -> str:
    raw = re.sub(r"<!--.*?-->", "", raw, flags=re.DOTALL)
    raw = re.sub(r"\s+", " ", raw).strip()
    return raw[:max_len]

def mine_tasks(fetcher=None, repos=None, token=None, limit=30) -> list:
    """采集任务文本列表：[{"task_text", "source"}...]。fetcher 可注入（测试）。"""
    fetcher = fetcher or (lambda repo: fetch_repo_issues(repo, token, limit))
    tasks = []
    for repo in (repos or DEFAULT_REPOS):
        try:
            for item in fetcher(repo):
                text = clean_task_text(f"{item['title']} {item['body']}")
                if len(text) >= 10:  # 有效任务（中文语义 10 字符已成立；英文按字符同样适用）
                    tasks.append({"task_text": text, "source": item.get("url", repo)})
        except Exception as e:
            print(f"[miner] skip {repo}: {e}")
    return tasks

def save_tasks(tasks, path: pathlib.Path):
    path.write_text(json.dumps({"version": "p8", "tasks": tasks},
                               ensure_ascii=False, indent=2), encoding="utf-8")
