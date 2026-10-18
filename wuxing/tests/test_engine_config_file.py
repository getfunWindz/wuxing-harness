import pathlib
import tempfile

from wuxing.config import EngineConfig
from wuxing.engine import Engine


def test_engine_loads_config_file():
    with tempfile.TemporaryDirectory() as tmp:
        wd = pathlib.Path(tmp)
        (wd / "config.jsonc").write_text('{"max_loop_rounds": 4}', encoding="utf-8")
        eng = Engine(workdir=wd, auto_confirm=True)  # 自动装载 cfg
        assert eng.cfg.max_loop_rounds == 4

def test_engine_programmatic_cfg_overrides_file():
    with tempfile.TemporaryDirectory() as tmp:
        wd = pathlib.Path(tmp)
        (wd / "config.jsonc").write_text('{"max_loop_rounds": 4}', encoding="utf-8")
        eng = Engine(cfg=EngineConfig(max_loop_rounds=2), workdir=wd)
        assert eng.cfg.max_loop_rounds == 2  # 程序化优先

def test_engine_invalid_config_file_raises():
    with tempfile.TemporaryDirectory() as tmp:
        wd = pathlib.Path(tmp)
        (wd / "config.jsonc").write_text('{"max_loop_rounds": "bad"}', encoding="utf-8")
        try:
            Engine(workdir=wd, auto_confirm=True)
            assert False
        except Exception as e:
            assert "max_loop_rounds" in str(e)
