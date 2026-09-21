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
  torus_compose --profile backup run --rm torus-backup \
    /app/deploy/backup/restore-test.sh
  exit 0
fi
[[ "$#" -eq 0 ]] || { printf 'torus-restore-test: unexpected argument\n' >&2; exit 2; }

work=/work/torus-restore-test
encrypted="$work/latest.dump.gz.age"
compressed="$work/latest.dump.gz"
archive="$work/latest.dump"
key_file="$work/restore-test.key"
data_dir="$work/postgres"
socket_dir="$work/socket"
run_id="restore-$(date -u +%G-W%V)"

cleanup() {
  if [[ -f "$data_dir/postmaster.pid" ]]; then
    pg_ctl -D "$data_dir" -m immediate stop >/dev/null 2>&1 || true
  fi
  rm -rf -- "$work"
}
trap cleanup EXIT INT TERM
mkdir -p "$work" "$socket_dir"

if [[ "${DRY_RUN:-true}" == "true" ]]; then
  python -m tis.backup download --path "$encrypted"
  python -m tis.backup heartbeat --monitor tis-restore-test --run-id "$run_id"
  printf 'torus-restore-test: dry run skipped remote reads and writes\n'
  exit 0
fi
[[ -n "${RESTORE_TEST_AGE_PRIVATE_KEY:-}" ]] || {
  printf 'torus-restore-test: restore key is missing\n' >&2
  exit 1
}
printf '%s\n' "$RESTORE_TEST_AGE_PRIVATE_KEY" >"$key_file"
chmod 0600 "$key_file"
python -m tis.backup download --path "$encrypted"
age --decrypt --identity "$key_file" --output "$compressed" "$encrypted"
gzip --decompress "$compressed"

initdb --auth=trust --encoding=UTF8 --no-locale -D "$data_dir" >/dev/null
pg_ctl -D "$data_dir" -o "-c listen_addresses='' -k $socket_dir" -w start >/dev/null
createdb -h "$socket_dir" torus_restore
pg_restore --exit-on-error --no-owner --no-privileges -h "$socket_dir" \
  --dbname torus_restore "$archive"
for table in leads integration_log integration_state; do
  psql -h "$socket_dir" -d torus_restore -v ON_ERROR_STOP=1 -Atc \
    "select count(*) from public.$table" >/dev/null
done
pg_ctl -D "$data_dir" -m fast -w stop >/dev/null
python -m tis.backup heartbeat --monitor tis-restore-test --run-id "$run_id"
printf 'torus-restore-test: completed aggregate sanity checks\n'
