#!/usr/bin/env bash
set -euo pipefail

[[ "${1:-}" == "--confirm" && "$#" -eq 1 ]] || {
  printf 'Usage: sudo bash deploy/host/bootstrap.sh --confirm\n' >&2
  exit 2
}

TEST_MODE="${TORUS_TEST_MODE:-0}"
ROOT="${TORUS_TEST_ROOT:-}"
if [[ "$TEST_MODE" != "1" ]]; then
  [[ "$(id -u)" -eq 0 ]] || { printf 'bootstrap requires root\n' >&2; exit 1; }
  ROOT=""
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
docker_key="$ROOT/etc/apt/keyrings/docker.asc"
docker_list="$ROOT/etc/apt/sources.list.d/docker.list"
daemon_json="$ROOT/etc/docker/daemon.json"
sops_target="$ROOT/usr/local/bin/sops"
tmpfiles_config="$ROOT/etc/tmpfiles.d/torus.conf"

say() { printf 'torus-bootstrap: %s\n' "$1"; }
run() { say "$*"; [[ "$TEST_MODE" == "1" ]] || "$@"; }

install_dirs() {
  run install -d -o torus -g docker -m 2770 "$ROOT/opt/torus/app" "$ROOT/opt/torus/state"
  run install -d -o root -g rehaanmerchant -m 0750 "$ROOT/etc/torus/age"
  run install -d -o root -g root -m 0755 "$ROOT/etc/torus/cloudflared"
  run install -d -o root -g root -m 0755 "$ROOT/etc/tmpfiles.d"
  run install -d -o rehaanmerchant -g docker -m 0700 "$ROOT/run/torus"
  if [[ "$TEST_MODE" != "1" ]]; then
    printf 'd /run/torus 0700 rehaanmerchant docker -\n' >"$tmpfiles_config"
  else
    say "write torus-prefixed tmpfiles rule for /run/torus"
  fi
  run systemd-tmpfiles --create "$tmpfiles_config"
}

ensure_user() {
  if [[ "$TEST_MODE" == "1" ]]; then
    say "ensure system owner torus exists without changing group membership"
  elif ! id torus >/dev/null 2>&1; then
    run useradd --system --home-dir /opt/torus --shell /usr/sbin/nologin torus
  fi
}

install_docker_if_missing() {
  if command -v docker >/dev/null 2>&1; then
    if [[ "$TEST_MODE" == "1" ]]; then
      say "verify Docker Engine 28.2.2 and Compose 2.40.3"
      return
    fi
    engine_version="$(docker version --format '{{.Server.Version}}')"
    compose_version="$(docker compose version --short)"
    [[ "$engine_version" == "28.2.2" ]] || {
      say "Docker Engine must be the reviewed 28.2.2 release"
      exit 1
    }
    [[ "$compose_version" == "2.40.3" ]] || {
      say "Docker Compose must be the reviewed 2.40.3 release"
      exit 1
    }
    docker info >/dev/null
    say "Docker already present: $engine_version"
    say "Compose already present: $compose_version"
    return
  fi
  run install -d -m 0755 "$(dirname "$docker_key")"
  run curl --proto '=https' --tlsv1.2 --fail --location --silent --show-error \
    https://download.docker.com/linux/ubuntu/gpg --output "$docker_key"
  run chmod 0644 "$docker_key"
  if [[ "$TEST_MODE" != "1" ]]; then
    . /etc/os-release
    arch="$(dpkg --print-architecture)"
    printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu %s stable\n' \
      "$arch" "$VERSION_CODENAME" >"$docker_list"
  else
    say "write Docker official signed repository definition"
  fi
  run apt-get update
  run apt-get install -y \
    'docker-ce=5:28.2.2-1~ubuntu.24.04~noble' \
    'docker-ce-cli=5:28.2.2-1~ubuntu.24.04~noble' \
    containerd.io docker-buildx-plugin \
    'docker-compose-plugin=2.40.3-1~ubuntu.24.04~noble'
}

install_host_tools() {
  run apt-get update
  run apt-get install -y age git jq unattended-upgrades curl ca-certificates
  run systemctl enable --now unattended-upgrades
  run systemctl enable --now systemd-timesyncd
  if [[ -x "$sops_target" ]] && "$sops_target" --version 2>/dev/null | grep -q '3.10.2'; then
    say "sops 3.10.2 already present"
    return
  fi
  temporary="$(mktemp)"
  run curl --proto '=https' --tlsv1.2 --fail --location --silent --show-error \
    https://github.com/getsops/sops/releases/download/v3.10.2/sops-v3.10.2.linux.amd64 \
    --output "$temporary"
  if [[ "$TEST_MODE" != "1" ]]; then
    printf '%s  %s\n' '79b0f844237bd4b0446e4dc884dbc1765fc7dedc3968f743d5949c6f2e701739' \
      "$temporary" | sha256sum --check --status
    install -m 0755 "$temporary" "$sops_target"
    rm -f -- "$temporary"
  else
    say "verify sops SHA-256 and install version 3.10.2"
  fi
}

merge_docker_defaults() {
  run install -d -m 0755 "$(dirname "$daemon_json")"
  if [[ "$TEST_MODE" == "1" ]]; then
    say "merge live-restore and log rotation while preserving data-root and unknown keys"
    return
  fi
  [[ -f "$daemon_json" ]] || printf '{}\n' >"$daemon_json"
  current_root="$(docker info --format '{{.DockerRootDir}}')"
  say "Docker data root detected: $current_root"
  [[ "$current_root" == "/mnt/apps/docker-root" ]] || {
    say "unexpected Docker data root; leaving daemon configuration unchanged"
    exit 1
  }
  existing_driver="$(jq -r '."log-driver" // empty' "$daemon_json")"
  if [[ -n "$existing_driver" && "$existing_driver" != "json-file" ]]; then
    say "existing log driver is incompatible; leaving daemon configuration unchanged"
    exit 1
  fi
  backup="$daemon_json.torus-backup-$(date -u +%Y%m%dT%H%M%SZ)"
  temporary="$(mktemp)"
  cp -- "$daemon_json" "$backup"
  jq 'if has("live-restore") then . else . + {"live-restore": true} end
      | if has("log-driver") then . else . + {"log-driver": "json-file"} end
      | if has("log-opts") then . else . + {"log-opts": {"max-size":"10m","max-file":"5"}} end' \
    "$daemon_json" >"$temporary"
  if cmp -s "$daemon_json" "$temporary"; then
    rm -f -- "$temporary" "$backup"
    say "Docker daemon defaults already configured"
  else
    install -m 0644 "$temporary" "$daemon_json"
    rm -f -- "$temporary"
    say "Docker daemon defaults updated; review and restart Docker separately"
  fi
}

install_torus_units() {
  run install -m 0644 "$repo_root/deploy/cloudflared/torus-cloudflared.yml" \
    "$ROOT/etc/torus/cloudflared/torus-cloudflared.yml"
  for unit in torus-backup.service torus-backup.timer torus-restore-test.service torus-restore-test.timer; do
    run install -m 0644 "$repo_root/deploy/systemd/$unit" "$ROOT/etc/systemd/system/$unit"
  done
  run systemctl daemon-reload
  run systemctl enable torus-backup.timer torus-restore-test.timer
}

ensure_user
install_docker_if_missing
install_host_tools
install_dirs
merge_docker_defaults
install_torus_units
say "complete; no inbound-network or remote-login configuration was changed"
