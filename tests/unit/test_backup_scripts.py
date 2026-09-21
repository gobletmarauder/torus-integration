"""Backup and restore shell safety contracts."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[2]
BACKUP = ROOT / "deploy" / "backup" / "backup.sh"
RESTORE = ROOT / "deploy" / "backup" / "restore-test.sh"


def test_backup_scripts_parse_and_clean_tmpfs() -> None:
    git_bash = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git" / "bin" / "bash.exe"
    bash = str(git_bash) if os.name == "nt" else "/bin/bash"
    for script in (BACKUP, RESTORE):
        result = subprocess.run(
            [bash, "-n", str(script)], check=False, capture_output=True, text=True
        )
        assert result.returncode == 0, result.stderr
        source = script.read_text(encoding="utf-8")
        assert "set -euo pipefail" in source
        assert "trap cleanup EXIT INT TERM" in source
        assert "/work/torus-" in source


def test_systemd_host_runs_decrypt_to_tmpfs_and_clean_up() -> None:
    common = (ROOT / "deploy" / "lib" / "torus-common.sh").read_text(encoding="utf-8")
    for script in (BACKUP, RESTORE):
        source = script.read_text(encoding="utf-8")
        assert "--host-run" in source
        assert "trap torus_cleanup_secrets EXIT INT TERM" in source
        assert "torus_decrypt_secrets" in source
        assert "torus_load_current_release" in source
        assert "torus_sanitize_backup_env" in source
        assert "torus_compose --profile backup run --rm torus-backup" in source
    assert 'state="$TORUS_STATE_DIR/torus-current.env"' in common


def test_backup_encrypts_before_guarded_upload_and_heartbeat() -> None:
    source = BACKUP.read_text(encoding="utf-8")
    assert source.index("age --recipient") < source.index("python -m tis.backup upload")
    assert source.index("python -m tis.backup upload") < source.index("heartbeat")
    assert "--format=custom" in source
    assert "--schema=public" in source


def test_restore_runs_local_postgres_without_docker_socket() -> None:
    source = RESTORE.read_text(encoding="utf-8")
    assert "initdb" in source
    assert "pg_restore --exit-on-error" in source
    assert "count(*)" in source
    assert "docker" not in source
    assert "tis-restore-test" in source
