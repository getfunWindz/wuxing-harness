"""R3-1 凭据存储：write-only、env 优先分层、严格文档、原子写。

DSH 对照：dsh-credentials-local（.credentials.yaml 分层 + assertUnshadowed）。
"""
import json

import pytest


@pytest.fixture(autouse=True)
def _store(tmp_path, monkeypatch):
    import wuxing.credentials as c
    monkeypatch.setattr(c, "credentials_path",
                        lambda: tmp_path / "credentials.json")
    monkeypatch.delenv("WUXING_TEST_KEY", raising=False)
    return c


def test_missing_file_is_empty_store(_store):
    assert _store.resolve("WUXING_TEST_KEY") is None
    d = _store.describe("WUXING_TEST_KEY")
    assert d == {"ref": "WUXING_TEST_KEY", "configured": False, "source": None,
                 "writable": True, "shadowed": False}


def test_set_then_resolve_roundtrip(_store):
    _store.set("WUXING_TEST_KEY", "sk-abc123")
    assert _store.resolve("WUXING_TEST_KEY") == "sk-abc123"
    doc = json.loads(_store.credentials_path().read_text(encoding="utf-8"))
    assert doc["version"] == 1
    assert doc["credentials"]["WUXING_TEST_KEY"] == "sk-abc123"


def test_env_wins_and_write_is_rejected(_store, monkeypatch):
    monkeypatch.setenv("WUXING_TEST_KEY", "sk-env")
    assert _store.resolve("WUXING_TEST_KEY") == "sk-env"
    assert _store.describe("WUXING_TEST_KEY")["source"] == "env"
    assert _store.describe("WUXING_TEST_KEY")["writable"] is False
    with pytest.raises(_store.CredentialShadowed):
        _store.set("WUXING_TEST_KEY", "sk-store")
    assert not _store.credentials_path().exists()


def test_describe_never_exposes_value(_store):
    _store.set("WUXING_TEST_KEY", "sk-secret-material")
    d = _store.describe("WUXING_TEST_KEY")
    assert "sk-secret-material" not in json.dumps(d)


def test_unset_idempotent(_store):
    _store.set("WUXING_TEST_KEY", "sk-a")
    _store.unset("WUXING_TEST_KEY")
    _store.unset("WUXING_TEST_KEY")          # 再次 = no-op
    assert _store.resolve("WUXING_TEST_KEY") is None


def test_invalid_ref_rejected(_store):
    for bad in ("lower", "1ABC", "A-B", "", "A B"):
        with pytest.raises(_store.CredentialError):
            _store.set(bad, "sk-x")


def test_invalid_value_rejected(_store):
    for bad in ("", "   ", "sk-\u4e2d\u6587", "NAME=sk-x", '"sk-x"', "'sk-x'"):
        with pytest.raises(_store.CredentialError):
            _store.set("WUXING_TEST_KEY", bad)


def test_invalid_document_loud(_store):
    _store.credentials_path().write_text("{not json", encoding="utf-8")
    with pytest.raises(_store.CredentialError):
        _store.resolve("WUXING_TEST_KEY")
    with pytest.raises(_store.CredentialError):
        _store.set("WUXING_TEST_KEY", "sk-a")   # 不覆盖无法理解的文档


def test_derive_ref_single_source(_store):
    assert _store.derive_ref("deepseek") == "DEEPSEEK_API_KEY"
    assert _store.derive_ref("micu-claude") == "MICU_CLAUDE_API_KEY"
    assert _store.derive_ref("mock") is None
    assert _store.derive_ref("") is None
