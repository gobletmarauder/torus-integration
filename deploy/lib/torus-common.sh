#!/usr/bin/env bash
set -euo pipefail

TORUS_APP_DIR="${TORUS_APP_DIR:-/opt/torus/app}"
TORUS_STATE_DIR="${TORUS_STATE_DIR:-/opt/torus/state}"
TORUS_RUN_DIR="${TORUS_RUN_DIR:-/run/torus}"
TORUS_AGE_KEY_FILE="${TORUS_AGE_KEY_FILE:-/etc/torus/age/tis.key}"
TORUS_COMPOSE=(docker compose --project-name torus --file "$TORUS_APP_DIR/deploy/compose.yaml")

torus_log() {
  printf 'torus: %s\n' "$1"
}

torus_fail() {
  printf 'torus: ERROR: %s\n' "$1" >&2
  exit 1
}

torus_require_deploy_user() {
  [[ "$(id -un)" == "rehaanmerchant" ]] || torus_fail "run as rehaanmerchant"
  docker info >/dev/null 2>&1 || torus_fail "Docker is unavailable to rehaanmerchant"
}

torus_require_tmpfs() {
  [[ "$(findmnt -n -o FSTYPE -T "$TORUS_RUN_DIR")" == "tmpfs" ]] || \
    torus_fail "/run/torus must reside on tmpfs"
}

torus_read_env() {
  local file="$1" key="$2" value
  value="$(awk -F= -v wanted="$key" '$1 == wanted {sub(/^[^=]*=/, ""); print; found=1} END {if (!found) exit 1}' "$file")" || \
    torus_fail "required encrypted setting is missing"
  [[ "$value" != *$'\n'* && "$value" != *$'\r'* ]] || torus_fail "invalid single-line setting"
  printf '%s' "$value"
}

torus_validate_digest() {
  [[ "$1" =~ ^sha256:[0-9a-f]{64}$ ]] || torus_fail "invalid image digest"
}

torus_cleanup_secrets() {
  rm -f -- "$TORUS_RUN_DIR/torus-tis.env" \
    "$TORUS_RUN_DIR/torus-cloudflared.env" "$TORUS_RUN_DIR/torus-backup.env"
  rm -f -- "$TORUS_RUN_DIR"/torus-release.*
}

torus_decrypt_secrets() {
  install -d -m 0700 "$TORUS_RUN_DIR"
  torus_require_tmpfs
  umask 077
  SOPS_AGE_KEY_FILE="$TORUS_AGE_KEY_FILE" sops --decrypt \
    --output "$TORUS_RUN_DIR/torus-tis.env" "$TORUS_APP_DIR/secrets/tis.enc.env"
  SOPS_AGE_KEY_FILE="$TORUS_AGE_KEY_FILE" sops --decrypt \
    --output "$TORUS_RUN_DIR/torus-cloudflared.env" \
    "$TORUS_APP_DIR/secrets/cloudflared.enc.env"
  SOPS_AGE_KEY_FILE="$TORUS_AGE_KEY_FILE" sops --decrypt \
    --output "$TORUS_RUN_DIR/torus-backup.env" "$TORUS_APP_DIR/secrets/backup.enc.env"
  chmod 0600 "$TORUS_RUN_DIR"/torus-*.env
}

torus_set_dry_run() {
  local enabled="$1" source="$TORUS_RUN_DIR/torus-tis.env" temporary
  temporary="$(mktemp "$TORUS_RUN_DIR/torus-tis.env.XXXXXX")"
  awk -v replacement="DRY_RUN=$enabled" '
    BEGIN {done=0}
    /^DRY_RUN=/ {print replacement; done=1; next}
    {print}
    END {if (!done) print replacement}
  ' "$source" >"$temporary"
  chmod 0600 "$temporary"
  mv -f -- "$temporary" "$source"
}

torus_sanitize_backup_env() {
  local source="$TORUS_RUN_DIR/torus-backup.env" temporary
  temporary="$(mktemp "$TORUS_RUN_DIR/torus-backup.env.XXXXXX")"
  awk -F= '$1 != "GITHUB_RELEASE_TOKEN" && $1 != "GITHUB_REPOSITORY" &&
    $1 != "GHCR_OWNER" && $1 != "CLOUDFLARED_DIGEST" {print}' "$source" >"$temporary"
  chmod 0600 "$temporary"
  mv -f -- "$temporary" "$source"
}

torus_load_current_release() {
  local state="$TORUS_STATE_DIR/torus-current.env"
  [[ -f "$state" ]] || torus_fail "no current Torus deployment is recorded"
  TAG="$(torus_read_env "$state" TAG)"
  TIS_DIGEST="$(torus_read_env "$state" TIS_DIGEST)"
  BACKUP_DIGEST="$(torus_read_env "$state" BACKUP_DIGEST)"
  CLOUDFLARED_DIGEST="$(torus_read_env "$state" CLOUDFLARED_DIGEST)"
  GHCR_OWNER="$(torus_read_env "$TORUS_RUN_DIR/torus-backup.env" GHCR_OWNER)"
  [[ "$TAG" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || torus_fail "invalid current tag"
  [[ "$GHCR_OWNER" =~ ^[a-z0-9_.-]+$ ]] || torus_fail "invalid GHCR owner"
  torus_validate_digest "$TIS_DIGEST"
  torus_validate_digest "$BACKUP_DIGEST"
  torus_validate_digest "$CLOUDFLARED_DIGEST"
  export TAG TIS_DIGEST BACKUP_DIGEST CLOUDFLARED_DIGEST GHCR_OWNER
}

torus_load_manifest() {
  local file="$1" line key value
  TIS_DIGEST=""
  BACKUP_DIGEST=""
  SOURCE_SHA=""
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ "$line" =~ ^([A-Z_]+)=([^[:space:]]+)$ ]] || torus_fail "malformed release manifest"
    key="${BASH_REMATCH[1]}"
    value="${BASH_REMATCH[2]}"
    case "$key" in
      TIS_DIGEST) TIS_DIGEST="$value" ;;
      BACKUP_DIGEST) BACKUP_DIGEST="$value" ;;
      SOURCE_SHA) SOURCE_SHA="$value" ;;
      *) torus_fail "unexpected release manifest key" ;;
    esac
  done <"$file"
  torus_validate_digest "$TIS_DIGEST"
  torus_validate_digest "$BACKUP_DIGEST"
  [[ "$SOURCE_SHA" =~ ^[0-9a-f]{40}$ ]] || torus_fail "invalid source commit"
  export TIS_DIGEST BACKUP_DIGEST
}

torus_resolve_digest() {
  local image="$1" digest
  digest="$(docker buildx imagetools inspect "$image" --format '{{.Manifest.Digest}}')"
  torus_validate_digest "$digest"
  printf '%s' "$digest"
}

torus_compose() {
  TIS_ENV_FILE="$TORUS_RUN_DIR/torus-tis.env" \
    CLOUDFLARED_ENV_FILE="$TORUS_RUN_DIR/torus-cloudflared.env" \
    BACKUP_ENV_FILE="$TORUS_RUN_DIR/torus-backup.env" \
    "${TORUS_COMPOSE[@]}" "$@"
}

torus_compose_timeout() {
  local duration="$1"
  shift
  timeout "$duration" env \
    TIS_ENV_FILE="$TORUS_RUN_DIR/torus-tis.env" \
    CLOUDFLARED_ENV_FILE="$TORUS_RUN_DIR/torus-cloudflared.env" \
    BACKUP_ENV_FILE="$TORUS_RUN_DIR/torus-backup.env" \
    docker compose --project-name torus --file "$TORUS_APP_DIR/deploy/compose.yaml" "$@"
}
