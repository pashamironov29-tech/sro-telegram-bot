#!/usr/bin/env python3
"""Quick status: bot / sync / stub."""
import subprocess
import sys

def sh(cmd: str) -> str:
    try:
        return subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.STDOUT).strip()
    except subprocess.CalledProcessError as e:
        return (e.output or "").strip()

print("sro-bot:", sh("systemctl is-active sro-bot"))
sync = sh("pgrep -af 'reestr_sync.py --daily' || true")
print("sync:", sync or "not running")
stub = sh("pgrep -af 'maintenance_stub.py' || true")
print("stub:", stub or "not running")
print("timers:")
print(sh("systemctl list-timers 'sro-*' --no-pager"))
sys.exit(0)
