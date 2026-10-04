#!/usr/bin/env python3
"""Start/restart the development servers with all runtime files inside this repo."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = ROOT / ".cache" / "development"
STATE_FILE = STATE_DIR / "servers.json"
FRONTEND_PORT = 8888
BACKEND_PORT = 8889


def managed_process(pid, marker):
    result = subprocess.run(["ps", "-p", str(pid), "-o", "args="], capture_output=True, text=True)
    return result.returncode == 0 and marker in result.stdout


def stop():
    if not STATE_FILE.exists():
        return
    state = json.loads(STATE_FILE.read_text())
    active = []
    for item in state.values():
        pid = item["pid"]
        if managed_process(pid, item["marker"]):
            os.killpg(pid, signal.SIGTERM)
            active.append(item)
    deadline = time.monotonic() + 8
    while active and time.monotonic() < deadline:
        active = [item for item in active if managed_process(item["pid"], item["marker"])]
        time.sleep(0.1)
    for item in active:
        if managed_process(item["pid"], item["marker"]):
            os.killpg(item["pid"], signal.SIGKILL)
    STATE_FILE.unlink(missing_ok=True)


def wait_ready(url, process, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Server exited; see logs in {STATE_DIR}")
        try:
            with urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except OSError:
            pass
        time.sleep(0.2)
    raise RuntimeError(f"Server not ready at {url}; see logs in {STATE_DIR}")


def start():
    if STATE_FILE.exists():
        state = json.loads(STATE_FILE.read_text())
        if any(managed_process(item["pid"], item["marker"]) for item in state.values()):
            raise RuntimeError("Development server already running; use restart")
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    (STATE_DIR / "tmp").mkdir(exist_ok=True)
    env = dict(os.environ, ENV="development", TMPDIR=str(STATE_DIR / "tmp"),
               FAMLEDGER_BACKEND_URL=f"http://127.0.0.1:{BACKEND_PORT}")
    commands = {
        "backend": ([str(ROOT / ".venv/bin/python"), "-m", "uvicorn", "main:app", "--host", "0.0.0.0",
                     "--port", str(BACKEND_PORT), "--reload", "--reload-dir", str(ROOT / "backend")], ROOT / "backend"),
        "frontend": (["node", str(ROOT / "frontend/node_modules/vite/bin/vite.js"), "--host", "0.0.0.0",
                      "--port", str(FRONTEND_PORT), "--strictPort"], ROOT / "frontend"),
    }
    state = {}
    processes = {}
    try:
        for name, (command, cwd) in commands.items():
            with (STATE_DIR / f"{name}.log").open("a") as log:
                process = subprocess.Popen(command, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT,
                                           stdin=subprocess.DEVNULL, start_new_session=True)
            processes[name] = process
            state[name] = {"pid": process.pid, "marker": " ".join(command) if name == "backend" else command[1]}
            STATE_FILE.write_text(json.dumps(state, indent=2))
        wait_ready(f"http://127.0.0.1:{BACKEND_PORT}/api/health", processes["backend"])
        wait_ready(f"http://127.0.0.1:{FRONTEND_PORT}/", processes["frontend"])
        wait_ready(f"http://127.0.0.1:{FRONTEND_PORT}/api/health", processes["frontend"])
    except BaseException:
        stop()
        raise
    print(f"Frontend with HMR: http://localhost:{FRONTEND_PORT}")
    print(f"Backend with reload: http://localhost:{BACKEND_PORT}")
    print(f"Logs: {STATE_DIR}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["start", "restart", "stop"], nargs="?", default="start")
    action = parser.parse_args().action
    if action in {"restart", "stop"}:
        stop()
    if action != "stop":
        start()


if __name__ == "__main__":
    main()
