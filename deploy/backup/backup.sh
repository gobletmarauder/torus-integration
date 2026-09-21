#!/usr/bin/env bash
set -euo pipefail
umask 077

if [[ "${1:-}" == "--host-run" ]]; then
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  # shellcheck source=deploy/lib/torus-common.sh
  source "$script_dir/../lib/torus-common.sh"
  torus_require_deploy_user
  trap torus_cleanup_secrets EXIT INT TERM
  torus_decrypt_secrets
  torus_load_current_release
  torus_sanitize_backup_env
  torus_compose --profile backup run --rm torus-backup /app/deploy/backup/backup.sh
  exit 0
fi
[[ "$#" -eq 0 ]] || { printf 'torus-backup: unexpected argument\n' >&2; exit 2; }

work=/work/torus-backup
run_date="${TORUS_BACKUP_DATE:-$(date -u +%F)}"
[[ "$run_date" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || {
  printf 'torus-backup: invalid UTC date\n' >&2
  exit 1
}
run_id="backup-$run_date"
archive="$work/torus-backup-$run_date.dump"
compressed="$archive.gz"
encrypted="$compressed.age"
object="torus-backup-$run_date.dump.gz.age"

cleanup() {
  rm -rf -- "$work"
}
trap cleanup EXIT INT TERM
mkdir -p "$work"

[[ -n "${BACKUP_DATABASE_DSN:-}" ]] || { printf 'torus-backup: missing database setting\n' >&2; exit 1; }
[[ -n "${BACKUP_AGE_RECIPIENT:-}" && -n "${RECOVERY_AGE_RECIPIENT:-}" ]] || {
  printf 'torus-backup: two age recipients are required\n' >&2
  exit 1
}

client_major="$(pg_dump --version | sed -E 's/.* ([0-9]+).*/\1/')"
server_major="$(PGDATABASE="$BACKUP_DATABASE_DSN" psql -Atc "show server_version_num" | cut -c1-2)"
(( client_major >= server_major )) || { printf 'torus-backup: pg_dump client is too old\n' >&2; exit 1; }

PGDATABASE="$BACKUP_DATABASE_DSN" pg_dump --format=custom --schema=public --file="$archive"
gzip --no-name "$archive"
age --recipient "$BACKUP_AGE_RECIPIENT" --recipient "$RECOVERY_AGE_RECIPIENT" \
  --output "$encrypted" "$compressed"
rm -f -- "$compressed"

python -m tis.backup upload --path "$encrypted" --object "$object" --date "$run_date"
python -m tis.backup prune --date "$run_date"
python -m tis.backup heartbeat --monitor tis-backup --run-id "$run_id"
printf 'torus-backup: completed %s\n' "$run_date"
