"""Shared-host bootstrap safety contracts."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[2]
BOOTSTRAP = ROOT / "deploy" / "host" / "bootstrap.sh"


def bash() -> str:
    git_bash = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git" / "bin" / "bash.exe"
    return str(git_bash) if os.name == "nt" else "/bin/bash"


def test_bootstrap_requires_confirm_before_any_action() -> None:
    result = subprocess.run([bash(), str(BOOTSTRAP)], check=False, capture_output=True, text=True)
    assert result.returncode == 2
    assert "Usage:" in result.stderr


def test_bootstrap_test_mode_is_repeatable_and_additive(tmp_path: Path) -> None:
    environment = {
        **os.environ,
        "TORUS_TEST_MODE": "1",
        "TORUS_TEST_ROOT": str(tmp_path),
    }
    first = subprocess.run(
        [bash(), str(BOOTSTRAP), "--confirm"],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    second = subprocess.run(
        [bash(), str(BOOTSTRAP), "--confirm"],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert first.returncode == second.returncode == 0
    assert "no inbound-network or remote-login configuration was changed" in second.stdout


def test_bootstrap_contains_no_shared_host_destructive_assumptions() -> None:
    source = BOOTSTRAP.read_text(encoding="utf-8")
    lowered = source.lower()
    assert "/var/lib/docker" not in source
    assert "sudo docker" not in lowered
    assert "scalprix" not in lowered
    assert "curl" in source and "curl |" not in source and "curl|" not in source
    assert "systemctl restart docker" not in lowered
    assert "useradd" in source and "usermod" not in source
    assert '-o root -g rehaanmerchant -m 0750 "$ROOT/etc/torus/age"' in source
    assert 'engine_version" == "28.2.2"' in source
    assert 'compose_version" == "2.40.3"' in source
    for forbidden in ("ufw", "sshd_config", "passwordauthentication", "permitrootlogin"):
        assert forbidden not in lowered
