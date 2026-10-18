"""TDD（双模式批 2 · Task 2）：黄金期档位——纯函数 + 投影集成 + 不可用路径。"""
import pathlib
import tempfile


def test_context_band_thresholds():
    from wuxing.context_preview import context_band
    assert context_band(0.0) == "golden"
    assert context_band(0.2) == "golden"       # 20% 归黄金（≤）
    assert context_band(0.2001) == "normal"
    assert context_band(0.5) == "normal"       # 50% 归正常（≤）
    assert context_band(0.5001) == "managed"
    assert context_band(0.9, 0.1, 0.3) == "managed"
    assert context_band("bad") == "golden"     # 容错 → 0.0


def test_preview_includes_band_and_thresholds(tmp_path):
    from wuxing.config import EngineConfig
    from wuxing.conversation import ConversationState
    from wuxing.engine import Engine
    wd = pathlib.Path(tempfile.mkdtemp())
    conv = wd / ".wuxing" / "conversation-1.jsonl"
    st = ConversationState(conv)
    st.append_turn(1, "短需求", [], "完成")
    # 默认窗口（200k）+ 短会话 → 黄金档
    eng = Engine(cfg=EngineConfig(use_real_shape=False), workdir=wd,
                 auto_confirm=True)
    d = eng.preview_session_context(conversation_path=conv)
    assert d["available"] is True
    assert d["band"] == "golden"
    assert d["golden_pct"] == 0.2 and d["managed_pct"] == 0.5
    # 极小窗口 → 严管档（同一会话）
    eng2 = Engine(cfg=EngineConfig(use_real_shape=False,
                                   default_context_window=10),
                  workdir=wd, auto_confirm=True)
    d2 = eng2.preview_session_context(conversation_path=conv)
    assert d2["percent"] > 0.5 and d2["band"] == "managed"
    # 不可用路径：band 空串（不假冒档位）
    d3 = eng.preview_session_context(
        conversation_path=wd / ".wuxing" / "nope.jsonl")
    assert d3["available"] is False and d3["band"] == ""


def test_thresholds_read_from_config_with_fallback():
    from types import SimpleNamespace

    from wuxing.context_preview import _thresholds
    ok = SimpleNamespace(cfg=SimpleNamespace(context_golden_pct=0.3,
                                             context_managed_pct=0.7))
    assert _thresholds(ok) == (0.3, 0.7)
    bad = SimpleNamespace(cfg=SimpleNamespace(context_golden_pct=0.8,
                                              context_managed_pct=0.5))
    assert _thresholds(bad) == (0.2, 0.5)   # 非法组合 → 读侧回退默认
    miss = SimpleNamespace(cfg=SimpleNamespace())
    assert _thresholds(miss) == (0.2, 0.5)


def test_preview_thresholds_from_config(tmp_path):
    from wuxing.config import EngineConfig
    from wuxing.context_preview import context_band
    from wuxing.conversation import ConversationState
    from wuxing.engine import Engine
    wd = pathlib.Path(tempfile.mkdtemp())
    conv = wd / ".wuxing" / "conversation-2.jsonl"
    st = ConversationState(conv)
    st.append_turn(1, "短需求", [], "完成")
    eng = Engine(cfg=EngineConfig(use_real_shape=False,
                                  context_golden_pct=0.3,
                                  context_managed_pct=0.7),
                 workdir=wd, auto_confirm=True)
    d = eng.preview_session_context(conversation_path=conv)
    assert d["golden_pct"] == 0.3 and d["managed_pct"] == 0.7
    # 档位随配置阈值推导（机制证明：band = f(percent, 配置阈值)）
    assert d["band"] == context_band(d["percent"], 0.3, 0.7)
