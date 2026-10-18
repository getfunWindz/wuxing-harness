"""生成壳协议 TS 类型（单一事实来源 → apps/shell/web/src/protocol/generated.ts）。

契约源：
  - wuxing/shell/web/version.py（版本常量）
  - wuxing/events.py（引擎事件载荷 dataclass）
  - wuxing/shell/web/contracts.py（事件类型映射 + 壳事件载荷）

用法：
  python -m scripts.gen_protocol_ts            # 写入产物
  python -m scripts.gen_protocol_ts --check    # 对拍（CI/本地门禁；不一致 → 1）
"""
from __future__ import annotations

import dataclasses
import pathlib
import sys
import types as pytypes
import typing

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT_PATH = REPO_ROOT / "apps" / "shell" / "web" / "src" / "protocol" / "generated.ts"

_HEADER = """/**
 * 本文件由脚本生成——禁止手改。
 *
 * 契约源：
 *   - wuxing/shell/web/version.py
 *   - wuxing/events.py
 *   - wuxing/shell/web/contracts.py
 * 生成命令：python -m scripts.gen_protocol_ts
 * 对拍检查：python -m scripts.gen_protocol_ts --check
 */
"""


def ts_type(annotation: object) -> str:
    """Python 注解 → TS 类型（覆盖契约中实际使用的形态）。"""
    if annotation is str:
        return "string"
    if annotation in (int, float):
        return "number"
    if annotation is bool:
        return "boolean"
    if annotation is type(None):
        return "null"
    if isinstance(annotation, type) and dataclasses.is_dataclass(annotation):
        return annotation.__name__
    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)
    if annotation is dict:
        return "Record<string, unknown>"
    if annotation is list:
        return "unknown[]"
    if origin in (typing.Union, pytypes.UnionType):
        parts = [ts_type(a) for a in args if a is not type(None)]
        if type(None) in args:
            parts.append("null")
        parts = list(dict.fromkeys(parts))   # 去重（如 str|int|float|bool|None）
        return " | ".join(parts) if parts else "unknown"
    if origin in (list, tuple):
        return f"{ts_type(args[0])}[]" if args else "unknown[]"
    if origin is dict:
        return "Record<string, unknown>"
    return "unknown"


def _fields(cls: type) -> list[tuple[str, str]]:
    hints = typing.get_type_hints(cls)
    return [(f.name, ts_type(hints.get(f.name, str)))
            for f in dataclasses.fields(cls)]


def _collect() -> list[tuple[str, type]]:
    """(事件类型名, 载荷 dataclass) 列表——契约顺序，保证输出确定性。"""
    from wuxing import events as engine_events
    from wuxing.shell.web import contracts

    items: list[tuple[str, type]] = []
    for cls_name, event_type in contracts.ENGINE_EVENT_TYPE_MAP.items():
        items.append((event_type, getattr(engine_events, cls_name)))
    for event_type, payload in contracts.SHELL_EVENT_PAYLOADS.items():
        items.append((event_type, payload))
    return items


def generate() -> str:
    from wuxing.shell.web import contracts, version

    parts: list[str] = [_HEADER]
    parts.append(f"export const API_VERSION = {version.API_VERSION} as const;\n")
    parts.append(f'export const API_PREFIX = "{version.API_PREFIX}" as const;\n')
    parts.append(
        f'export const SHELL_VERSION = "{version.SHELL_VERSION}" as const;\n')
    parts.append(
        "\n/** 事件类型 → 载荷（信封 data 字段）映射。 */\n"
        "export interface EventDataMap {\n")
    for event_type, payload_cls in _collect():
        parts.append(f"  {event_type}: {{\n")
        for name, ts in _fields(payload_cls):
            parts.append(f"    {name}: {ts};\n")
        parts.append("  };\n")
    parts.append("}\n")
    parts.append("\nexport type EventType = keyof EventDataMap;\n")
    parts.append(
        "\n/** 事件信封（EventHub §4.2 契约）。 */\n"
        "export interface EventEnvelope<TType extends EventType = EventType> {\n"
        "  v: number;\n"
        "  epoch: string;\n"
        "  seq: number;\n"
        "  ts: number;\n"
        "  workspace_id: string;\n"
        "  run_id: string;\n"
        "  type: TType;\n"
        "  data: EventDataMap[TType];\n"
        "}\n")
    parts.append(
        "\n/** 任意具体事件（判别联合）。 */\n"
        "export type AnyEvent = { [K in EventType]: EventEnvelope<K> }[EventType];\n")
    parts.append("\n// ---- REST DTO（响应契约）----\n")
    for dto_name, dto_cls in contracts.REST_DTOS.items():
        parts.append(f"\nexport interface {dto_name} {{\n")
        for name, ts in _fields(dto_cls):
            parts.append(f"  {name}: {ts};\n")
        parts.append("}\n")
    return "".join(parts)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    expected = generate()
    if "--check" in args:
        if not OUT_PATH.is_file():
            print(f"[protocol] 产物缺失：{OUT_PATH}")
            return 1
        actual = OUT_PATH.read_text(encoding="utf-8").replace("\r\n", "\n")
        if actual != expected:
            print("[protocol] 对拍失败——generated.ts 与契约源不一致")
            print("[protocol] 修复：python -m scripts.gen_protocol_ts")
            return 1
        print("[protocol] 对拍通过")
        return 0
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(expected, encoding="utf-8", newline="\n")
    print(f"[protocol] 已生成 {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
