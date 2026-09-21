#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=deploy/lib/torus-common.sh
source "$script_dir/lib/torus-common.sh"

tag="${1:-}"
mode="${2:---dry-run}"
reload="${3:-}"
[[ "$tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || torus_fail "tag must be vMAJOR.MINOR.PATCH"
[[ "$mode" == "--dry-run" || "$mode" == "--live" ]] || torus_fail "choose --dry-run or --live"
[[ -z "$reload" || "$reload" == "--reload-secrets" ]] || torus_fail "unexpected argument"
torus_require_deploy_user

install -d -m 2770 "$TORUS_STATE_DIR"
exec 9>"$TORUS_STATE_DIR/torus-deploy.lock"
flock -n 9 || torus_fail "another Torus deploy is running"
trap torus_cleanup_secrets EXIT INT TERM

[[ -z "$(git -C "$TORUS_APP_DIR" status --porcelain)" ]] || torus_fail "application checkout is dirty"
torus_log "fetching reviewed tag"
git -C "$TORUS_APP_DIR" fetch --tags origin
git -C "$TORUS_APP_DIR" checkout --detach "$tag"

torus_decrypt_secrets
if [[ "$mode" == "--dry-run" ]]; then
  torus_set_dry_run true
else
  torus_set_dry_run false
fi

release_token="$(torus_read_env "$TORUS_RUN_DIR/torus-backup.env" GITHUB_RELEASE_TOKEN)"
repository="$(torus_read_env "$TORUS_RUN_DIR/torus-backup.env" GITHUB_REPOSITORY)"
owner="$(torus_read_env "$TORUS_RUN_DIR/torus-backup.env" GHCR_OWNER)"
[[ "$repository" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || torus_fail "invalid repository setting"
[[ "$owner" =~ ^[a-z0-9_.-]+$ ]] || torus_fail "invalid GHCR owner"
[[ "$release_token" =~ ^[A-Za-z0-9_]+$ ]] || torus_fail "invalid release token format"

release_json="$(mktemp "$TORUS_RUN_DIR/torus-release.XXXXXX.json")"
manifest_file="$(mktemp "$TORUS_RUN_DIR/torus-release.XXXXXX.env")"
auth_config="$(mktemp "$TORUS_RUN_DIR/torus-release.XXXXXX.curl")"
printf 'header = "Authorization: Bearer %s"\n' "$release_token" >"$auth_config"
chmod 0600 "$auth_config"
curl --proto '=https' --tlsv1.2 --fail --location --silent --show-error \
  --config "$auth_config" \
  --header 'Accept: application/vnd.github+json' \
  "https://api.github.com/repos/$repository/releases/tags/$tag" --output "$release_json"
asset_url="$(jq -er '.assets[] | select(.name == "torus-release-digests.env") | .url' "$release_json")"
curl --proto '=https' --tlsv1.2 --fail --location --silent --show-error \
  --config "$auth_config" \
  --header 'Accept: application/octet-stream' "$asset_url" --output "$manifest_file"
rm -f -- "$release_json"
torus_load_manifest "$manifest_file"
rm -f -- "$manifest_file"
rm -f -- "$auth_config"

[[ "$(git -C "$TORUS_APP_DIR" rev-parse HEAD)" == "$SOURCE_SHA" ]] || \
  torus_fail "release source does not match checked-out tag"
[[ "$(torus_resolve_digest "ghcr.io/$owner/tis:$tag")" == "$TIS_DIGEST" ]] || \
  torus_fail "tis registry digest does not match release manifest"
[[ "$(torus_resolve_digest "ghcr.io/$owner/tis-backup:$tag")" == "$BACKUP_DIGEST" ]] || \
  torus_fail "backup registry digest does not match release manifest"

GHCR_OWNER="$owner"
CLOUDFLARED_DIGEST="$(torus_read_env "$TORUS_RUN_DIR/torus-backup.env" CLOUDFLARED_DIGEST)"
torus_validate_digest "$CLOUDFLARED_DIGEST"
export GHCR_OWNER CLOUDFLARED_DIGEST
torus_sanitize_backup_env

previous="$TORUS_STATE_DIR/torus-current.env"
if [[ -f "$previous" ]]; then
  cp -- "$previous" "$TORUS_STATE_DIR/torus-previous.env"
fi
temporary_state="$(mktemp "$TORUS_STATE_DIR/torus-current.XXXXXX")"
printf 'TAG=%s\nTIS_DIGEST=%s\nBACKUP_DIGEST=%s\nCLOUDFLARED_DIGEST=%s\n' \
  "$tag" "$TIS_DIGEST" "$BACKUP_DIGEST" "$CLOUDFLARED_DIGEST" >"$temporary_state"

torus_log "pulling immutable image digests"
torus_compose --profile backup pull
torus_compose up -d --remove-orphans
if ! "$TORUS_APP_DIR/deploy/smoke.sh"; then
  torus_log "smoke failed; starting automatic rollback"
  "$TORUS_APP_DIR/deploy/rollback.sh" --automatic
  torus_fail "deploy failed and rollback was attempted"
fi
mv -f -- "$temporary_state" "$TORUS_STATE_DIR/torus-current.env"
printf '%s tag=%s dry_run=%s result=ok\n' "$(date -u +%FT%TZ)" "$tag" \
  "$([[ "$mode" == "--dry-run" ]] && printf true || printf false)" \
  >>"$TORUS_STATE_DIR/torus-deploys.log"
torus_log "deploy complete: tag=$tag"
