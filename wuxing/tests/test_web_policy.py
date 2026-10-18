"""E2-5：web_policy 纯函数——域名策略 + 私网判定 + scheme 白名单。

纪律：策略纯函数（可测、零网络）；DNS 解析复检在 fetch 路径（`resolve_private`，
测试可注入）——策略层保持离线可测。
"""
import pytest

from wuxing.web_policy import check_url, host_allowed, is_private_host


def test_deny_first_and_suffix_match():
    assert not host_allowed("a.evil.com", allow=(), deny=("evil.com",))
    assert host_allowed("docs.python.org", allow=("python.org",), deny=())
    assert host_allowed("python.org", allow=("python.org",), deny=())
    assert not host_allowed("notpython.org", allow=("python.org",), deny=())
    # deny 优先于 allow（同域同时出现 → 拒）
    assert not host_allowed("x.com", allow=("x.com",), deny=("x.com",))


def test_allow_empty_means_all_except_deny():
    assert host_allowed("example.com", allow=(), deny=())
    assert not host_allowed("example.com", allow=(), deny=("example.com",))


def test_host_allow_case_insensitive_and_subdomain():
    assert host_allowed("Docs.Python.Org", allow=("python.org",), deny=())
    assert not host_allowed("python.org.evil.com", allow=("python.org",), deny=())


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "10.1.2.3",
                                  "192.168.1.1", "169.254.0.1", "::1",
                                  "0.0.0.0", "foo.localhost"])
def test_private_hosts_rejected(host):
    assert is_private_host(host)


def test_public_literals_pass():
    assert not is_private_host("8.8.8.8")
    assert not is_private_host("1.1.1.1")


def test_scheme_allowlist():
    assert check_url("https://example.com/x") is None
    assert check_url("http://example.com/x") is None
    with pytest.raises(ValueError):
        check_url("file:///etc/passwd")
    with pytest.raises(ValueError):
        check_url("ftp://example.com/x")


def test_check_url_private_and_policy():
    with pytest.raises(ValueError):
        check_url("http://127.0.0.1/admin")
    with pytest.raises(ValueError):
        check_url("https://a.evil.com/", allow=(), deny=("evil.com",))
    assert check_url("https://docs.python.org/3/", allow=("python.org",),
                     deny=()) is None


def test_check_url_rejects_userinfo_and_bad_host():
    # userinfo 混淆（http://evil.com@127.0.0.1/）解析后 host=127.0.0.1 → 私网拒
    with pytest.raises(ValueError):
        check_url("http://evil.com@127.0.0.1/")
    with pytest.raises(ValueError):
        check_url("https://")
