"""协议单源（TS 生成）守卫测试。

契约源：`wuxing/events.py`（引擎事件载荷）+ `wuxing/shell/web/contracts.py`（壳事件与映射）。
生成物：`apps/shell/web/src/protocol/generated.ts`（提交入 git；本测试防漂移）。
"""
import dataclasses

from wuxing.shell.web import contracts


def test_engine_event_map_covers_all_engine_event_classes():
    from wuxing import events
    engine_classes = {
        name for name, obj in vars(events).items()
        if isinstance(obj, type) and dataclasses.is_dataclass(obj)
    }
    assert set(contracts.ENGINE_EVENT_TYPE_MAP) == engine_classes


def test_generate_is_deterministic():
    from scripts.gen_protocol_ts import generate
    assert generate() == generate()


def test_generated_protocol_is_current():
    from scripts.gen_protocol_ts import OUT_PATH, generate
    current = OUT_PATH.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert current == generate(), (
        "generated.ts 与契约源不一致——运行：python -m scripts.gen_protocol_ts")


def test_ts_type_mapping():
    from scripts.gen_protocol_ts import ts_type
    assert ts_type(str) == "string"
    assert ts_type(int) == "number"
    assert ts_type(float) == "number"
    assert ts_type(bool) == "boolean"
    assert ts_type(str | None) == "string | null"
    assert ts_type(str | int | float | bool | None) == \
        "string | number | boolean | null"   # 联合去重（E2-UI default）
    assert ts_type(list[str]) == "string[]"
    assert ts_type(dict) == "Record<string, unknown>"


def test_generated_contains_rest_dtos():
    from scripts.gen_protocol_ts import generate
    out = generate()
    for name in ("HealthDto", "WorkspaceListDto", "SnapshotDto", "SubmitDto"):
        assert f"export interface {name} {{" in out


def test_rest_dto_map_is_ts_safe():
    import typing

    from scripts.gen_protocol_ts import ts_type
    from wuxing.shell.web import contracts

    for dto in contracts.REST_DTOS.values():
        hints = typing.get_type_hints(dto)
        for name, tp in hints.items():
            rendered = ts_type(tp)
            assert rendered != "unknown", f"{dto.__name__}.{name} 类型未覆盖：{tp!r}"
