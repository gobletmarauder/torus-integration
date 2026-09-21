#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=deploy/lib/torus-common.sh
source "$script_dir/lib/torus-common.sh"

torus_require_deploy_user
if [[ "${1:-}" != "--automatic" ]]; then
  install -d -m 2770 "$TORUS_STATE_DIR"
  exec 9>"$TORUS_STATE_DIR/torus-deploy.lock"
  flock -n 9 || torus_fail "another Torus deploy is running"
fi
state="$TORUS_STATE_DIR/torus-previous.env"
[[ -f "$state" ]] || torus_fail "no previous Torus deployment is recorded"
if [[ ! -f "$TORUS_RUN_DIR/torus-tis.env" ]]; then
  trap torus_cleanup_secrets EXIT INT TERM
  torus_decrypt_secrets
fi

TAG="$(torus_read_env "$state" TAG)"
[[ "$TAG" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || torus_fail "invalid previous tag"
TIS_DIGEST="$(torus_read_env "$state" TIS_DIGEST)"
BACKUP_DIGEST="$(torus_read_env "$state" BACKUP_DIGEST)"
CLOUDFLARED_DIGEST="$(torus_read_env "$state" CLOUDFLARED_DIGEST)"
GHCR_OWNER="$(torus_read_env "$TORUS_RUN_DIR/torus-backup.env" GHCR_OWNER)"
torus_validate_digest "$TIS_DIGEST"
torus_validate_digest "$BACKUP_DIGEST"
torus_validate_digest "$CLOUDFLARED_DIGEST"
export TIS_DIGEST BACKUP_DIGEST CLOUDFLARED_DIGEST GHCR_OWNER
torus_sanitize_backup_env

git -C "$TORUS_APP_DIR" checkout --detach "$TAG"
torus_compose --profile backup pull
torus_compose up -d --remove-orphans
"$TORUS_APP_DIR/deploy/smoke.sh"
cp -- "$state" "$TORUS_STATE_DIR/torus-current.env"
printf '%s tag=%s result=rollback-ok\n' "$(date -u +%FT%TZ)" "$TAG" \
  >>"$TORUS_STATE_DIR/torus-deploys.log"
torus_log "rollback complete: tag=$TAG"
