"""Digest deploy, smoke, and rollback static/parse contracts."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[2]
SCRIPTS = [
    ROOT / "deploy" / "lib" / "torus-common.sh",
    ROOT / "deploy" / "deploy.sh",
    ROOT / "deploy" / "rollback.sh",
    ROOT / "deploy" / "smoke.sh",
]


def bash() -> str:
    git_bash = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git" / "bin" / "bash.exe"
    return str(git_bash) if os.name == "nt" else "/bin/bash"


def test_deploy_shell_parses_and_uses_only_torus_resources() -> None:
    for script in SCRIPTS:
        result = subprocess.run(
            [bash(), "-n", str(script)], check=False, capture_output=True, text=True
        )
        assert result.returncode == 0, result.stderr
        source = script.read_text(encoding="utf-8").lower()
        assert "sudo docker" not in source
        assert "/var/lib/docker" not in source
        assert "scalprix" not in source


def test_deploy_is_digest_verified_tmpfs_only_and_auto_rolls_back() -> None:
    deploy = (ROOT / "deploy" / "deploy.sh").read_text(encoding="utf-8")
    common = (ROOT / "deploy" / "lib" / "torus-common.sh").read_text(encoding="utf-8")
    assert "torus_resolve_digest" in deploy
    assert '== "$TIS_DIGEST"' in deploy
    assert '== "$BACKUP_DIGEST"' in deploy
    assert "torus_require_tmpfs" in common
    assert "chmod 0600" in common
    assert "torus_sanitize_backup_env" in deploy
    assert '$1 != "GITHUB_RELEASE_TOKEN"' in common
    assert "trap torus_cleanup_secrets" in deploy
    assert 'rollback.sh" --automatic' in deploy
    assert "set -euo pipefail" in deploy


def test_smoke_has_bounded_health_log_and_scheduler_checks() -> None:
    smoke = (ROOT / "deploy" / "smoke.sh").read_text(encoding="utf-8")
    assert "SECONDS + 90" in smoke
    assert "job_completed" in smoke
    assert "tis.healthcheck api" in smoke
    assert "cloudflared tunnel" in smoke
    assert "grep -q 'ERROR'" in smoke


def test_planted_smoke_failure_restores_prior_release(tmp_path: Path) -> None:
    app = tmp_path / "app"
    deploy_dir = app / "deploy"
    lib_dir = deploy_dir / "lib"
    state = tmp_path / "state"
    run = tmp_path / "run"
    lib_dir.mkdir(parents=True)
    state.mkdir()
    run.mkdir()
    shutil.copy2(ROOT / "deploy" / "deploy.sh", deploy_dir / "deploy.sh")
    shutil.copy2(ROOT / "deploy" / "rollback.sh", deploy_dir / "rollback.sh")
    old_digest = "sha256:" + "1" * 64
    new_digest = "sha256:" + "2" * 64
    (state / "torus-current.env").write_text(
        "\n".join(
            (
                "TAG=v1.0.0",
                f"TIS_DIGEST={old_digest}",
                f"BACKUP_DIGEST={old_digest}",
                f"CLOUDFLARED_DIGEST={old_digest}",
                "",
            )
        ),
        encoding="utf-8",
    )
    (deploy_dir / "smoke.sh").write_text(
        "#!/usr/bin/env bash\n"
        'source "$(dirname "${BASH_SOURCE[0]}")/lib/torus-common.sh"\n'
        'count_file="$TORUS_STATE_DIR/smoke-count"\n'
        'count="$(cat "$count_file" 2>/dev/null || printf 0)"\n'
        'count=$((count + 1)); printf "%s" "$count" > "$count_file"\n'
        '[[ "$count" -gt 1 ]]\n',
        encoding="utf-8",
    )
    for executable in (
        deploy_dir / "deploy.sh",
        deploy_dir / "rollback.sh",
        deploy_dir / "smoke.sh",
    ):
        executable.chmod(0o755)
    stub = f'''#!/usr/bin/env bash
TORUS_APP_DIR="{app.as_posix()}"
TORUS_STATE_DIR="{state.as_posix()}"
TORUS_RUN_DIR="{run.as_posix()}"
torus_log() {{ printf 'torus: %s\\n' "$1"; }}
torus_fail() {{ printf 'torus: ERROR: %s\\n' "$1" >&2; exit 1; }}
torus_require_deploy_user() {{ :; }}
torus_cleanup_secrets() {{ rm -f "$TORUS_RUN_DIR"/torus-*.env; }}
torus_decrypt_secrets() {{
  printf 'DRY_RUN=true\\n' > "$TORUS_RUN_DIR/torus-tis.env"
  printf 'TUNNEL_TOKEN=fixture\\n' > "$TORUS_RUN_DIR/torus-cloudflared.env"
  printf 'GITHUB_RELEASE_TOKEN=fixture\\nGITHUB_REPOSITORY=owner/repo\\n' \
    > "$TORUS_RUN_DIR/torus-backup.env"
  printf 'GHCR_OWNER=owner\\nCLOUDFLARED_DIGEST={new_digest}\\n' \
    >> "$TORUS_RUN_DIR/torus-backup.env"
}}
torus_set_dry_run() {{ :; }}
torus_read_env() {{ awk -F= -v wanted="$2" '$1 == wanted {{sub(/^[^=]*=/, ""); print}}' "$1"; }}
torus_load_manifest() {{
  TIS_DIGEST={new_digest}; BACKUP_DIGEST={new_digest}; SOURCE_SHA={"a" * 40}
  export TIS_DIGEST BACKUP_DIGEST SOURCE_SHA
}}
torus_resolve_digest() {{ printf '%s' '{new_digest}'; }}
torus_validate_digest() {{ [[ "$1" =~ ^sha256:[0-9a-f]{{64}}$ ]]; }}
torus_sanitize_backup_env() {{ :; }}
torus_compose() {{ printf 'compose %s\\n' "$*" >> "$TORUS_STATE_DIR/commands"; }}
install() {{ mkdir -p "${{@: -1}}"; }}
flock() {{ return 0; }}
git() {{
  case "$*" in
    *'status --porcelain') return 0 ;;
    *'rev-parse HEAD') printf '%s\\n' '{"a" * 40}' ;;
    *) return 0 ;;
  esac
}}
curl() {{
  local previous='' output=''
  for argument in "$@"; do
    [[ "$previous" == '--output' ]] && output="$argument"
    previous="$argument"
  done
  if [[ "$output" == *.json ]]; then
    printf '{{}}\\n' > "$output"
  else
    printf 'fixture\\n' > "$output"
  fi
}}
jq() {{ printf 'fixture-asset\\n'; }}
'''
    (lib_dir / "torus-common.sh").write_text(stub, encoding="utf-8")

    result = subprocess.run(
        [bash(), str(deploy_dir / "deploy.sh"), "v2.0.0", "--dry-run"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "automatic rollback" in result.stdout
    assert (state / "smoke-count").read_text(encoding="utf-8") == "2"
    current = (state / "torus-current.env").read_text(encoding="utf-8")
    assert "TAG=v1.0.0" in current
    assert f"TIS_DIGEST={old_digest}" in current
    assert f"BACKUP_DIGEST={old_digest}" in current
    commands = (state / "commands").read_text(encoding="utf-8")
    assert "--project-name" not in commands
    assert "compose --profile backup pull" in commands
    assert not any(run.glob("torus-*.env"))
    assert "fixture" not in result.stdout + result.stderr
