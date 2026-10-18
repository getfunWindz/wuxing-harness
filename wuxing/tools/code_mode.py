"""Code Mode（X7/A7 · Phase 1——脚本执行通道）。

模型写一段 Python 编排脚本：脚本内经**受限 API**（`unit 白名单 ∩ code_mode_tools`）
调用工具；中间结果留在脚本进程内，仅 stdout 摘要回传上下文（上下文经济学）。

安全与纪律：
- 脚本子进程 = bash 同轴沙箱档位（native：cwd=工作区 + 敏感 env 剥离 +
  超时杀进程树）；**容器档 Phase 1 不支持**（loud 报错，不静默回退）；
- 脚本内每次工具调用经 `ToolRegistry.execute` 统一守卫链（扩展干预 → guard
  （danger_guard 等）→ 权限声明 → schema 校验）——**不得绕过**；
- 执行上下文（registry/白名单/trace/unit）由 runner 在执行前注入（仿 delegate 惯例）；
- 审计：脚本落盘 `<工作区>/.wuxing/code/`；trace `code_mode_run` + 内层
  `tool_call`（via=code_mode）；stdout 超限截断 + 全文落盘（G6 精神）；
- 物证（O3 对齐点/C4）：脚本内写/读/运行经回调上报 runner 证据累计（与模型直调同源；trace `via=code_mode` 可区分来源）。
"""
import json
import logging
import os
import pathlib
import secrets
import socket
import subprocess
import sys
import threading
import time

from wuxing.atomic_write import atomic_write_text
from wuxing.protocols import Tool
from wuxing.tools.bash_tool import _ENV_ALLOW, _decode_output, _kill_tree

logger = logging.getLogger(__name__)

_FORBIDDEN = {"run_script", "ask_user", "delegate"}  # 脚本内恒禁（嵌套/挂起语义）

_BOOTSTRAP = r'''
import json, os, runpy, socket, sys


class _Api:
    def __init__(self):
        self._sock = socket.create_connection(
            ("127.0.0.1", int(os.environ["WUXING_CODE_PORT"])), timeout=30)
        self._f = self._sock.makefile("rw", encoding="utf-8")
        self._token = os.environ["WUXING_CODE_TOKEN"]
        self._tools = json.loads(os.environ["WUXING_CODE_TOOLS"])
        self._n = 0

    def call(self, name, args=None):
        if name not in self._tools:
            raise PermissionError("tool not allowed in code mode: %s" % name)
        self._n += 1
        self._f.write(json.dumps(
            {"token": self._token, "id": self._n, "tool": name,
             "args": args or {}}, ensure_ascii=False) + "\n")
        self._f.flush()
        line = self._f.readline()
        if not line:
            raise RuntimeError("code mode: engine connection closed")
        resp = json.loads(line)
        if resp.get("status") == "ok":
            return resp.get("content", "")
        raise RuntimeError("%s: %s" % (resp.get("status"), resp.get("error")))


_api = _Api()


def _mk(name):
    def _fn(**kwargs):
        return _api.call(name, kwargs)
    _fn.__name__ = name
    return _fn


_g = {n: _mk(n) for n in _api._tools}


def _denied(name):
    def _fn(**kwargs):
        raise PermissionError("tool not allowed in code mode: %s" % name)
    _fn.__name__ = name
    return _fn


for _n in json.loads(os.environ.get("WUXING_CODE_SUBSET", "[]")):
    if _n not in _g:
        _g[_n] = _denied(_n)
_g["tool"] = _api.call
runpy.run_path(sys.argv[1], run_name="__main__", init_globals=_g)
'''


class _RpcServer:
    """单脚本 RPC 服务（127.0.0.1 随机端口 + token；线程 accept）。"""

    def __init__(self, handler):
        self._handler = handler
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(4)
        self._sock.settimeout(0.3)
        self.port = int(self._sock.getsockname()[1])
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._serve, daemon=True)
        self._t.start()

    def _serve(self):
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except OSError:
                continue
            try:
                with conn:
                    f = conn.makefile("rw", encoding="utf-8")
                    while True:
                        line = f.readline()
                        if not line:
                            break
                        try:
                            resp = self._handler(json.loads(line))
                        except Exception as exc:
                            resp = {"status": "error",
                                    "error": f"{type(exc).__name__}: {exc}"}
                        f.write(json.dumps(resp, ensure_ascii=False) + "\n")
                        f.flush()
            except OSError:
                continue

    def close(self):
        self._stop.set()
        try:
            self._sock.close()
        except OSError:
            # 关闭竞态：socket 可能已被 serve 线程关闭——忽略（收尾阶段）
            pass


class RunScriptTool(Tool):
    reentrant = True  # 内部执行其它工具（同 delegate 语义——不占全局并发槽）

    def __init__(self, ws, cfg):
        self._ws = ws
        self._cfg = cfg
        self._timeout = float(getattr(cfg, "code_mode_timeout_s", 120.0) or 120.0)
        self._max_calls = int(getattr(cfg, "code_mode_max_calls", 64) or 64)
        self._out_max = int(
            getattr(cfg, "code_mode_output_max_chars", 20000) or 20000)
        self._subset = {str(x) for x in (getattr(cfg, "code_mode_tools", ()) or ())}
        self._sandbox_mode = str(getattr(cfg, "sandbox_mode", "native") or "native")
        self._ctx = {}

    def name(self):
        return "run_script"

    def description(self):
        return ("以 Python 脚本批量编排工具调用（Code Mode）：中间结果留在脚本内，"
                "仅 stdout 摘要回传上下文。脚本内可用函数与单元白名单一致（另有"
                "代码模式子集过滤）：read_file(path[,offset,limit])/grep/glob/"
                "read_dependency/write_file/write_artifact/bash(command=...)——"
                "未授权名称调用报错。只 print 结论/摘要；脚本超时会终止；"
                "脚本内写操作计入契约物证（与常规工具调用同源）。")

    def input_schema(self):
        return {"type": "object",
                "properties": {"script": {"type": "string"}},
                "required": ["script"]}

    def permission(self):
        # 能力面由脚本内调用链决定（同 bash：白名单+守卫+超时约束）
        return {"read": True, "write": True, "execute": True,
                "network": True, "destructive": True}

    def set_context(self, *, registry, whitelist, trace=None,
                    unit_id="", domain_id="", on_inner_call=None):
        self._ctx = {"registry": registry,
                     "whitelist": set(whitelist or ()),
                     "trace": trace, "unit_id": unit_id, "domain_id": domain_id,
                     "on_inner_call": on_inner_call}

    def execute(self, script="", **kw):
        from wuxing.protocols import ToolResult
        reg = self._ctx.get("registry")
        if reg is None:
            return ToolResult(status="error", tool_name="run_script",
                              error="run_script: 执行上下文未绑定（需经 runner 调用）")
        if self._sandbox_mode == "container":
            return ToolResult(status="error", tool_name="run_script",
                              error="container: run_script 暂不支持容器档"
                                    "（Phase 1 为 native 沙箱；不静默回退）")
        body = str(script or "")
        if not body.strip():
            return ToolResult(status="error", tool_name="run_script",
                              error="param: script 不能为空")
        allowed = sorted((self._subset & self._ctx.get("whitelist", set()))
                         - _FORBIDDEN)
        code_dir = pathlib.Path(self._ws.root) / ".wuxing" / "code"
        code_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        uid = str(self._ctx.get("unit_id") or "adhoc") or "adhoc"
        script_path = code_dir / f"{stamp}-{uid}.py"
        boot_path = code_dir / f"{stamp}-{uid}-boot.py"
        atomic_write_text(script_path, body)
        atomic_write_text(boot_path, _BOOTSTRAP)

        token = secrets.token_hex(16)
        state = {"calls": 0}
        trace = self._ctx.get("trace")
        unit_id = str(self._ctx.get("unit_id") or "")
        domain_id = str(self._ctx.get("domain_id") or "")

        def _handle(req):
            if str(req.get("token") or "") != token:
                return {"status": "error", "error": "code mode: token mismatch"}
            name = str(req.get("tool") or "")
            if name not in allowed:
                return {"status": "error",
                        "error": f"tool not allowed in code mode: {name}"}
            state["calls"] += 1
            if state["calls"] > self._max_calls:
                return {"status": "error",
                        "error": f"code mode: 调用数超过上限（{self._max_calls}）"}
            args = req.get("args") or {}
            if not isinstance(args, dict):
                return {"status": "error", "error": "args 必须为 JSON 对象"}
            t0 = time.time()
            res = reg.execute(name, **args)
            latency = int((time.time() - t0) * 1000)
            if trace is not None:
                try:
                    trace.log("tool_call", unit_id, domain_id, name=name,
                              status=res.status, latency_ms=latency,
                              via="code_mode")
                except Exception as exc:
                    logger.debug("code_mode 内层 trace 失败（不阻断）：%s", exc)
            # O3/C4：证据回调（写/读/运行——runner 侧统一累计；异常不阻断）
            cb = self._ctx.get("on_inner_call")
            if cb is not None:
                try:
                    cb(name, args, res.status, str(res.content or ""))
                except Exception as exc:
                    logger.debug("code_mode 证据回调失败（不阻断）：%s", exc)
            return {"status": res.status, "content": str(res.content or ""),
                    "error": str(res.error or "")}

        srv = _RpcServer(_handle)
        # 大小写不敏感白名单匹配（Windows：SYSTEMROOT vs SystemRoot——漏则子进程
        # Python 无法取随机数致命失败）：只放行白名单内的环境变量
        _allow = {str(k).upper() for k in _ENV_ALLOW}
        env = {k: v for k, v in os.environ.items()
               if str(k).upper() in _allow}
        env.update({"WUXING_CODE_PORT": str(srv.port),
                    "WUXING_CODE_TOKEN": token,
                    "WUXING_CODE_TOOLS": json.dumps(allowed),
                    "WUXING_CODE_SUBSET": json.dumps(sorted(self._subset)),
                    "PYTHONIOENCODING": "utf-8"})
        timed_out = False
        try:
            proc = subprocess.Popen(
                [sys.executable, "-I", "-X", "utf8",
                 str(boot_path), str(script_path)],
                cwd=str(self._ws.root), env=env,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                out, err = proc.communicate(timeout=self._timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                _kill_tree(proc)
                out, err = proc.communicate()
        finally:
            srv.close()
        stdout = _decode_output(out)
        stderr = _decode_output(err)
        truncated = False
        if len(stdout) > self._out_max:
            full = code_dir / f"{stamp}-{uid}.out"
            note = ""
            try:
                full.write_text(stdout, encoding="utf-8")
                note = f"；全文 {full}"
            except OSError as exc:
                logger.debug("code_mode 全文落盘失败（不阻断）：%s", exc)
            stdout = stdout[: self._out_max] + (
                f"\n…（stdout 超 {self._out_max} 字符已截断{note}）")
            truncated = True
        if trace is not None:
            try:
                trace.log("code_mode_run", unit_id, domain_id,
                          calls=state["calls"], rc=proc.returncode,
                          timeout=timed_out, stdout_chars=len(stdout),
                          truncated=truncated, script=str(script_path),
                          script_chars=len(body))
            except Exception as exc:
                logger.debug("code_mode_run trace 失败（不阻断）：%s", exc)
        if timed_out:
            return ToolResult(status="error", tool_name="run_script",
                              error=f"timeout: 脚本超时（{self._timeout}s）已终止",
                              content=stdout[-2000:])
        if proc.returncode != 0:
            tail = (stderr or stdout)[-2000:]
            return ToolResult(status="error", tool_name="run_script",
                              error=f"退出码 {proc.returncode}：{tail}",
                              content=stdout[-2000:])
        text = stdout
        if stderr.strip():
            text += "\n[stderr]\n" + stderr[-2000:]
        return ToolResult(status="ok", tool_name="run_script",
                          content=text or "（脚本无输出）")
