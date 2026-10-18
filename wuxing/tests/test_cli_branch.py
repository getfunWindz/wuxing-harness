"""G1：CLI `wuxing branch` 子命令测试。"""
import json


def _write_turns(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
                    + "\n", encoding="utf-8")


def _turn(rnd, text="任务", summary="done"):
    return {"round": rnd, "user_text": text, "artifacts": [],
            "summary": summary, "ts": 1000.0 + rnd}


def _run_cli(monkeypatch, argv):
    from wuxing import cli
    monkeypatch.setattr("sys.argv", ["wuxing"] + argv)
    return cli.main()


def test_cli_branch_creates_session(tmp_path, monkeypatch, capsys):
    src = tmp_path / ".wuxing" / "conversation-src.jsonl"
    _write_turns(src, [_turn(1, "第一轮"), _turn(2, "第二轮")])
    code = _run_cli(monkeypatch, [
        "branch", "--workdir", str(tmp_path), "--session",
        "conversation-src.jsonl", "--from-round", "2", "--mode", "redo",
        "--summary", "mech"])
    out = capsys.readouterr().out
    assert code in (0, None)
    assert "新会话：" in out
    assert "第 2 轮" in out
    assert "摘要：mech" in out
    assert "回填文本：第二轮" in out
    # 文件真实创建
    names = [p.name for p in (tmp_path / ".wuxing").glob("conversation-*.jsonl")
             if p.name != "conversation-src.jsonl"]
    assert names


def test_cli_branch_error_exit_code(tmp_path, monkeypatch, capsys):
    src = tmp_path / ".wuxing" / "conversation-src.jsonl"
    _write_turns(src, [_turn(1, "第一轮")])
    code = _run_cli(monkeypatch, [
        "branch", "--workdir", str(tmp_path), "--session",
        "conversation-src.jsonl", "--from-round", "9"])
    out = capsys.readouterr().out
    assert code == 2
    assert "error:" in out
