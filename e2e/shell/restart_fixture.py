"""严格重启 8833 夹具：杀监听 → 等端口空闲 → 启动 → health PID 双证。

用法：
  python e2e/shell/restart_fixture.py            # 零态重启
  python e2e/shell/restart_fixture.py restore    # 带 FAKE_RESTORE（重启恢复双证）
"""
import json
import os
import pathlib
import socket
import subprocess
import sys
import time
import urllib.request

PORT = 8833
HOST = "127.0.0.60"


def _port_free() -> bool:
    s = socket.socket()
    s.settimeout(0.3)
    try:
        s.connect((HOST, PORT))
        s.close()
        return False
    except OSError:
        return True


def _listener_pid() -> str:
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         ("(Get-NetTCPConnection -LocalPort 8833 -State Listen "
           "-ErrorAction SilentlyContinue | Select-Object -First 1 "
           "-ExpandProperty OwningProcess)")],
        capture_output=True, text=True, check=False).stdout.strip()
    return out


pid = _listener_pid()
if pid:
    subprocess.run(["powershell", "-NoProfile", "-Command",
                    f"Stop-Process -Id {pid} -Force"], capture_output=True, check=False)
for _ in range(80):
    if _port_free():
        break
    time.sleep(0.25)
else:
    print("port busy after kill")
    sys.exit(1)

wd = pathlib.Path(__file__).resolve().parents[2]
env = None
if len(sys.argv) > 1 and sys.argv[1] == "restore":
    env = {**os.environ,
           "FAKE_RESTORE": str(pathlib.Path(__file__).resolve().parent / "fake-ws-keep")}
flags = 0x8 | 0x200 if sys.platform == "win32" else 0
proc = subprocess.Popen(
    [sys.executable, "e2e/shell/serve_fake.py", str(PORT)],
    cwd=str(wd), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    env=env, creationflags=flags, close_fds=True)

for _ in range(80):
    try:
        with urllib.request.urlopen(f"http://{HOST}:{PORT}/health", timeout=2) as r:
            d = json.load(r)
        if d.get("pid") == proc.pid:
            print(f"ok pid {proc.pid}")
            sys.exit(0)
    except Exception:
        pass
    time.sleep(0.5)
print(f"FAILED to start {proc.pid}")
sys.exit(1)
