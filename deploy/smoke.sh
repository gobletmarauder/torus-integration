#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=deploy/lib/torus-common.sh
source "$script_dir/lib/torus-common.sh"

torus_require_deploy_user
deadline=$((SECONDS + 90))
services=(tis-scheduler tis-api cloudflared)
while (( SECONDS < deadline )); do
  healthy=1
  for service in "${services[@]}"; do
    container="$(torus_compose ps -q "$service")"
    [[ -n "$container" ]] || { healthy=0; continue; }
    [[ "$(docker inspect --format '{{.State.Health.Status}}' "$container")" == "healthy" ]] || \
      healthy=0
  done
  (( healthy == 1 )) && break
  sleep 2
done
(( healthy == 1 )) || torus_fail "containers did not become healthy within 90 seconds"

torus_compose_timeout 10s exec -T tis-api python -m tis.healthcheck api >/dev/null
torus_compose_timeout 10s logs --since 90s tis-scheduler | grep -q 'job_completed' || \
  torus_fail "scheduler did not complete a job"
torus_compose_timeout 10s exec -T cloudflared cloudflared tunnel --metrics 127.0.0.1:2000 ready >/dev/null
if torus_compose_timeout 10s logs --since 60s tis-scheduler tis-api | grep -q 'ERROR'; then
  torus_fail "Torus service emitted an ERROR during startup"
fi
torus_log "smoke PASS"
