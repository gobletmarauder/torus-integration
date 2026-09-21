# Service packaging runbook

## Safe local validation

Run `make check`, `make compose-config`, and `make image-size`. These commands use repository code, synthetic Compose values, and the local Docker daemon only. They must not use a production environment file or make a real service request.

## Scheduler unhealthy

The scheduler healthcheck fails when its watchdog file is absent or stale. Inspect redacted container logs for `job_failed`, confirm the database is reachable, and confirm `/tmp` is writable. Keep `DRY_RUN=true` while correcting configuration. Do not delete integration state or retry external records manually.

## API unhealthy or denied

`/healthz` returns only `ok` or `unavailable`; an unavailable response means the configured database check failed. `/ops/status` requires a valid Cloudflare Access JWT for the exact team issuer and audience. Signing-key retrieval, rotation, malformed tokens, and claim failures deny access without exposing token or key material.

## Host-health heartbeat absent

The health heartbeat is deliberately suppressed if disk use is at least 85%, `last_backup_at` is missing or at least 26 hours old, an unsynced lead is older than 30 minutes, a booking error occurred in the last hour, the kill switch is on, or a dependency fails. Before M5 records the first backup timestamp, this check is expected to fail closed.

## Rollback

Keep the kill switch on and all job enable flags off, stop the Compose stack, then restore the last reviewed image digest and Compose revision. Preserve `integration_log` and `integration_state`; do not remove audit or cursor records to force retries.
