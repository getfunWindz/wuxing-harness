"""路由表特征化（Q1 register_api 拆分安全网）：清单锁定 + 无重叠证明。

拆分为分组模块后，注册顺序按模块分组变化；本测试证明两件事：
1. 路由全集（method+pattern）与拆分前逐条一致（清单锁定）；
2. 同方法路由两两无样例重叠——注册顺序不影响分派（顺序变化合法）。

DummyMgr：仅需 manager.hub（注册期访问），不启动服务、不触碰引擎。
"""
import itertools
import re

from wuxing.shell.web.api import register_api
from wuxing.shell.web.hub import EventHub
from wuxing.shell.web.server import ShellServer


class _DummyMgr:
    hub = EventHub()


def _route_table():
    srv = ShellServer(port=0)
    register_api(srv, _DummyMgr())
    return [(m, p.pattern) for m, p, _fn in srv.routes]


# Q1 拆分前基线（2026-09-28 · 87 条）+ A10 answer + E3-1/R5（T5）worktree 3 条
# + O2-2 P3 浏览器允许条目 2 条 + 重大优化清单 #3 域提示词 2 条 + §11.5-① 身份 2 条
# （现行 97 条 = /health + 96 API）——逐条锁定，新增路由须同步本清单
_EXPECTED_ROUTES = [
    ('DELETE', '^/api/v1/credentials/(?P<ref>[^/]+)$'),
    ('DELETE', '^/api/v1/folders/(?P<fid>[0-9a-f]+)$'),
    ('DELETE', '^/api/v1/recycle/(?P<eid>[0-9a-zA-Z]+)$'),
    ('DELETE', '^/api/v1/skills/(?P<name>[^/]+)$'),
    ('DELETE', '^/api/v1/workspaces/(?P<ws>[0-9a-f]+)$'),
    ('GET', '^/api/v1/about$'),
    ('GET', '^/api/v1/browser/allow$'),
    ('GET', '^/api/v1/browser/identity$'),
    ('GET', '^/api/v1/config$'),
    ('GET', '^/api/v1/config/schema$'),
    ('GET', '^/api/v1/credentials/(?P<ref>[^/]+)$'),
    ('GET', '^/api/v1/events$'),
    ('GET', '^/api/v1/events/log$'),
    ('GET', '^/api/v1/fs/list$'),
    ('GET', '^/api/v1/interaction$'),
    ('GET', '^/api/v1/maintenance$'),
    ('GET', '^/api/v1/mcp$'),
    ('GET', '^/api/v1/notifications$'),
    ('GET', '^/api/v1/prompts/domains$'),
    ('GET', '^/api/v1/providers/catalog$'),
    ('GET', '^/api/v1/recycle$'),
    ('GET', '^/api/v1/search$'),
    ('GET', '^/api/v1/skills$'),
    ('GET', '^/api/v1/skills/(?P<name>[^/]+)$'),
    ('GET', '^/api/v1/workspaces$'),
    ('GET', '^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/artifacts/(?P<path>.+)$'),
    ('GET', '^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/brain$'),
    ('GET', '^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/config$'),
    ('GET', '^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/context-preview$'),
    ('GET', '^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/context-previews$'),
    ('GET', '^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/context-sources$'),
    ('GET', '^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/decisions$'),
    ('GET', '^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/design-state$'),
    ('GET', '^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/extensions/commands$'),
    ('GET', '^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/files$'),
    ('GET', '^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/handoff-brief$'),
    ('GET', '^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/map$'),
    ('GET', '^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/observe/provenance$'),
    ('GET', '^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/observe/trace$'),
    ('GET', '^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/presets$'),
    ('GET', '^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/reports$'),
    ('GET', '^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/session-modes$'),
    ('GET', '^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/session-preset$'),
    ('GET', '^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/sessions$'),
    ('GET', '^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/sessions/(?P<name>[^/]+)$'),
    ('GET', '^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/sessions/(?P<name>[^/]+)/export$'),
    ('GET', '^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/sessions/(?P<name>[^/]+)/rounds$'),
    ('GET', '^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/skills$'),
    ('GET', '^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/snapshot$'),
    ('GET', '^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/tasks/(?P<run>[0-9a-f]+)/worktree$'),
    ('GET', '^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/tasks/history$'),
    ('GET', '^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/tickets$'),
    ('GET', '^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/trajectory$'),
    ('GET', '^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/unit-sessions/(?P<unit>[^/]+)$'),
    ('GET', '^/health$'),
    ('PATCH', '^/api/v1/folders/(?P<fid>[0-9a-f]+)$'),
    ('PATCH', '^/api/v1/skills/(?P<name>[^/]+)$'),
    ('POST', '^/api/v1/browser/allow/revoke$'),
    ('POST', '^/api/v1/browser/identity/clear$'),
    ('POST', '^/api/v1/dialog/pick$'),
    ('POST', '^/api/v1/folders$'),
    ('POST', '^/api/v1/interaction$'),
    ('POST', '^/api/v1/maintenance/clean$'),
    ('POST', '^/api/v1/mcp/reload$'),
    ('POST', '^/api/v1/prompts/domains$'),
    ('POST', '^/api/v1/providers/discover$'),
    ('POST', '^/api/v1/recycle/(?P<eid>[0-9a-zA-Z]+)/restore$'),
    ('POST', '^/api/v1/skills/discover$'),
    ('POST', '^/api/v1/skills/install$'),
    ('POST', '^/api/v1/workspaces$'),
    ('POST', '^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/abandon$'),
    ('POST', '^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/archive$'),
    ('POST', '^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/bench/cache$'),
    ('POST', '^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/conversations/(?P<name>[^/]+)/context-edits$'),
    ('POST', '^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/conversations/branch$'),
    ('POST', '^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/extensions/commands/(?P<command>[a-z][a-z0-9-]*)$'),
    ('POST', '^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/resume$'),
    ('POST', '^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/sessions/(?P<name>[^/]+)/archive$'),
    ('POST', '^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/sessions/(?P<name>[^/]+)/title$'),
    ('POST', '^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/tasks$'),
    ('POST', '^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/tasks/(?P<run>[0-9a-f]+)/answer$'),
    ('POST', '^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/tasks/(?P<run>[0-9a-f]+)/archive$'),
    ('POST', '^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/tasks/(?P<run>[0-9a-f]+)/cancel$'),
    ('POST', '^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/tasks/(?P<run>[0-9a-f]+)/confirm$'),
    ('POST', '^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/tasks/(?P<run>[0-9a-f]+)/resume$'),
    ('POST', '^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/tasks/(?P<run>[0-9a-f]+)/rollback$'),
    ('POST', '^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/tasks/(?P<run>[0-9a-f]+)/worktree/apply$'),
    ('POST', '^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/tasks/(?P<run>[0-9a-f]+)/worktree/discard$'),
    ('POST', '^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/tickets/publish$'),
    ('POST', '^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/tickets/reset$'),
    ('POST', '^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/unit-sessions/(?P<unit>[^/]+)/context-edits$'),
    ('PUT', '^/api/v1/config$'),
    ('PUT', '^/api/v1/credentials/(?P<ref>[^/]+)$'),
    ('PUT', '^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/context-sources$'),
    ('PUT', '^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/design-state$'),
    ('PUT', '^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/folder$'),
    ('PUT', '^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/session-modes$'),
    ('PUT', '^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/session-preset$'),
    ('PUT', '^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/sessions/(?P<name>[^/]+)$'),
    ('PUT', '^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/settings$'),
]


def test_route_inventory_exact():
    """路由全集逐条锁定（拆分前后必须完全一致——含 /health）。"""
    assert sorted(_route_table()) == _EXPECTED_ROUTES


# —— 无重叠证明：注册顺序不影响分派 ——
# 两套样例值（覆盖字面量与通配组混用场景，如 skills/install vs skills/<name>）
_SAMPLES_A = {
    "ws": "0123abcd", "run": "4567ef01", "fid": "89abcdef",
    "unit": "u1", "name": "conv1.jsonl", "path": "docs/a.md",
    "eid": "abc123", "ref": "deepseek", "command": "demo-cmd",
}
_SAMPLES_B = {
    "ws": "deadbeef", "run": "cafebabe", "fid": "01234567",
    "unit": "U-9", "name": "install", "path": "x/y.bin",
    "eid": "Z9", "ref": "openai", "command": "reload",
}


def _sample_urls(pattern):
    """按命名组生成两套样例路径（用于交叉匹配检查）。"""
    out = []
    for samples in (_SAMPLES_A, _SAMPLES_B):
        out.append(re.sub(r"\(\?P<(\w+)>[^)]*\)",
                          lambda m, s=samples: s.get(m.group(1), ""),
                          pattern).strip("^$"))
    return out


def test_no_ambiguous_route_overlaps():
    """同方法路由两两交叉匹配：0 重叠 → 注册顺序不影响分派（拆分前提）。"""
    routes = _route_table()
    overlaps = []
    for (m1, p1), (m2, p2) in itertools.combinations(routes, 2):
        if m1 != m2:
            continue
        r1, r2 = re.compile(p1), re.compile(p2)
        if any(r1.match(u) and r2.match(u)
               for u in _sample_urls(p1) + _sample_urls(p2)):
            overlaps.append((m1, p1, p2))
    assert not overlaps, (
        "存在同方法重叠路由——注册顺序将影响分派，需固定相对顺序："
        f"{overlaps}")
