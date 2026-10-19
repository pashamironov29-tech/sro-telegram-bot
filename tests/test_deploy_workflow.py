"""Текст workflow выкладки и синтаксис scripts/deploy_vps.sh."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "deploy.yml"
SCRIPT = ROOT / "scripts" / "deploy_vps.sh"

_IPV4 = re.compile(
    r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b"
)


def _exclude_names_from_workflow(text: str) -> list[str]:
    lines = text.splitlines()
    start = None
    for index, line in enumerate(lines):
        if line.strip() == "DEPLOY_RSYNC_EXCLUDES: |":
            start = index + 1
            break
    assert start is not None, "в deploy.yml нет списка исключений"
    names = []
    for line in lines[start:]:
        if not line.startswith("            "):
            break
        item = line.strip()
        if item:
            names.append(item)
    assert names, "пустой список исключений"
    return names


def _exclude_names_from_script(text: str) -> list[str]:
    match = re.search(r"EXCLUDES=\(\n(?P<body>.*?)\n\)", text, re.S)
    assert match, "в скрипте нет списка исключений"
    names = []
    for line in match.group("body").splitlines():
        item = line.strip().rstrip(",")
        assert item.startswith("'") and item.endswith("'"), item
        names.append(item[1:-1])
    return names


def test_deploy_workflow_text():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "needs: test" in text
    assert "workflow_dispatch" in text
    assert "master" in text
    assert "environment: production" in text
    assert text.count("environment: production") == 1
    assert "contents: read" in text
    assert "deploy-vps" in text
    assert "cancel-in-progress: false" in text
    assert "config_keys.py" in text
    assert "vps/" in text
    assert "--delete" not in text
    assert "BEGIN OPENSSH PRIVATE KEY" not in text
    assert "BEGIN RSA PRIVATE KEY" not in text
    assert _IPV4.search(text) is None
    assert not re.search(r"sk-[A-Za-z0-9]{20,}", text)


def test_deploy_script_matches_workflow_excludes():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    script = SCRIPT.read_text(encoding="utf-8")
    assert _exclude_names_from_workflow(workflow) == _exclude_names_from_script(script)
    assert "config_keys.py" in script
    assert "vps/" in script
    assert "-rlptz" in script
    assert "--checksum" in script
    assert "--backup" in script
    assert "StrictHostKeyChecking=yes" in script
    assert "pip не откатывался" in script
    assert "NRestarts" in script
    assert script.count("systemctl restart sro-bot sro-max-bot") == 2
    assert "-m pip install -r" in script
    assert "pip install -U" not in script
    assert "--delete" not in script
    assert "BEGIN OPENSSH PRIVATE KEY" not in script
    assert _IPV4.search(script) is None
    assert b"\r" not in SCRIPT.read_bytes()
    assert b"\r" not in WORKFLOW.read_bytes()


def test_deploy_script_bash_syntax():
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash нет")
    subprocess.run([bash, "-n", str(SCRIPT)], check=True)
    subprocess.run([bash, str(SCRIPT), "--self-check"], check=True)
