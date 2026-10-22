"""Установка юнитов при выкладке: cmp, verify, без рестарта синков."""

from __future__ import annotations

import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts" / "install_systemd_units.sh"
DEPLOY = ROOT / "scripts" / "deploy_vps.sh"
VPS = ROOT / "vps"

ALWAYS = (
    "sro-bot.service",
    "sro-max-bot.service",
    "sro-reestr-sync.service",
    "sro-reestr-sync.timer",
    "sro-specialist-sync.service",
    "sro-specialist-sync.timer",
    "sro-sync-alert@.service",
)
IF_PRESENT = (
    "sro-telegram-watchdog.service",
    "sro-telegram-watchdog.timer",
    "sro-site-health.service",
    "sro-site-health.timer",
)


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


def _mocks(tmp_path: Path, *, analyze_rc: int = 0):
    tmp_path.mkdir(parents=True, exist_ok=True)
    log = tmp_path / "cmd.log"
    systemctl = tmp_path / "systemctl"
    analyze = tmp_path / "analyze"
    _write(
        systemctl,
        f"""#!/bin/bash
printf '%s\\n' "$*" >> {log}
case "$1" in
  restart|stop|start|enable|disable) exit 3 ;;
esac
exit 0
""",
    )
    _write(
        analyze,
        f"""#!/bin/bash
printf '%s\\n' "analyze $*" >> {log}
echo "verify-ok" >&2
exit {analyze_rc}
""",
    )
    return log, systemctl, analyze


def _run(tmp_path: Path, source: Path, unit_dir: Path, helper: Path, *, analyze_rc: int = 0):
    log, systemctl, analyze = _mocks(tmp_path, analyze_rc=analyze_rc)
    proc = subprocess.run(
        [
            "bash",
            str(INSTALLER),
            "--source",
            str(source),
            "--unit-dir",
            str(unit_dir),
            "--helper-dir",
            str(helper),
            "--systemctl",
            str(systemctl),
            "--analyze",
            str(analyze),
        ],
        capture_output=True,
        text=True,
    )
    return proc, log.read_text(encoding="utf-8") if log.exists() else ""


def test_installer_lists_live_units_and_not_secrets():
    proc = subprocess.run(
        ["bash", str(INSTALLER), "--list"],
        check=True,
        capture_output=True,
        text=True,
    )
    names = proc.stdout.split()
    for name in ALWAYS + IF_PRESENT + ("sync_failure_alert.sh",):
        assert name in names
    blob = proc.stdout
    assert "config_keys" not in blob
    assert ".env" not in blob
    assert "install.sh" not in blob
    assert "harden_vps.sh" not in blob
    subprocess.run(["bash", "-n", str(INSTALLER)], check=True)
    assert b"\r" not in INSTALLER.read_bytes()


def test_install_is_idempotent_and_does_not_restart_sync(tmp_path: Path):
    unit_dir = tmp_path / "etc"
    helper = tmp_path / "vps"
    unit_dir.mkdir()
    proc, log = _run(tmp_path / "m1", VPS, unit_dir, helper)
    assert proc.returncode == 0, proc.stderr
    for name in ALWAYS:
        dest = unit_dir / name
        assert dest.read_bytes() == (VPS / name).read_bytes()
        assert stat.S_IMODE(dest.stat().st_mode) == 0o644
    script = helper / "sync_failure_alert.sh"
    assert script.read_bytes() == (VPS / "sync_failure_alert.sh").read_bytes()
    assert stat.S_IMODE(script.stat().st_mode) == 0o755
    for name in IF_PRESENT:
        assert not (unit_dir / name).exists()
    assert "daemon-reload" in log
    assert "restart" not in log
    assert "stop " not in log
    assert not (unit_dir / "config_keys.py").exists()

    stamped = (unit_dir / "sro-bot.service").stat().st_mtime_ns
    proc2, log2 = _run(tmp_path / "m2", VPS, unit_dir, helper)
    assert proc2.returncode == 0, proc2.stderr
    assert (unit_dir / "sro-bot.service").stat().st_mtime_ns == stamped
    assert "daemon-reload" not in log2
    assert "без изменений: sro-bot.service" in proc2.stdout


def test_mode_fix_and_existing_optional_unit(tmp_path: Path):
    unit_dir = tmp_path / "etc"
    helper = tmp_path / "vps"
    unit_dir.mkdir()
    proc, _log = _run(tmp_path / "m1", VPS, unit_dir, helper)
    assert proc.returncode == 0, proc.stderr
    bot = unit_dir / "sro-bot.service"
    bot.chmod(0o600)
    (helper / "sync_failure_alert.sh").chmod(0o644)
    watchdog = unit_dir / "sro-telegram-watchdog.service"
    watchdog.write_text("old\n", encoding="utf-8")

    proc2, log2 = _run(tmp_path / "m2", VPS, unit_dir, helper)
    assert proc2.returncode == 0, proc2.stderr
    assert stat.S_IMODE(bot.stat().st_mode) == 0o644
    assert stat.S_IMODE((helper / "sync_failure_alert.sh").stat().st_mode) == 0o755
    assert watchdog.read_bytes() == (VPS / "sro-telegram-watchdog.service").read_bytes()
    assert stat.S_IMODE(watchdog.stat().st_mode) == 0o644
    assert "daemon-reload" in log2
    assert "restart" not in log2


def test_verify_failure_restores_previous_and_removes_new(tmp_path: Path):
    unit_dir = tmp_path / "etc"
    helper = tmp_path / "vps"
    unit_dir.mkdir()
    old = unit_dir / "sro-bot.service"
    old.write_text("OLD-UNIT\n", encoding="utf-8")
    old.chmod(0o644)
    proc, log = _run(tmp_path / "m1", VPS, unit_dir, helper, analyze_rc=1)
    assert proc.returncode != 0
    assert "systemd-analyze verify не прошёл" in proc.stderr
    assert old.read_text(encoding="utf-8") == "OLD-UNIT\n"
    assert not (unit_dir / "sro-sync-alert@.service").exists()
    assert not (helper / "sync_failure_alert.sh").exists()
    assert "daemon-reload" not in log


def test_secret_in_source_is_not_copied(tmp_path: Path):
    source = tmp_path / "src"
    shutil.copytree(VPS, source)
    (source / "config_keys.py").write_text("BOT_TOKEN = 'x'\n", encoding="utf-8")
    (source / ".env").write_text("TOKEN=x\n", encoding="utf-8")
    unit_dir = tmp_path / "etc"
    helper = tmp_path / "vps"
    unit_dir.mkdir()
    proc, _log = _run(tmp_path / "m1", source, unit_dir, helper)
    assert proc.returncode == 0, proc.stderr
    assert not (unit_dir / "config_keys.py").exists()
    assert not (helper / "config_keys.py").exists()
    assert not (helper / ".env").exists()
    assert not any(path.name.startswith(".env") for path in helper.iterdir())


def test_deploy_calls_installer_and_does_not_restart_syncs():
    script = DEPLOY.read_text(encoding="utf-8")
    installer = INSTALLER.read_text(encoding="utf-8")
    assert "install_systemd_units.sh" in script
    assert "systemd-analyze verify" in installer
    assert "cmp -s" in installer
    assert "daemon-reload" in installer
    assert "config_keys.py" in installer
    for name in ("sro-specialist-sync", "sro-reestr-sync"):
        assert f"systemctl restart {name}" not in script
        assert f"systemctl stop {name}" not in script
        assert f"systemctl restart {name}" not in installer
        assert f"systemctl stop {name}" not in installer
    subprocess.run(["bash", "-n", str(DEPLOY)], check=True)
    subprocess.run(["bash", str(DEPLOY), "--self-check"], check=True)


def test_systemd_analyze_unit_files_have_no_syntax_errors():
    analyze = shutil.which("systemd-analyze")
    if analyze is None:
        pytest.skip("нет systemd-analyze")
    units = sorted(VPS.glob("sro-*.service")) + sorted(VPS.glob("sro-*.timer"))
    assert units
    proc = subprocess.run(
        [analyze, "verify", *[str(path) for path in units]],
        capture_output=True,
        text=True,
    )
    unexpected = []
    for line in (proc.stdout + proc.stderr).splitlines():
        text = line.strip()
        if not text:
            continue
        if "Command /opt/sro-bot/venv/bin/python is not executable" in text:
            continue
        unexpected.append(text)
    assert unexpected == []
