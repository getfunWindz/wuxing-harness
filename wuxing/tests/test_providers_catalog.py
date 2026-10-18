"""R5-1 供应商目录：条目完整性 + host 匹配 + id 派生。"""
import re

from wuxing.config_schema import PROVIDER_TYPES
from wuxing.providers_catalog import (
    CATALOG,
    catalog_entries,
    find_entry,
    match_provider_by_url,
    slug_provider_id,
)


def test_catalog_entries_wellformed():
    ids = [e["id"] for e in CATALOG]
    assert len(ids) == len(set(ids)), "目录 id 必须唯一"
    for e in CATALOG:
        assert re.match(r"^[A-Za-z0-9_-]{1,32}$", e["id"]), e
        assert e["name"].strip()
        assert e["base_url"].startswith(("http://", "https://")), e
        assert e["type"] in PROVIDER_TYPES, e
        assert e["env"] and re.match(r"^[A-Z][A-Z0-9_]*$", e["env"]), e
        assert e["docs"].startswith("https://"), e
        assert e["hosts"], e


def test_catalog_covers_verified_providers():
    ids = {e["id"] for e in CATALOG}
    for expected in ("deepseek", "moonshot", "zhipu", "dashscope", "siliconflow",
                     "ark", "openai", "anthropic", "google", "groq",
                     "openrouter", "ollama"):
        assert expected in ids


def test_match_by_url():
    assert match_provider_by_url("https://api.deepseek.com/v1")["id"] == "deepseek"
    assert match_provider_by_url("open.bigmodel.cn/api/paas/v4")["id"] == "zhipu"
    assert match_provider_by_url("https://api.moonshot.ai/v1")["id"] == "moonshot"
    assert match_provider_by_url("http://localhost:11434/v1")["id"] == "ollama"
    assert match_provider_by_url("http://localhost:1234/v1")["id"] == "lmstudio"
    assert match_provider_by_url("https://api.micuapi.ai/v1") is None
    assert match_provider_by_url("") is None
    assert match_provider_by_url("not a url") is None


def test_slug_provider_id():
    assert slug_provider_id("DeepSeek 官方") == "deepseek"
    assert slug_provider_id("My Relay") == "my-relay"
    assert slug_provider_id("") == "provider"
    assert slug_provider_id("x" * 40) == "x" * 32


def test_catalog_entries_are_copies():
    a = catalog_entries()
    a[0]["hosts"].append("evil.example")
    assert "evil.example" not in CATALOG[0]["hosts"]
    assert find_entry("deepseek")["name"] == "DeepSeek 官方"
    assert find_entry("nope") is None
