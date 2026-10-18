"""Q2（第二轮优化 §1）：静默吞异常补 logger.debug——抽查 3 处代表性站点。

背景：全库 45 处 ``except …: pass`` 为「观测/优化不阻断」韧性设计（有意保留；
ruff S110 白名单）。本项补 DEBUG 级日志提升可诊断性——默认不输出、语义不变。

抽查点位（磁盘面三兄弟）：trace 写入 / cache 落盘 / provenance 写入。
制造手法：以「同名目录」冒充目标文件路径——写文件动作必抛 OSError，
异常仍被吞掉（不阻断），但对应 DEBUG 日志应出现。
"""
import logging
import pathlib
import tempfile

from wuxing.cache import ReplyCache
from wuxing.provenance import ProvenanceLedger
from wuxing.trace import TraceLogger


def _dir_as_file(name: str) -> pathlib.Path:
    """返回「路径已是目录」的伪文件位点（写它必失败）。"""
    p = pathlib.Path(tempfile.mkdtemp()) / name
    p.mkdir(parents=True, exist_ok=True)
    return p


def test_trace_write_failure_logs_debug(caplog):
    logger = TraceLogger(_dir_as_file("trace.jsonl"))
    with caplog.at_level(logging.DEBUG, logger="wuxing.trace"):
        logger.log("unit_started", "F-1")  # 写入失败被吞——不阻断
    assert any("trace 写入失败" in r.getMessage() for r in caplog.records)


def test_cache_write_failure_logs_debug(caplog):
    cache = ReplyCache(_dir_as_file("reply_cache.json"))
    with caplog.at_level(logging.DEBUG, logger="wuxing.cache"):
        cache.put("k", "v")  # 落盘失败被吞——不阻断
    assert any("缓存写盘失败" in r.getMessage() for r in caplog.records)


def test_provenance_write_failure_logs_debug(caplog):
    led = ProvenanceLedger(_dir_as_file("provenance.jsonl"))
    with caplog.at_level(logging.DEBUG, logger="wuxing.provenance"):
        led.record(unit_id="F-1", parent_id="", task_text="t", goal="g",
                   domain="plan", model="mock", status="ok", artifacts=[])
    assert any("溯源写入失败" in r.getMessage() for r in caplog.records)
