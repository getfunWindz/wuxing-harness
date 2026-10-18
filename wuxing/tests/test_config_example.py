"""R5-1/R5-2：配置示例文件——可解析 + 通过引擎校验（最小化模板，不预填供应商/模型）。"""
import pathlib

from wuxing.config_loader import parse_jsonc
from wuxing.config_schema import validate_config

EXAMPLE = (pathlib.Path(__file__).resolve().parents[1]
           / "config.example.jsonc")


def test_example_parses_and_validates():
    data = parse_jsonc(EXAMPLE.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    errors = validate_config(data)
    assert errors == [], errors


def test_example_has_no_prefilled_providers_or_models():
    """R5-2 修正一：模板不预填供应商与模型（避免「内置模型」误解）。"""
    src = EXAMPLE.read_text(encoding="utf-8")
    data = parse_jsonc(src)
    assert "providers" not in data
    assert "llm" not in data
    assert "router" not in data
