# Torus Mesh Home Server Hosting

**How the Torus Integration Service (`tis`) runs on the home server: containers, deploys, secrets, monitoring, backups and the runbook.**
Version 1.0 · 16 September 2026 · Owner: Rehaan Merchant
Reads with: `MASTER-PLAN.md` (decisions A1 to A10, milestones M4 and M5) and `CLOUDFLARE.md` (tunnel and Access).

**Goal:** it runs on its own, tells you when it doesn't, and can be rebuilt from the repo, the password manager and R2 in under an hour.

---

## Part 1. The decisions

### 1.1 Containerize? Yes, with Docker Compose

| Option | Verdict | Why |
|---|---|---|
| **Docker Compose on one host** | **Use** | Reproducible images, pinned digests, one-command deploy and rollback, restart policies, resource limits, easy to reason about |
| systemd services with a Python virtualenv | No | Works, but upgrades, rollback and dependency drift are manual; harder to scan |
| Kubernetes / k3s / Nomad / Swarm | No | Orchestration for one host and three containers is maintenance without benefit |
| Portainer / Coolify / CasaOS-style panels | No | Another admin surface with its own vulnerabilities and upgrade cycle |
| Watchtower or any auto-updater | **No** | Unreviewed images reaching production defeats the gates |

### 1.2 What runs where

| Component | Location | Why |
|---|---|---|
| Website | Cloudflare (Workers static assets) | Front door must stay up when home is down |
| Lead capture (durable row) | Supabase | Survives any home outage |
| Lead sync, booking sync, health, keepalive | Home server `tis-scheduler` | Custom code, one runtime |
| Ops status page (and later webhooks, queue page) | Home server `tis-api` via Cloudflare Tunnel | No open ports |
| Backups | Home server `backup` → R2 | Off-site, encrypted |
| Alerts | Better Stack (external) | An external watcher notices when home goes dark |

### 1.3 What happens during outages

| Event | Effect | Recovery |
|---|---|---|
| Home internet down 2 hours | Leads keep landing in Supabase; no Zoho records, alerts or acknowledgment emails until back; Turnstile tokens expire so those leads sync with tag `unverified` | Automatic catch-up within minutes of reconnecting |
| Power outage | Same as above; containers restart when Docker starts (BIOS "power on after AC loss" should be enabled; a UPS is recommended) | Automatic if the host boots; Better Stack alerts if not |
| Server hardware failure | Syncs stop; leads safe | Rebuild on any Ubuntu machine from Part 9 in about an hour |
| Supabase outage | Site form shows its error with a mailto fallback; syncs pause | Automatic |
| Zoho outage | Rows retry with backoff | Automatic; `needs_attention` after 10 attempts |

---

## Part 2. Host baseline

### 2.1 Machine

- Ubuntu Server 24.04 LTS, x86_64 (Q1 in the master plan), static LAN IP or DHCP reservation.
- BIOS: restore power on AC loss; disable wake-on-LAN if unused.
- Disk: at least 20 GB free for Docker images and logs; `tis` itself needs well under 1 GB RAM.
- UPS strongly recommended.

### 2.1a Existing host inventory (read-only discovery, 2026-09-20)

This is **not** a dedicated box. It already runs 28 other containers across several
compose projects (a live trading stack under `scalprix-agentic-trader*`, Nextcloud,
Jellyfin, Immich, and a Prometheus/Grafana/Loki/Tempo observability stack). Anything
M5 automates must be additive and must not touch what is already running. Full raw
output lives with Rehaan; the facts that constrain M5 tooling:

| Area | Finding | Consequence for M5 |
|---|---|---|
| Docker/Compose | Engine 28.2.2, Compose 2.40.3, `data-root` at `/mnt/apps/docker-root` (not the default `/var/lib/docker`) | Nothing in `deploy/**` or `bootstrap.sh` may hardcode the default Docker root path |
| Host ports | 22 (ssh), 80/443 (Traefik, LAN/tailscale only), 445/139 (smb), 5433/2283 (published Postgres/Immich, loopback-only), 9091, 11434 (ollama) | Torus publishes no host port at all (`tis-api` uses `expose`, `cloudflared` is outbound-only), so there is nothing to avoid here by design; confirm at G4 with `ss -tlnp` that nothing new is listening |
| Docker networks | 8 existing bridge networks already claim `172.17.0.0/16` through `172.26.0.0/16` (`edge_net`, `obs_net`, `immich_default`, `nas_net`, three `scalprix-agentic-trader_*` networks) | `torus_internal`/`torus_egress` should land in unused pool space automatically; **G4 dry-run must include `docker network ls` to confirm no overlap/warning before sign-off** |
| Reverse ingress | An existing `scalprix-edge_cloudflared` container already runs a separate named tunnel (own token, own `/etc/cloudflared/config.yml`) fronting Traefik for the other services | Torus's own `cloudflared` sidecar must use its own distinct tunnel name/credentials/config path; `bootstrap.sh`/`deploy.sh` must never write to or reference the existing tunnel's config |
| Firewall (UFW) | Default deny incoming, allow outgoing. 22/tcp open broadly plus LAN/tailscale-scoped rules; 443/80 open to LAN/tailscale only, **not to the internet** — existing services rely entirely on outbound Cloudflare Tunnel, same pattern Torus uses | Torus needs **no new UFW rule of any kind**; a G0 plan that proposes opening a port is out of scope and should be rejected |
| SSH | `PermitRootLogin no`, `PasswordAuthentication yes`, key auth also enabled, `authorized_keys` present | See 2.2 below: the original "SSH keys only" baseline is deferred, not implemented, for this shared box |
| Backups/cron | `scalprix-backup.timer` and `backup-jellyfin.timer` already exist as systemd timers | Torus's own backup timer/service must use an unambiguous `torus-` prefix so it is never confused with the existing jobs |
| Docker group | Only `rehaanmerchant` is a member | `deploy.sh` runs as this user; no need for `sudo docker` |

### 2.2 Security baseline (done by `deploy/host/bootstrap.sh`, reviewed at G3)

| Control | Setting |
|---|---|
| Users | Dedicated `torus` system user owns `/opt/torus`; Rehaan's existing admin user keeps its current access unchanged |
| ~~SSH~~ **Deferred** | Original baseline called for disabling password SSH login and restricting it in UFW. **Deferred out of M5 scope** per the 2026-09-20 discovery: this box already runs other services under the current SSH/UFW config, Torus ingress is entirely outbound via its own tunnel and needs no inbound SSH change, and touching `sshd_config` or existing SSH-related UFW rules risks locking Rehaan out of everything on the box, not just Torus. `bootstrap.sh` must not modify `sshd_config` or any existing UFW rule. Revisit as its own reviewed, isolated change if Rehaan wants it later. |
| Inbound firewall | No change made by Torus tooling. UFW is already default-deny-incoming on this host with 443/80 open to LAN/tailscale only (not the internet) and existing SSH rules unchanged; Torus adds zero new rules since ingress is outbound-only via its own Cloudflare Tunnel |
| Port forwarding on the router | None |
| Updates | `unattended-upgrades` for security updates daily; automatic reboot if required at Sunday 04:00 local |
| Docker | Official Docker apt repository with its signing key; `live-restore: true`; default log driver `json-file` with `max-size 10m`, `max-file 5` in `/etc/docker/daemon.json` |
| Time | `systemd-timesyncd` on (JWT validation and OAuth depend on correct time) |
| Tools | `sops`, `age`, `git`, `jq` from package sources with checksums verified |
| Secrets directory | `/etc/torus/` root-owned `0700`; age key file `0600` |

### 2.3 Directory layout

```
/opt/torus/
  app/                 git checkout of torus-integrations at the deployed tag (compose, scripts, encrypted secrets)
  state/               small files: current and previous digest, deploys.log
/etc/torus/
  age/tis.key          age private key for SOPS (0600, root)
/run/torus/            tmpfs; decrypted env files exist only during deploy
```

---

## Part 3. The Compose stack

### 3.1 Services

| Service | Image | Purpose | Network | Published ports |
|---|---|---|---|---|
| `tis-scheduler` | `ghcr.io/<owner>/tis@sha256:…` | Jobs: lead sync (30 s), booking sync (2 min), health (5 min), keepalive (daily) | `internal`, `egress` | None |
| `tis-api` | same image | `/healthz` (internal), `/ops/status` (via tunnel, Access JWT required) | `internal`, `egress` | None |
| `cloudflared` | `cloudflare/cloudflared@sha256:…` | Outbound tunnel for `ops.torusmesh.com` (and `ssh.torusmesh.com`) | `internal`, `egress` | None |
| `backup` | `ghcr.io/<owner>/tis-backup@sha256:…` (postgres client, rclone, age, supercronic) | Nightly encrypted dump to R2; weekly restore test | `egress` + its own scratch network | None |

**Deliberately not included:** containers that mount the Docker socket (log viewers, auto-healers). Socket access is root-equivalent on the host. Instead, each `tis` process has an internal watchdog that exits if its loop stalls, and Docker's restart policy brings it back. Logs are read with `docker compose logs` over SSH through Access.

### 3.2 `deploy/compose.yaml` (reference for Codex, milestone M4.5)

```yaml
name: torus

x-hardening: &hardening
  restart: unless-stopped
  read_only: true
  cap_drop: ["ALL"]
  security_opt: ["no-new-privileges:true"]
  logging:
    driver: json-file
    options: { max-size: "10m", max-file: "5" }

services:
  tis-scheduler:
    <<: *hardening
    image: "ghcr.io/${GHCR_OWNER}/tis@${TIS_DIGEST}"
    user: "10001:10001"
    command: ["python", "-m", "tis.scheduler"]
    env_file: ["/run/torus/tis.env"]
    tmpfs: ["/tmp:size=64m,mode=1777"]
    volumes:
      - /opt/torus/state:/host-state:ro      # disk usage check reads this filesystem only
    networks: [internal, egress]
    mem_limit: 512m
    cpus: 1.0
    healthcheck:
      test: ["CMD", "python", "-m", "tis.healthcheck", "scheduler"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 30s

  tis-api:
    <<: *hardening
    image: "ghcr.io/${GHCR_OWNER}/tis@${TIS_DIGEST}"
    user: "10001:10001"
    command: ["uvicorn", "tis.api.app:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers"]
    env_file: ["/run/torus/tis.env"]
    tmpfs: ["/tmp:size=32m,mode=1777"]
    expose: ["8080"]
    networks: [internal, egress]
    mem_limit: 256m
    cpus: 0.5
    healthcheck:
      test: ["CMD", "python", "-m", "tis.healthcheck", "api"]
      interval: 30s
      timeout: 5s
      retries: 3

  cloudflared:
    <<: *hardening
    image: "cloudflare/cloudflared@${CLOUDFLARED_DIGEST}"
    command: ["tunnel", "--no-autoupdate", "--metrics", "0.0.0.0:2000", "run"]
    env_file: ["/run/torus/cloudflared.env"]   # TUNNEL_TOKEN only
    extra_hosts: ["host-gateway:host-gateway"] # lets the ssh.torusmesh.com route reach the host's sshd
    networks: [internal, egress]
    mem_limit: 128m
    healthcheck:
      test: ["CMD", "cloudflared", "tunnel", "--metrics", "127.0.0.1:2000", "ready"]
      interval: 30s
      timeout: 5s
      retries: 3

  backup:
    <<: *hardening
    image: "ghcr.io/${GHCR_OWNER}/tis-backup@${BACKUP_DIGEST}"
    user: "10001:10001"
    env_file: ["/run/torus/backup.env"]
    tmpfs: ["/tmp:size=1g,mode=1777", "/work:size=1g,mode=1777"]
    networks: [egress]
    mem_limit: 512m

networks:
  internal:
    internal: true
  egress: {}
```

Notes for Codex and the G3 reviewer:
- `cloudflared ready` via the metrics endpoint is supported in recent releases [VERIFY for the pinned version]; if not, use a TCP check on the metrics port.
- The weekly restore test starts a throwaway `postgres` container. Because `backup` has no Docker socket, the restore test runs **inside** the backup image using `pg_restore` into a local Postgres process started in `/work` (tmpfs), then discards it.
- `pg_dump` client major version must be ≥ the Supabase server's Postgres major version; the backup image pins it.

### 3.3 Environment files (all decrypted only during deploy)

| File | Contents | Consumed by |
|---|---|---|
| `tis.env` | `ENV=prod`, `DRY_RUN`, per-job enable flags, write budgets, Supabase pooler DSN for `tis_service`, Supabase URL and publishable key (keepalive), Zoho client id/secret/refresh token and API domains, Google service-account email/private key/impersonated user/calendar id, Turnstile secret, PostHog key and host, Better Stack heartbeat URLs, Access team domain and audience tag | `tis-scheduler`, `tis-api` |
| `cloudflared.env` | `TUNNEL_TOKEN` | `cloudflared` |
| `backup.env` | Database DSN for the `postgres` role through the session pooler (a restricted role cannot dump RLS-protected tables), R2 access key id/secret/endpoint/bucket, two age **public** recipients (offline recovery key and restore-test key), the restore-test age **private** key, Better Stack backup heartbeat URLs | `backup` |

**Honest trade-off:** Docker stores environment variables in each container's configuration under `/var/lib/docker` (root-only). That is what lets containers restart after a reboot without re-decrypting. For this threat model (single-owner home server, no inbound ports) it is acceptable. Moving to file-mounted secrets read at startup is a later hardening step if a second person ever gets shell access.

---

## Part 4. Secrets with SOPS and age

### 4.1 One-time setup (Rehaan)

```bash
# On the server, as root
install -d -m 0700 /etc/torus/age
age-keygen -o /etc/torus/age/tis.key          # prints the public key (age1...)
chmod 0600 /etc/torus/age/tis.key
cat /etc/torus/age/tis.key                    # copy the whole file into the password manager, then clear the terminal

# Offline recovery key for backups (private key ONLY in the password manager, never on the server)
age-keygen -o /tmp/backup-recovery.key && cat /tmp/backup-recovery.key
# store it in the password manager, then:
shred -u /tmp/backup-recovery.key

# Restore-test key (private key goes into secrets/backup.enc.env via sops; also save in the password manager)
age-keygen -o /tmp/restore-test.key && cat /tmp/restore-test.key
shred -u /tmp/restore-test.key
```

`.sops.yaml` in the repo (protected; Rehaan commits the public key):

```yaml
creation_rules:
  - path_regex: secrets/.*\.enc\.env$
    age: age1xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

### 4.2 Creating and editing secrets

```bash
# On a machine that has the private key (the server, via SSH)
export SOPS_AGE_KEY_FILE=/etc/torus/age/tis.key
cd /opt/torus/app
sops secrets/tis.enc.env          # opens an editor; saves encrypted
sops secrets/cloudflared.enc.env
sops secrets/backup.enc.env
git add secrets/*.enc.env && git commit -m "secrets: update (values encrypted)" && git push   # from a branch; PR as a protected change
```

Codex never runs `sops`. Claude never sees plaintext. CI never has the key.

### 4.3 Rotation

| Secret | When | How |
|---|---|---|
| Zoho refresh token | If exposed, or yearly | New grant code → new refresh token → `sops` edit → `deploy.sh <current tag> --reload-secrets` → revoke the old token in the Zoho API console |
| Google service-account key | Yearly | Create new key → `sops` edit → reload → delete old key in Google Cloud |
| `tis_service` Postgres password | Yearly | `alter role tis_service password '…'` in Supabase SQL editor → `sops` edit → reload |
| Tunnel token | If exposed | Rotate in Cloudflare (or Terraform) → `sops` edit → reload |
| R2 keys | Yearly | Create new scoped token → edit → reload → delete old |
| age key | If the server is compromised | New key pair → re-encrypt all files (`sops updatekeys`) → rotate every secret above |

---

## Part 5. Build and deploy

### 5.1 Pipeline

```
Codex branch ──► PR ──► CI (G2: lint, types, tests, guard, gitleaks, pip-audit, docker build, Trivy, SBOM)
            ──► Claude G3 verdict ──► Rehaan merges
Rehaan tags vX.Y.Z ──► release.yml builds, scans, pushes ghcr.io/<owner>/tis:vX.Y.Z and tis-backup, prints digests in the release notes
Rehaan on server ──► sudo /opt/torus/app/deploy/deploy.sh vX.Y.Z  (dry run first at G4)
```

The server needs read access to GHCR for private images: create a fine-grained GitHub token with **read:packages only**, then `sudo docker login ghcr.io -u <user>` once. That token is the only GitHub credential on the server.

### 5.2 What `deploy.sh <tag> [--dry-run|--live] [--reload-secrets]` does

1. `set -euo pipefail`; require root; take a lock file to prevent concurrent deploys.
2. `git -C /opt/torus/app fetch --tags` and check out the tag (verify the tag signature if signing is configured).
3. Read expected digests from the GitHub release notes for that tag (or `deploy/digests/<tag>.txt` committed by the release workflow) and confirm `docker buildx imagetools inspect` returns the same digests.
4. Decrypt `secrets/*.enc.env` with SOPS into `/run/torus/` (`umask 077`), set `DRY_RUN` from the flag, and register a trap that shreds those files on exit.
5. Record the currently running digests in `/opt/torus/state/previous.env`.
6. `docker compose pull` then `docker compose up -d --remove-orphans` with the new digests.
7. Run `smoke.sh` (below). On failure, run `rollback.sh` automatically and exit non-zero.
8. Write the new digests to `/opt/torus/state/current.env`, append a line to `/opt/torus/state/deploys.log`, and print the row for `PROGRESS.md`.

### 5.3 `smoke.sh`

- All four containers `healthy` within 90 seconds.
- `docker compose exec tis-api python -m tis.healthcheck api` returns 0 (database reachable).
- The scheduler logged `job_completed` for `lead_sync` within 90 seconds.
- No `ERROR` log lines from `tis-*` in the first 60 seconds.
- `cloudflared` reports ready.

### 5.4 Rollback

`sudo /opt/torus/app/deploy/rollback.sh` re-deploys the digests in `previous.env` with the secrets currently in place and runs `smoke.sh`. Drill it once during M5 by deploying a tag built to fail its healthcheck.

---

## Part 6. Monitoring and alerting

One external watcher (Better Stack), signals pushed from inside. Everything below alerts to email and the Better Stack mobile app.

| # | Monitor | Type | Sent by | Period / grace | Fires when |
|---|---|---|---|---|---|
| H1 | `tis-sync` | Heartbeat | `tis-scheduler` after a successful lead-sync run (throttled to once a minute) | 5 min / 5 min | Scheduler dead, host down, internet down, database unreachable |
| H2 | `tis-health` | Heartbeat | `host_health` job, only if: unsynced leads older than 30 minutes = 0, `needs_attention` = 0, booking sync errors in last hour = 0, disk < 85%, last backup < 26 hours, kill switch off | 5 min / 15 min | Any condition fails, including silent integration errors |
| H3 | `tis-backup` | Heartbeat | `backup` after a verified upload | 24 h / 2 h | Backup failed |
| H4 | `tis-restore-test` | Heartbeat | `backup` weekly restore test | 7 days / 1 day | Restore test failed |
| H5 | `site` | HTTP | Better Stack | 3 min | torusmesh.com down |
| H6 | `site-book` | HTTP keyword | Better Stack | 5 min | `/book` down or booking embed missing |
| H7 | `ops-tunnel` | HTTP status | Better Stack → `https://ops.torusmesh.com/` expecting a redirect to Cloudflare Access login | 5 min | Tunnel or `tis-api` down |

Better Stack's free plan limits monitor counts; seven fits within typical free allowances [VERIFY]. If it does not, merge H3 and H4 into H2.

**The ops status page** (`https://ops.torusmesh.com/ops/status`, Access login required) shows: running version and digests, each job's last success and last error time, kill switch, `DRY_RUN`, today's external write counts versus budgets, unsynced and `needs_attention` counts, last backup and restore-test times. No personal data.

**Where to look first:** Better Stack alert → ops status page → `ssh ssh.torusmesh.com` (through Access) → `cd /opt/torus/app && sudo docker compose logs --since 30m tis-scheduler`.

---

## Part 7. Backups and restore

| Item | Setting |
|---|---|
| What | Logical dump of the Supabase `public` schema and data (`pg_dump --format=custom --schema=public`) using the `postgres` role through the session pooler; that DSN exists only in `backup.env` |
| When | Nightly 03:30 UTC |
| Encryption | `age` to two recipients before upload: the **offline recovery key** (private key only in the password manager) and the **restore-test key** (private key in `backup.env`, used only by the weekly restore test). A compromised server could read backups, but it could already read the database, so this adds no new exposure |
| Where | R2 bucket `torus-backups` with an R2 token scoped to that bucket (object read and write) |
| Retention | 7 daily, 4 weekly (script-managed; bucket lifecycle rule as a backstop at 45 days) |
| Verification | Weekly restore test inside the backup container into a temporary local Postgres on tmpfs; row-count checks on `leads`, `integration_log`, content tables; heartbeat H4 |
| Real restore | Download → `age -d -i <offline recovery key from the password manager>` → `pg_restore` into a new Supabase project or local Postgres; documented in `docs/runbooks/restore.md` |

Supabase's free plan provides no downloadable backups, so this is the only restore path until the project moves to Pro.

---

## Part 8. Updates

| What | How often | How |
|---|---|---|
| Ubuntu security patches | Daily, automatic | `unattended-upgrades`; reboot Sunday 04:00 if required; containers return by restart policy |
| Docker Engine | Monthly, manual | `apt upgrade docker-ce` in a quiet window, then `smoke.sh` |
| Python dependencies and base image | Weekly PRs | Dependabot (or Renovate) → normal gates → tag → deploy |
| `cloudflared` image | Monthly PR | Digest bump → gates → deploy |
| Zoho/Google API changes | As announced | Contract fixtures updated by Codex under a milestone task |

No automatic image updates on the server, ever.

---

## Part 9. Rebuild from scratch (target: under 1 hour)

1. Install Ubuntu 24.04; set BIOS power-on after AC loss.
2. Copy `deploy/host/bootstrap.sh` from the repo, read it, run `sudo bash bootstrap.sh --confirm`.
3. Restore `/etc/torus/age/tis.key` from the password manager (`0600`).
4. `sudo git clone` the repo to `/opt/torus/app`; `sudo docker login ghcr.io` with the read-only packages token.
5. `sudo /opt/torus/app/deploy/deploy.sh <last good tag> --live`.
6. Confirm H1, H2, H7 green; check the ops status page.
7. If the tunnel was recreated, update the token secret first (the tunnel itself is in Terraform).

---

## Part 10. Runbook

| Symptom | Diagnose | Fix |
|---|---|---|
| H1 missing | Ops page unreachable too? Then host or internet. Reachable? Scheduler logs | Power/internet: wait or power-cycle. Scheduler crash loop: `docker compose logs tis-scheduler`; `rollback.sh` if it began after a deploy |
| H2 missing, H1 fine | Ops page: which condition fails | `needs_attention` → admin Leads screen `crm_last_error` (see brief Part 11 table); disk → `docker image prune -a --filter "until=168h"`; backup age → see H3 |
| H3 or H4 missing | `docker compose logs backup` | R2 token expired, Supabase unreachable, or `pg_dump` version mismatch after a Supabase upgrade (bump the client in the backup image) |
| H7 alerting, H1 fine | `docker compose logs cloudflared`; Cloudflare dashboard tunnel status | Token rotated or revoked → update `cloudflared.enc.env` → `deploy.sh <tag> --reload-secrets` |
| Duplicate or wrong Zoho records | Ops page write counts; `integration_log` for the lead id | Admin kill switch **on** → fix mapping via a Codex task → deploy → kill switch off; clean up records in Zoho by hand |
| Need everything to stop now | | Admin screen kill switch, or `sudo docker compose stop tis-scheduler` |
| Suspected compromise | Unknown processes, unexpected outbound traffic, unexplained Zoho writes | Kill switch on; `docker compose down`; revoke Zoho refresh token, Google key, tunnel token, R2 keys, `tis_service` password; rebuild from Part 9 with a new age key |
| Supabase paused (free plan) | Supabase email; H2 database check fails | Restore in the Supabase dashboard; confirm the daily keepalive job logs; consider Pro |
