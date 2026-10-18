"""精确测试框架（B 阶段；原称准测试）——隐藏 rubric + 单轮大对话 + 机械体检 + B/C 评审。

设计：docs/WUXING_准测试框架设计_2026-09-11.md
红线（测试守卫）：
  1. 隐藏 rubric **绝不**写入被测工作区 / 绝不注入任何 harness prompt；
  2. 顺序硬约束：运行 → 冻结快照 → 才释放 rubric 给评审；
  3. 评审输入不含 harness verify 结论（防自评污染）；judge prompt 版本化。
"""
import json
import pathlib
import re

_REQUIRED = ("id", "title", "public_prompt", "hidden_rubric", "evidence_checklist")


def validate_task(task: dict, source: str = "") -> dict:
    """任务结构校验（元数据不完整即 ValueError——引用质量铁律）。"""
    where = f"（{source}）" if source else ""
    if not isinstance(task, dict):
        raise TypeError(f"task 必须是对象{where}")
    for k in _REQUIRED:
        if k not in task:
            raise ValueError(f"缺字段 {k}{where}")
    for k in ("id", "title", "public_prompt"):
        if not isinstance(task[k], str) or not task[k].strip():
            raise ValueError(f"{k} 必须为非空字符串{where}")
    rubric = task["hidden_rubric"]
    if not isinstance(rubric, dict) \
            or not isinstance(rubric.get("version"), str) \
            or not rubric["version"].strip():
        raise ValueError(f"hidden_rubric.version 非法{where}")
    items = rubric.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError(f"hidden_rubric.items 必须为非空列表{where}")
    seen = set()
    for it in items:
        if not isinstance(it, dict):
            raise TypeError(f"rubric 条目必须是对象{where}")
        for k in ("id", "desc", "weight", "checks"):
            if k not in it:
                raise ValueError(f"rubric 条目缺 {k}{where}")
        if not isinstance(it["id"], str) or not it["id"].strip() \
                or it["id"] in seen:
            raise ValueError(f"rubric 条目 id 非法/重复：{it.get('id')}{where}")
        seen.add(it["id"])
        w = it["weight"]
        if not isinstance(w, (int, float)) or isinstance(w, bool) or w <= 0:
            raise ValueError(f"rubric 条目 weight 非法：{it.get('id')}{where}")
        if not isinstance(it["checks"], list) or not it["checks"]:
            raise ValueError(f"rubric 条目 checks 非法：{it.get('id')}{where}")
    pl = rubric.get("pass_line")
    if not isinstance(pl, (int, float)) or isinstance(pl, bool) \
            or not (0 < pl <= 1):
        raise ValueError(f"pass_line 必须在 (0,1]{where}")
    ev = task["evidence_checklist"]
    if not isinstance(ev, list) or not all(isinstance(x, str) for x in ev):
        raise ValueError(f"evidence_checklist 必须为字符串列表{where}")
    return task


def load_tasks(directory) -> list:
    """装载任务目录（*.json——逐个校验；错误带文件名上下文）。"""
    d = pathlib.Path(directory)
    tasks = []
    for p in sorted(d.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ValueError(f"{p.name} JSON 解析失败：{e}") from e
        tasks.append(validate_task(data, source=p.name))
    return tasks


# ---------------- 机械体检（确定性——评审证据基线） ----------------

_INTERNAL_DIRS = {".wuxing", "__pycache__", ".pytest_cache"}
_TEXT_SUFFIXES = (".md", ".txt", ".py", ".json", ".csv", ".yaml", ".yml")
_PROBE_NAMES = {"main.py", "app.py", "cli.py"}


def _iter_files(root: pathlib.Path):
    """工作区文件迭代（确定性排序；排除内部目录）。"""
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if any(part in _INTERNAL_DIRS for part in rel.parts):
            continue
        yield p, rel


def _decode(b: bytes) -> str:
    return (b or b"").decode("utf-8", errors="replace")


_PROBE_TIME_RE = re.compile(r"\d+\.\d+s")


def _normalize_probe(text: str) -> str:
    """探针输出规范化（耗时变体 → 占位——机械体检确定性要求）。"""
    return _PROBE_TIME_RE.sub("<t>s", text)


def mechanical_checkup(workdir, probe_timeout: int = 30,
                       max_entries: int = 2000) -> dict:
    """机械体检（设计 §3——确定性、不写工作区）：

    - 文件清单/大小/类型（排除 .wuxing/__pycache__ 等内部目录）
    - 压缩标记扫描（`[中间 …]`）
    - 语法检查（compile()——不落 .pyc，零副作用）
    - 可运行探测（入口候选 ≤3 个 `--help`，限时；tests/ 存在则跑一次 pytest）
    """
    import subprocess
    import sys
    root = pathlib.Path(workdir)
    files, compressed, syntax_errors, py_candidates = [], [], [], []
    for p, rel in _iter_files(root):
        if len(files) >= max_entries:
            break
        try:
            size = p.stat().st_size
        except OSError:
            continue
        kind = p.suffix.lstrip(".").lower() or "(none)"
        files.append({"path": rel.as_posix(), "size": size, "kind": kind})
        if p.suffix.lower() not in _TEXT_SUFFIXES:
            continue
        try:
            txt = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        n_mark = txt.count("[中间 ")
        if n_mark:
            compressed.append({"path": rel.as_posix(), "count": n_mark})
        if p.suffix.lower() == ".py":
            try:
                compile(txt, str(p), "exec")
            except SyntaxError as e:
                syntax_errors.append({
                    "path": rel.as_posix(),
                    "error": f"SyntaxError: {e.msg} (line {e.lineno})"})
            else:
                if p.name.lower() in _PROBE_NAMES or "if __name__" in txt:
                    py_candidates.append(rel.as_posix())
    probes = []
    for rel in sorted(py_candidates)[:3]:
        cmd = [sys.executable, str(root / rel), "--help"]
        entry = {"path": rel, "cmd": f"python {rel} --help",
                 "returncode": None, "timed_out": False, "output_head": ""}
        try:
            r = subprocess.run(cmd, cwd=str(root), capture_output=True,
                               timeout=probe_timeout, check=False)
            entry["returncode"] = r.returncode
            entry["output_head"] = _normalize_probe(
                (_decode(r.stdout) + _decode(r.stderr))[:400])
        except subprocess.TimeoutExpired as e:
            entry["timed_out"] = True
            entry["output_head"] = _decode(e.stdout or b"")[:400]
        except OSError as e:
            entry["output_head"] = f"OSError: {e}"[:400]
        probes.append(entry)
    tests_probe = None
    tests_dir = root / "tests"
    if tests_dir.is_dir() and any(tests_dir.glob("test_*.py")):
        entry = {"returncode": None, "timed_out": False, "output_head": ""}
        try:
            r = subprocess.run(
                [sys.executable, "-m", "pytest", str(tests_dir), "-q",
                 "-p", "no:cacheprovider"],
                cwd=str(root), capture_output=True, timeout=probe_timeout,
                check=False)
            entry["returncode"] = r.returncode
            entry["output_head"] = _normalize_probe(
                (_decode(r.stdout) + _decode(r.stderr))[:600])
        except subprocess.TimeoutExpired as e:
            entry["timed_out"] = True
            entry["output_head"] = _decode(e.stdout or b"")[:600]
        except OSError as e:
            entry["output_head"] = f"OSError: {e}"[:600]
        tests_probe = entry
    return {"files": files,
            "total_files": len(files),
            "compressed_markers": compressed,
            "py_compile": {"checked": sum(1 for f in files if f["kind"] == "py"),
                           "errors": syntax_errors},
            "run_probes": probes,
            "tests_probe": tests_probe}


# ---------------- 单轮运行器（rubric 不进 harness——红线） ----------------

def run_accuracy_task(task: dict, workdir, llm=None, real_shape: bool = False,
                      max_parallel: int | None = None) -> dict:
    """单轮大对话（设计 §3）：仅注入 `public_prompt`——rubric 绝不参与。

    独立工作区；返回运行元数据（状态/耗时/harness 指标/产物清单）。
    """
    import time

    from wuxing.config import EngineConfig
    from wuxing.engine import Engine
    validate_task(task)
    wd = pathlib.Path(workdir)
    wd.mkdir(parents=True, exist_ok=True)
    cfg = EngineConfig(use_real_shape=bool(real_shape))
    if max_parallel is not None:
        cfg.max_parallel_units = int(max_parallel)
    eng = Engine(cfg=cfg, workdir=wd, llm=llm, auto_confirm=True)
    t0 = time.time()
    res = eng.run_task(task["public_prompt"])
    dur = round(time.time() - t0, 2)
    return {"task_id": task["id"], "status": res.status,
            "duration_s": dur, "metrics": res.metrics or {},
            "artifacts": [a.path for a in (res.artifacts or [])],
            "workdir": str(wd)}


# ---------------- 冻结与评审输入（顺序红线：运行 → 冻结 → 才释放 rubric） ----------------

def freeze_snapshot(workdir, max_file_chars: int = 4000) -> dict:
    """冻结快照：文件 hash 清单 + 内容定格（此后工作区变化可检测）。

    评审只能基于冻结视图——防「运行后改产物」与顺序逆置（设计 §3/§7）。
    """
    import hashlib
    root = pathlib.Path(workdir)
    files, contents = [], {}
    for p, rel in _iter_files(root):
        try:
            data = p.read_bytes()
        except OSError:
            continue
        files.append({"path": rel.as_posix(), "size": len(data),
                      "sha256": hashlib.sha256(data).hexdigest()})
        if p.suffix.lower() in _TEXT_SUFFIXES:
            contents[rel.as_posix()] = data.decode(
                "utf-8", errors="replace")[:max_file_chars]
    return {"files": files, "contents": contents, "total_files": len(files)}


def build_judge_payload(task: dict, checkup: dict, snapshot: dict,
                        max_file_chars: int = 2000,
                        max_total_chars: int = 30000) -> dict:
    """评审输入（盲评）：public_prompt + rubric + 机械体检 + 产物内容摘录。

    红线：不含 harness 自评/状态/模型信息（防自评污染）；总量受限（截断策略）。
    """
    files, total = [], 0
    for f in snapshot.get("files", []):
        path = f["path"]
        excerpt = str(snapshot.get("contents", {}).get(path, ""))[:max_file_chars]
        if total + len(excerpt) > max_total_chars:
            break
        files.append({"path": path, "size": f["size"], "sha256": f["sha256"],
                      "excerpt": excerpt})
        total += len(excerpt)
    return {"public_prompt": task["public_prompt"],
            "rubric": task["hidden_rubric"],
            "mechanical": checkup,
            "files": files}


# ---------------- Judge B（独立评审——版本化/盲评/结构化） ----------------

JUDGE_PROMPT_VERSION = "judge-v1"

_JUDGE_SYSTEM = (
    "你是独立评审（judge）——对被测系统产出的真实工件按隐藏 rubric 逐条客观评分。"
    "只依据提供的工件与机械体检证据；不要臆测未提供的内容；不要参考任何自评结论。"
    "严格输出 JSON（无多余文字）："
    '{"items": [{"id": "R1", "verdict": "pass|partial|fail", '
    '"score": 0.0-1.0, "evidence": "证据", "reason": "理由"}], "total": 0.0-1.0}'
    f"（评分口径版本：{JUDGE_PROMPT_VERSION}）"
)


def build_judge_prompt(payload: dict) -> list:
    """盲评 prompt（版本化）：public_prompt + rubric + 机械体检 + 工件摘录。"""
    user = (f"# 任务（用户原始需求）\n{payload['public_prompt']}\n\n"
            f"# 隐藏 rubric\n"
            f"{json.dumps(payload['rubric'], ensure_ascii=False, indent=2)}\n\n"
            f"# 机械体检（确定性证据）\n"
            f"{json.dumps(payload['mechanical'], ensure_ascii=False)[:8000]}\n\n"
            f"# 工件视图（冻结快照摘录）\n")
    for f in payload.get("files", []):
        user += f"\n## {f['path']}（{f['size']} bytes）\n{f['excerpt']}\n"
    return [{"role": "system", "content": _JUDGE_SYSTEM},
            {"role": "user", "content": user}]


def _extract_json(text) -> dict:
    s = str(text or "")
    i, j = s.find("{"), s.rfind("}")
    if i < 0 or j <= i:
        raise ValueError("judge 输出不含 JSON 对象")
    return json.loads(s[i:j + 1])


def judge_payload(payload: dict, provider, retries: int = 1) -> dict:
    """调用独立 judge 并校验结构化输出（版本化；失败重试一次）。

    总分由**本地加权计算**（rubric 权重 × 条目得分）——不盲信 judge 自报；
    `pass` 用任务自带 pass_line 判定（透明可复现）。
    """
    messages = build_judge_prompt(payload)
    rubric_items = payload["rubric"]["items"]
    want_ids = [it["id"] for it in rubric_items]
    last_err = None
    for _ in range(retries + 1):
        out = provider.chat(messages)
        text = out.text if hasattr(out, "text") else out
        try:
            data = _extract_json(text)
            items = data.get("items")
            if not isinstance(items, list):
                raise TypeError("items 缺失")
            got = []
            for it in items:
                if not isinstance(it, dict):
                    raise TypeError("item 非对象")
                iid = it.get("id")
                if iid not in want_ids or iid in got:
                    raise ValueError(f"item id 非法：{iid}")
                if it.get("verdict") not in ("pass", "partial", "fail"):
                    raise ValueError(f"verdict 非法：{iid}")
                score = it.get("score")
                if not isinstance(score, (int, float)) or isinstance(score, bool) \
                        or not (0 <= float(score) <= 1):
                    raise ValueError(f"score 非法：{iid}")
                got.append(iid)
            if sorted(got) != sorted(want_ids):
                raise ValueError("rubric 条目覆盖不完整")
            by_id = {it["id"]: it for it in items}
            wsum = sum(float(it["weight"]) for it in rubric_items)
            total = (sum(float(it["weight"]) * float(by_id[it["id"]]["score"])
                         for it in rubric_items) / wsum) if wsum else 0.0
            total = round(total, 4)
            return {
                "items": [{"id": it["id"],
                           "verdict": by_id[it["id"]]["verdict"],
                           "score": round(float(by_id[it["id"]]["score"]), 4),
                           "evidence": str(by_id[it["id"]].get("evidence", ""))[:500],
                           "reason": str(by_id[it["id"]].get("reason", ""))[:500]}
                          for it in rubric_items],
                "total": total,
                "pass": total >= float(payload["rubric"]["pass_line"]),
                "meta": {"version": JUDGE_PROMPT_VERSION,
                         "model": provider.name() if hasattr(provider, "name") else "?",
                         "judge_total": data.get("total")}}
        except (TypeError, ValueError, json.JSONDecodeError) as e:
            last_err = e
    raise ValueError(f"judge 输出校验失败：{last_err}")


# ---------------- 流水线聚合与报告 ----------------

def gather_pipeline(task: dict, workdir, llm=None, real_shape: bool = False,
                    judge_provider=None, max_parallel: int | None = None,
                    max_file_chars: int = 2000,
                    max_total_chars: int = 30000) -> dict:
    """端到端采集：运行 → 机械体检 → 冻结 → 评审输入 →（可选）judge B。"""
    run_meta = run_accuracy_task(task, workdir, llm=llm, real_shape=real_shape,
                                 max_parallel=max_parallel)
    checkup = mechanical_checkup(workdir)
    snap = freeze_snapshot(workdir)
    payload = build_judge_payload(task, checkup, snap,
                                  max_file_chars=max_file_chars,
                                  max_total_chars=max_total_chars)
    verdict = judge_payload(payload, judge_provider) \
        if judge_provider is not None else None
    return {"task": task, "run": run_meta, "checkup": checkup,
            "snapshot": snap, "verdict": verdict, "payload": payload}


def write_report(out_path, result: dict) -> pathlib.Path:
    """报告落盘（B 分逐条/总分 · 体检 · 快省指标 · C 记录位）。"""
    task, run = result["task"], result["run"]
    chk, v = result["checkup"], result.get("verdict")
    usage = ((run.get("metrics") or {}).get("usage") or {})
    inp = int(usage.get("input", 0) or 0)
    cr = int(usage.get("cache_read", 0) or 0)
    token_rate = f"{cr / inp:.1%}" if inp else "n/a"
    probe = chk.get("tests_probe")
    lines = [f"# 精确测试报告 · {task['id']} {task['title']}", "",
             "## 运行指标（快省）", "",
             f"- 状态：{run.get('status')}",
             f"- 墙钟：{run.get('duration_s')} s",
             f"- token 级缓存命中：{token_rate}（read {cr} / input {inp}）",
             f"- 产物数：{len(result.get('snapshot', {}).get('files', []))}",
             "",
             "## 机械体检", "",
             f"- 文件总数：{chk.get('total_files')}",
             f"- 压缩标记文件：{len(chk.get('compressed_markers', []))}",
             f"- 语法错误：{len(chk.get('py_compile', {}).get('errors', []))}",
             f"- 运行探针：{len(chk.get('run_probes', []))} 个；"
             + (f"tests 探针 rc={probe['returncode']}" if probe else "无 tests"),
             "",
             "## B 分（独立 judge）", ""]
    if v:
        ok = "✅ 通过" if v["pass"] else "❌ 未过"
        lines += [(f"- 总分：**{v['total']}**（pass_line "
                   f"{task['hidden_rubric']['pass_line']} → {ok}）"),
                  f"- 口径：{v['meta']['version']} · judge={v['meta']['model']}",
                  "", "| 条目 | verdict | score | 证据 | 理由 |",
                  "|---|---|---|---|---|"]
        for it in v["items"]:
            lines.append(f"| {it['id']} | {it['verdict']} | {it['score']} | "
                         f"{it['evidence']} | {it['reason']} |")
    else:
        lines.append("（未启用 judge——`--mech-only`）")
    lines += ["", "## C 记录（人工·最终裁决）", "",
              "> 请过一遍关键产物后填写：",
              "1. 一句话：作为真实用户，我会不会直接用它？（1-5 分）",
              "2. 哪里让我抓狂/最不放心（自由问题清单）",
              "3. 备注：", ""]
    out_path = pathlib.Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path
