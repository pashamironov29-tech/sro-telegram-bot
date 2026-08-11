#!/usr/bin/env python3
"""While reestr_sync.py runs: hold token with maintenance_stub; then restore sro-bot."""
from __future__ import annotations

import os
import signal
import subprocess
import time

APP = "/opt/sro-bot"
PY = f"{APP}/venv/bin/python"
STUB = f"{APP}/maintenance_stub.py"
PID_FILE = f"{APP}/maintenance_stub.pid"
LOG = f"{APP}/logs/maintenance_handoff.log"


def log(msg: str) -> None:
    os.makedirs(f"{APP}/logs", exist_ok=True)
    line = time.strftime("%Y-%m-%d %H:%M:%S") + " " + msg
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def pgrep(pattern: str) -> list[int]:
    try:
        out = subprocess.check_output(["pgrep", "-f", pattern], text=True)
    except subprocess.CalledProcessError:
        return []
    pids = [int(x) for x in out.split() if x.strip().isdigit()]
    # не считаем сам handoff / shell
    me = os.getpid()
    return [p for p in pids if p != me]


def stub_pids() -> list[int]:
    # точный путь скрипта, без совпадений с handoff.py в командной строке
    return pgrep(f"{PY} -u {STUB}") or pgrep(f"{STUB}")


def sync_pids() -> list[int]:
    return pgrep(f"{PY} -u {APP}/reestr_sync.py --daily") or pgrep(
        "reestr_sync.py --daily"
    )


def start_stub() -> None:
    if stub_pids():
        log(f"stub already running pids={stub_pids()}")
        return
    subprocess.call(["systemctl", "stop", "sro-bot"])
    time.sleep(2)
    proc = subprocess.Popen(
        [PY, "-u", STUB],
        cwd=APP,
        stdout=open(f"{APP}/logs/maintenance_stub_handoff.log", "a"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    with open(PID_FILE, "w", encoding="utf-8") as f:
        f.write(str(proc.pid))
    time.sleep(2)
    if proc.poll() is not None:
        log(f"stub exited early code={proc.returncode}")
        return
    log(f"started stub pid={proc.pid}")


def stop_stub() -> None:
    pids = stub_pids()
    if os.path.isfile(PID_FILE):
        try:
            pids.append(int(open(PID_FILE, encoding="utf-8").read().strip()))
        except Exception:
            pass
    for pid in sorted(set(pids)):
        log(f"stopping stub pid={pid}")
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    time.sleep(2)
    for pid in stub_pids():
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if os.path.isfile(PID_FILE):
        os.remove(PID_FILE)


def main() -> int:
    running = sync_pids()
    if not running:
        log("no sync running — start bot only")
        stop_stub()
        subprocess.call(["systemctl", "start", "sro-bot"])
        return 0

    log(f"sync running pids={running}; enabling maintenance stub")
    start_stub()

    while sync_pids():
        time.sleep(20)

    log("sync finished — restore main bot")
    stop_stub()
    time.sleep(2)
    subprocess.call(["systemctl", "start", "sro-bot"])
    time.sleep(3)
    active = subprocess.call(["systemctl", "is-active", "--quiet", "sro-bot"]) == 0
    log(f"sro-bot active={active}")
    return 0 if active else 1


if __name__ == "__main__":
    raise SystemExit(main())
