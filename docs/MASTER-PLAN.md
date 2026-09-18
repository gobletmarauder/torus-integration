# Torus Mesh Integration Build: Master Plan

**The single source of truth for building, hosting and verifying the Torus Mesh integration layer.**
Version 1.0 · 16 September 2026 · Owner: Rehaan Merchant
Roles: **Codex** builds · **Rehaan** approves, applies and deploys · **Claude (Opus)** plans and verifies at gates only.

**Precedence:** this file wins over `torus-mesh-GTM-STACK.md` Part 23 and `torus-mesh-LOVABLE-INTEGRATION-BRIEF.md` Parts 6, 7 and 12 wherever they conflict. Those parts described a Cloudflare Worker as the integration layer; this plan moves the integration layer to the home server (decision A1 below). The Zoho data model, automations A1 to A24, field mapping rules and test ideas in those files still apply.

Companion files:

| File | Where it lives | Purpose |
|---|---|---|
| `AGENTS.md` | root of the `torus-integrations` repo | Codex's standing rules, guardrails and definition of done |
| `PROGRESS.md` | root of the `torus-integrations` repo | Live tracker Codex updates on every task |
| `docs/VERIFICATION.md` | `torus-integrations` repo | How Claude verifies each gate from a compact evidence bundle |
| `docs/MASTER-PLAN.md` | `torus-integrations` repo (copy of this file) | Milestones, tasks, acceptance criteria |
| `HOSTING.md` | Claude project + `docs/` | Containers, deploy, secrets, monitoring, backups, runbook |
| `CLOUDFLARE.md` | Claude project + `docs/` | Terraform (Codex-authored, human-applied) and manual steps |
| `torus-mesh-LOVABLE-FINAL-MESSAGE.md` | Claude project | The message that finishes the website end to end |

---

## Part 0. Questions, with the defaults this plan assumes

Answer any that differ; everything else proceeds on the default.

| # | Question | Default used | Changes if different |
|---|---|---|---|
| Q1 | Home server OS and CPU architecture? | Ubuntu Server 24.04 LTS, x86_64, Docker Engine + Compose v2 | Image platform in CI; bootstrap script |
| Q2 | Is there a UPS, and does the BIOS power back on after an outage? | Assume no; plan tolerates outages | Add NUT shutdown hook if a UPS exists |
| Q3 | Codex surface? | **Codex cloud** (tasks run in isolated containers, open PRs) for builds; **Codex CLI** locally in workspace-write sandbox for small fixes | Guardrail section 4.2 |
| Q4 | Language for the integration service? | **Python 3.12**, FastAPI, httpx, psycopg 3, APScheduler 3, uv, ruff, mypy, pytest | Whole repo layout |
| Q5 | Remote admin access to the server? | **Cloudflare Access** in front of SSH and the ops page (no open ports) | Swap for Tailscale if preferred |
| Q6 | Alerts to phone? | **Better Stack** free (heartbeats + email/push) | ntfy or Pushover |
| Q7 | Terraform state? | **Cloudflare R2** bucket as S3-compatible backend, created manually once | HCP Terraform free |
| Q8 | Supabase access from the service? | **Direct Postgres through the Supabase pooler with a least-privilege role `tis_service`** [TEST]; fallback: Supabase secret key over REST | db.py implementation |
| Q9 | Zoho edition and data center (open from before) | Standard, US data center | API base URLs, formula fields |
| Q10 | Google Workspace plan (open from before) | Business Standard (booking reminders) | Zoho reminder workflow A6 |
| Q11 | GitHub account type? | Personal account with a private repo; branch protection available on private repos only on paid plans for organizations/Pro [VERIFY] | If protection is unavailable, rely on CI-required checks via a free org or GitHub Pro |

---

## Part 1. Architecture decisions

| ID | Decision | Why | Trade-off accepted |
|---|---|---|---|
| **A1** | **Integration layer runs on the home server** as a containerized service (`tis`, Torus Integration Service), not in a Cloudflare Worker | Rehaan wants custom work on his own server, built by Codex, with one runtime and one language; free compute for phase-2 jobs (rolodex, scoring) | Home outages delay syncs. Accepted because the browser writes every lead to Supabase first, Stripe retries webhooks for days, and Better Stack alerts on missed heartbeats |
| **A2** | **The website stays at the edge**: Lovable repo (TanStack Start with server-side rendering) → GitHub → Cloudflare Workers Builds, deployed as a Worker with the official Cloudflare Vite plugin. Its server code renders pages, reads content with the publishable key and records first-party analytics only; no third-party APIs or secrets | Uptime of the front door must not depend on the home server; SSR keeps titles and copy in the HTML | None |
| **A3** | **No Lovable-hosted integrations, no Supabase Edge Functions, no browser calls to integration endpoints** | One integration runtime; nothing secret near the browser | Turnstile tokens must be verified within ~5 minutes, so the lead job polls every 30 seconds |
| **A4** | **Supabase is the contract between site and service**: `leads` (capture), `integration_log` (audit), `integration_state` (sync tokens, kill switch), `prospects` (phase 2), RPCs for admin actions | The site and service never talk directly; each can be down independently | Polling instead of push; fine at this volume |
| **A5** | **Containerize with Docker Compose** on one host. No Kubernetes, Swarm, Nomad, or auto-updaters | Reproducible, easy rollback, minimal upkeep | Single host is a single point of failure for syncs (not for leads) |
| **A6** | **Secrets encrypted in the repo with SOPS + age**; the age private key exists only on the server and in Rehaan's password manager | Rebuildable server, versioned secrets, Codex and CI never see plaintext | One more tool; the key backup is critical |
| **A7** | **Nothing on the home server is publicly reachable in phase 1.** Cloudflare Tunnel (outbound only) exposes `ops.torusmesh.com` behind Cloudflare Access. `hooks.torusmesh.com` appears only when Stripe webhooks arrive in phase 2 | Smallest attack surface | Phase 1 has no inbound webhooks (none are needed) |
| **A8** | **Deploys are pull-based and human-triggered**: CI builds and scans images to GHCR; Rehaan runs `deploy.sh <version>` on the server after the gate passes; automatic rollback on failed smoke test | A compromised repo or a bad merge cannot reach production by itself | Deploys need Rehaan for a minute |
| **A9** | **Infrastructure as code for Cloudflare** via Terraform (provider `~> 5`), written by Codex, planned and applied only by Rehaan after Claude reviews the plan | Repeatable, reviewable; Terraform certification already held | Some v5 provider rough edges; pin minor versions |
| **A10** | **Claude verifies from evidence bundles, not full repos**: `make verify-bundle` produces one markdown file per gate | Keeps Opus usage small and focused | Claude sees what the bundle shows; the bundle script itself is a protected file |

### 1.1 System diagram

```
                    ┌──────────────── Cloudflare (edge) ─────────────────┐
Visitor ──► torusmesh.com ─► Worker: Lovable TanStack Start app (SSR)      │
   │                    │ DNS · WAF · Turnstile · Access · Tunnel · R2    │
   │                    └───────────────────────────▲─────────────────────┘
   │ content RPC, lead INSERT (publishable key)       │ outbound tunnel only
   ▼                                                  │
Supabase (Postgres) ◄──── tis_service role ───── Home server (Docker Compose)
  leads · integration_log · integration_state        ├─ tis-scheduler  (jobs)
  prospects · RPCs                                    ├─ tis-api        (ops status; phase 2 webhooks)
                                                      ├─ cloudflared    (tunnel)
Google Calendar ◄── service account (read-only) ──────┤
Zoho CRM ◄──────── OAuth refresh token ───────────────┤
PostHog ◄───────── server events ─────────────────────┤
Better Stack ◄──── heartbeats ─────────────────────────┤
R2 (backups, age-encrypted) ◄── nightly pg_dump ───────├─ backup
                                                      └─ (no containers with Docker socket access)
Browser ──► PostHog (direct, after consent) · Google booking iframe
```

### 1.2 Data contracts (Supabase)

| Object | Writer | Reader | Notes |
|---|---|---|---|
| `leads` | Browser (anon INSERT on listed columns) | `tis_service` (select, update sync columns), admins (select) | Row exists before any integration runs |
| `integration_log` | `tis_service` | Admins | Unique `(source, external_id, action)` for idempotency |
| `integration_state` | `tis_service`; admins via RPC for `kill_switch` | `tis_service`, admins | Keys: `kill_switch`, `gcal_sync_token`, `last_run:<job>` |
| `prospects` | `tis_service` | `tis_service` | Phase 2; no anon or admin UI access |
| RPC `request_lead_resync(id)` | Admins | | Resets attempts and `next_retry_at` so the next poll retries |
| RPC `set_integration_kill_switch(on)` | Admins | | Stops all external writes within 30 seconds |

---

## Part 2. Repositories and ownership

| Repo | Owner | Contains | Deploys |
|---|---|---|---|
| **Lovable site repo** (existing) | Lovable only (plus `wrangler.jsonc` created by Lovable per the final message) | React app, Supabase migrations, `_headers`, robots, sitemap | Cloudflare Workers Builds on push to `main` |
| **`torus-integrations`** (new, private) | Codex via PRs; Rehaan merges | Integration service, tests, Dockerfile, compose, deploy scripts, Terraform, SOPS-encrypted secrets, docs | Images to GHCR via CI; production via `deploy.sh` |

**Rule:** Codex never opens PRs against the Lovable repo, and Lovable never touches `torus-integrations`. Database schema changes are requested through Lovable (they own migrations), using SQL that Codex drafts in `docs/sql/` for Rehaan to paste into the Lovable message.

### 2.1 `torus-integrations` layout

```
AGENTS.md                      protected
PROGRESS.md
Makefile
pyproject.toml / uv.lock
Dockerfile
.env.example                   names only, no values
.sops.yaml                     protected
secrets/prod.enc.env           protected (SOPS encrypted)
src/tis/
  config.py                    pydantic settings; DRY_RUN default true outside prod
  http.py                      single HTTP client: egress allowlist, timeouts, retries, redaction
  log.py                       JSON logs, PII redaction
  db.py                        psycopg pool with tis_service
  state.py                     kill switch, sync tokens, last-run stamps
  guards.py                    write budgets, dry-run wrapper, idempotency helper
  integrations/                zoho.py, google_calendar.py, turnstile.py, posthog.py, betterstack.py
  mapping/                     lead_to_zoho.py, source_rules.py, booking_parser.py
  jobs/                        lead_sync.py, booking_sync.py, keepalive.py, host_health.py
  api/app.py                   FastAPI: /healthz (internal), /ops/status (Access-protected)
  scheduler.py                 APScheduler entrypoint
tests/
  unit/ · contract/ (recorded fixtures) · fixtures/
scripts/
  guard.py                     static policy checks (protected)
  verify_bundle.sh             builds the Claude evidence bundle (protected)
deploy/                        protected
  compose.yaml · deploy.sh · rollback.sh · smoke.sh
  backup/backup.sh · backup/restore-test.sh
  host/bootstrap.sh
infra/cloudflare/              protected
  versions.tf · providers.tf · variables.tf · tunnel.tf · access.tf · dns.tf · r2.tf · turnstile.tf · waf.tf · outputs.tf
docs/
  MASTER-PLAN.md · VERIFICATION.md · HOSTING.md · CLOUDFLARE.md · sql/ · runbooks/ · bundles/ (gitignored)
.github/
  CODEOWNERS (protected) · pull_request_template.md · workflows/ci.yml · workflows/release.yml (protected)
```

**Protected paths** (changes require the `protected-change` label, a Claude verification, and Rehaan's review): `AGENTS.md`, `.github/**`, `deploy/**`, `infra/**`, `.sops.yaml`, `secrets/**`, `scripts/guard.py`, `scripts/verify_bundle.sh`, `src/tis/http.py` (egress allowlist), `src/tis/guards.py`.

---

## Part 3. Validation gates

Every milestone passes the gates in order. A gate is **PASS** only with the evidence listed. Codex records gate status in `PROGRESS.md`; Claude issues PASS or FAIL from the bundle; Rehaan acts.

| Gate | Name | Who | Evidence required | Blocks |
|---|---|---|---|---|
| **G0** | Plan | Codex writes, Rehaan approves (Claude optional for protected paths) | Task plan in `PROGRESS.md`: scope, files to touch, protected paths touched (yes/no), new dependencies, new egress hosts, test plan, rollback | Coding |
| **G1** | Local checks | Codex | `make check` green: ruff, mypy (strict on `src/tis`), pytest with coverage ≥ 85% on `mapping/` and `jobs/`, `scripts/guard.py`, gitleaks, pip-audit | Opening PR |
| **G2** | CI | GitHub Actions | Same as G1 plus Docker build, Trivy image scan (no fixable HIGH/CRITICAL), SBOM artifact, license check (no GPL/AGPL in runtime deps), `terraform fmt -check` and `validate` for infra changes | Merge |
| **G3** | Verification | Claude | `docs/bundles/<milestone>.md` from `make verify-bundle` reviewed against `docs/VERIFICATION.md`; written PASS/FAIL with findings | Merge for protected paths and every milestone end |
| **G4** | Dry run on server | Rehaan | Deploy the tag with `DRY_RUN=true` for at least 30 minutes; `integration_log` shows intended writes with `status = skipped`; no errors; heartbeats green | Live writes |
| **G5** | Live enable | Rehaan | Flip `DRY_RUN=false` for one job at a time; run the milestone's acceptance tests; smoke test passes | Next milestone |
| **G6** | Burn-in | Rehaan, Claude reviews summary | 24 hours: zero unsynced leads older than 30 minutes, zero error rows, heartbeats green, no container restarts beyond autoheal events explained | Milestone closed |

**Stop conditions (any gate):** a secret appears in a diff, log or bundle; a test is skipped or deleted to go green; a new egress host without an approved plan; any write to production systems from CI or a Codex environment; any change to protected paths without the label. Response: stop, revert, rotate anything exposed, record in `PROGRESS.md` incidents.

---

## Part 4. Safety model (defense in depth)

Instructions shape intent; controls enforce limits. Each risk has at least one mechanical control, not just a rule in `AGENTS.md`.

### 4.1 Risk to control map

| Risk | Mechanical controls | Detective controls |
|---|---|---|
| Codex exfiltrates or prints secrets | Codex environments never receive secrets; prod secrets only as SOPS ciphertext; age key only on the server; CI has no decryption key | gitleaks in G1/G2; bundle redaction check; Claude G3 |
| Codex adds malicious or typosquatted dependencies | `uv.lock` pinned with hashes; new deps must appear in the G0 plan; `guard.py` fails if `pyproject.toml` deps change without `docs/dependencies.md` entry | pip-audit, Trivy, license check, Claude reviews the dependency diff |
| Service calls unexpected hosts (data exfiltration, SSRF) | `http.py` egress allowlist raises on non-allowlisted hosts; `guard.py` fails on direct `requests`/`urllib`/`socket` use outside `http.py` | Allowlist diff in every bundle |
| Destructive database actions | `tis_service` role has only select/insert/update on four tables, no delete, no DDL; migrations are owned by Lovable, not Codex | `guard.py` flags `DROP`, `TRUNCATE`, `DELETE` in SQL strings |
| Runaway writes to Zoho (loops, duplicates) | Idempotency keys in `integration_log`; per-run write budgets (default 25 creates per job run, 200 per day); kill switch; `DRY_RUN` default true | Daily write counts in the ops status; Better Stack alert when budget is hit |
| CI or workflow tampering | `.github/**` protected via CODEOWNERS; workflows use `permissions: contents: read` by default; third-party actions pinned by commit SHA; no `pull_request_target` | Claude reviews any protected diff |
| Compromised image reaching production | Deploy by digest; Trivy gate; human-triggered pull; containers non-root, read-only root filesystem, `cap_drop: ALL`, `no-new-privileges` | `deploy.sh` prints digest; ops status shows running digest |
| Host compromise via exposed ports | No port forwards; tunnel outbound only; Access for ops and SSH; UFW default deny inbound | Cloudflare Access logs |
| Codex modifies its own rules | `AGENTS.md`, `guard.py`, `verify_bundle.sh` protected | Hash of protected files printed in every bundle |
| Prompt injection from fetched content (web pages, API responses) | Codex cloud agent internet off by default; package installs only in setup phase | Claude G3 notes any code that interprets remote text as instructions |

### 4.2 Codex environment settings

**Codex cloud (primary):**
- Environment: `torus-integrations`, connected to the private repo.
- **Agent internet access: off.** Setup phase installs dependencies with network (Codex cloud runs setup with network before the agent phase).
- Setup script: `pip install uv && uv sync --frozen`.
- **No secrets or environment variables with real values.** Tests use fixtures and fakes.
- Codex works on branches and opens PRs; it never merges.

**Codex CLI (secondary, on Rehaan's laptop only, never on the home server):** user-level `~/.codex/config.toml`:

```toml
sandbox_mode = "workspace-write"
approval_policy = "on-request"

[sandbox_workspace_write]
network_access = false
```

Never use `danger-full-access`, `--yolo`, or `--dangerously-bypass-approvals-and-sandbox`. Before a session, `git status` must be clean so every change is reviewable as a diff.

**GitHub:**
- Branch protection on `main`: PR required, CI required, 1 approving review (Rehaan), CODEOWNERS review for protected paths, no force pushes, no deletions [VERIFY availability for the account type, Q11].
- CODEOWNERS: `* @rehaan` and protected paths `@rehaan`.
- Repository secrets: only `GHCR` publishing via the built-in `GITHUB_TOKEN` with `packages: write` in `release.yml`. No Zoho, Google, Supabase or Cloudflare credentials in GitHub.

---

## Part 5. Milestones

Each milestone lists tasks for Codex, acceptance criteria, and the gates. Codex takes one milestone at a time; each task is one PR unless stated.

### M0. Repo bootstrap and guardrails

| Task | Details |
|---|---|
| M0.1 | Create layout (2.1), `pyproject.toml` with uv, Python 3.12, ruff, mypy strict for `src/tis`, pytest, coverage |
| M0.2 | `Makefile` targets: `setup`, `check`, `test`, `lint`, `type`, `guard`, `audit`, `build`, `verify-bundle`, `tf-fmt`, `tf-validate` |
| M0.3 | `scripts/guard.py` policy checks: forbidden imports outside `http.py` (`requests`, `urllib.request`, `http.client`, `socket`); `subprocess` with `shell=True`; `eval`/`exec`; `pickle.loads`; base64-encoded blobs over 200 characters; hardcoded URLs not in the allowlist; SQL strings containing `DROP`, `TRUNCATE`, `ALTER`, `GRANT`, `DELETE`; `print(` in `src/`; changes to dependencies without `docs/dependencies.md`; any file under protected paths changed (reports list, does not fail) |
| M0.4 | `scripts/verify_bundle.sh` (spec in `docs/VERIFICATION.md` Part 2) |
| M0.5 | `.github/workflows/ci.yml` (G2 checks; `permissions: contents: read`; actions pinned by SHA); `release.yml` (on tag `v*`: build, Trivy, SBOM, push `ghcr.io/<owner>/tis:<tag>` and print digest) |
| M0.6 | `CODEOWNERS`, PR template (scope, gates, protected paths touched, new deps, new egress hosts, evidence links) |
| M0.7 | `.env.example` listing every setting name with descriptions and no values; `.sops.yaml` with the age public key placeholder |
| M0.8 | `PROGRESS.md` initialized from the template |

**Acceptance:** CI green on an empty service; guard catches a planted violation in a test branch; bundle script produces a file. **Gates:** G0, G1, G2, G3.

### M1. Core library

| Task | Details |
|---|---|
| M1.1 | `config.py`: pydantic-settings; `ENV` (`dev`, `prod`); `DRY_RUN` default `true` unless `ENV=prod` and explicitly `false`; per-job enable flags; write budgets |
| M1.2 | `http.py`: one `httpx.AsyncClient` factory; allowlist from config (Part 6); 10-second default timeout; retries with jitter on 429/5xx for idempotent calls; request/response logging with header and body redaction; raises `EgressDenied` |
| M1.3 | `log.py`: JSON logs to stdout; redaction of emails (to domain), names, tokens, phone numbers; correlation id per job run |
| M1.4 | `db.py`: psycopg 3 async pool; connection string from settings; statement timeout 10 seconds; helper queries only (no ORM) |
| M1.5 | `state.py`: kill switch (cached 15 seconds), key/value state, `last_run` stamps |
| M1.6 | `guards.py`: `@external_write(source, action, key)` decorator combining kill switch, dry run (log as `skipped`), write budget, idempotency via `integration_log` upsert |
| M1.7 | `integrations/betterstack.py` heartbeat helper; `integrations/posthog.py` server capture |

**Acceptance:** unit tests prove: non-allowlisted host raises; dry run writes `skipped` logs and never calls HTTP; kill switch blocks writes; duplicate idempotency key skips; logs contain no raw email in any test. **Gates:** G0 to G3.

### M2. Lead sync (GTM Stack A1)

| Task | Details |
|---|---|
| M2.1 | `integrations/turnstile.py` siteverify |
| M2.2 | `integrations/zoho.py`: token refresh with in-memory cache (expires 5 minutes early), `search_contacts_by_email`, `search_leads_by_email`, `upsert_lead`, `create_note`, `create_task`, `find_campaign_by_name`; handles `INVALID_TOKEN` (refresh once), 429 backoff, 204 not found |
| M2.3 | `mapping/source_rules.py` and `mapping/lead_to_zoho.py` implementing `torus-mesh-LOVABLE-INTEGRATION-BRIEF.md` Part 8 and GTM Stack A1 rules (never overwrite outbound `Lead_Source`; single-word names; missing company → domain; size band → segment; `unverified` and `test` tags) |
| M2.4 | `jobs/lead_sync.py`: every 30 seconds; select up to 25 rows `crm_synced = false and (next_retry_at is null or next_retry_at <= now()) and crm_sync_attempts < 10 and is_spam = false` using `FOR UPDATE SKIP LOCKED`; verify Turnstile if token present and row younger than 5 minutes, then null the token; Contact exists → note + task; else upsert Lead with `trigger: ["workflow"]`; update row; log; PostHog `lead_synced`; backoff `min(5 min × 2^(n-1), 6 h)`; `needs_attention` at 10 attempts; `is_test = true` rows sync only when `ALLOW_TEST_SYNC=true` and get tag `test` |
| M2.5 | Contract tests with recorded Zoho response fixtures (success, duplicate, INVALID_DATA, INVALID_TOKEN, 429) |

**Acceptance (G5 on server):** brief tests T3, T4, T5, T6, T7, T13 pass (lead happy path, existing Contact, Turnstile failure, Zoho outage recovery, honeypot, admin resync via RPC). **Gates:** all.

### M3. Booking sync (GTM Stack A5)

| Task | Details |
|---|---|
| M3.1 | `integrations/google_calendar.py`: service-account JWT (RS256 via `cryptography`), token cache, `events.list` with `syncToken` in `integration_state`, full resync on 410 |
| M3.2 | `mapping/booking_parser.py`: built from a **real captured event fixture** (Rehaan books a test meeting; the job in `CAPTURE_MODE` stores the raw event redacted in `integration_log.payload`); "How did you hear about us?" → `Lead_Source` mapping per the brief Part 7.6 |
| M3.3 | Zoho additions: `convert_lead`, `create_account`, `create_contact`, `create_deal`, `update_deal`, `create_event`, `update_event` |
| M3.4 | `jobs/booking_sync.py`: every 2 minutes; created, rescheduled, cancelled flows; per-event error isolation; PostHog `booking_complete` |

**Acceptance:** brief tests T8, T9, T10 pass. **Gates:** all.

### M4. Service packaging

| Task | Details |
|---|---|
| M4.1 | `scheduler.py`: APScheduler with jobs from config, `max_instances=1`, coalescing, misfire grace; each job wraps run → heartbeat on success |
| M4.2 | `jobs/keepalive.py` (daily content RPC), `jobs/host_health.py` (every 5 minutes: disk usage of mounted `/host-state` < 85%, last backup age < 26 hours from `integration_state`, unsynced leads older than 30 minutes = 0, booking errors last hour = 0 → heartbeat `tis-health`) |
| M4.3 | `api/app.py`: `/healthz` (process up, DB reachable) bound to the internal Docker network; `/ops/status` JSON (running version and digest, job last-run times, kill switch, today's write counts, unsynced counts) that validates the `Cf-Access-Jwt-Assertion` header against the Access team keys and audience |
| M4.4 | `Dockerfile`: multi-stage, `python:3.12-slim` pinned by digest, non-root uid 10001, no compilers in final stage, `HEALTHCHECK`, `PYTHONDONTWRITEBYTECODE`, read-only friendly |
| M4.5 | `deploy/compose.yaml` per `HOSTING.md` Part 3 |

**Acceptance:** `docker compose up` locally with fakes runs all jobs in dry run; Trivy clean; image under 250 MB. **Gates:** G0 to G3.

### M5. Home server deployment tooling

| Task | Details |
|---|---|
| M5.1 | `deploy/host/bootstrap.sh`: idempotent, prints every action, requires `--confirm`; installs Docker from the official repo, creates `torus` user and `/opt/torus`, UFW default deny inbound, unattended security upgrades, Docker log rotation, sops and age install. **No curl-pipe-to-shell.** |
| M5.2 | `deploy/deploy.sh <tag>`: resolve digest from GHCR, verify it matches the release notes digest, decrypt secrets with SOPS to `/run/torus/prod.env` (tmpfs, mode 600), `docker compose pull`, `up -d`, run `smoke.sh`, on failure `rollback.sh` to the previous recorded digest, record deploy in `/opt/torus/deploys.log` |
| M5.3 | `deploy/smoke.sh`: containers healthy within 90 seconds; `/healthz` ok; scheduler logged a run; no ERROR lines in the first 60 seconds |
| M5.4 | `deploy/backup/backup.sh`: nightly `pg_dump --schema=public` with the `postgres` role via the session pooler (client version ≥ server version) → gzip → `age` encrypt to the backup public key → upload to R2 with rclone; retention 7 daily, 4 weekly; write `last_backup_at` to `integration_state`; heartbeat `tis-backup` |
| M5.5 | `deploy/backup/restore-test.sh`: weekly, inside the backup image: download latest, decrypt with a restore-test key pair, restore into a temporary local Postgres on tmpfs, run row-count sanity queries, discard, heartbeat `tis-restore-test` |

**Acceptance:** bootstrap run on the server with output reviewed; deploy, forced smoke failure, automatic rollback demonstrated; one backup and one restore test succeed. **Gates:** all (every file here is protected, so G3 is mandatory).

### M6. Cloudflare infrastructure

Per `CLOUDFLARE.md`. Codex writes Terraform; Rehaan plans and applies.

| Task | Details |
|---|---|
| M6.1 | Provider and R2 backend config; variables with no defaults for ids |
| M6.2 | Tunnel (remotely managed) and ingress for `ops.torusmesh.com` → `http://tis-api:8080` and `ssh.torusmesh.com` → `ssh://host-gateway:22`, ending with a `http_status:404` catch-all |
| M6.3 | Access applications and policies for `ops.torusmesh.com` and `ssh.torusmesh.com` (email = Rehaan only, session 12 hours) |
| M6.4 | DNS CNAMEs for tunnel hostnames with `lifecycle { prevent_destroy = true }`; **no management of existing MX/SPF/DKIM/DMARC records** |
| M6.5 | Turnstile: **not managed** (created in the dashboard to unblock the site); document its hostnames in `docs/CLOUDFLARE.md` only |
| M6.6 | R2 buckets `torus-backups` (and the state bucket as a data source only) |
| M6.7 | Zone settings and rules: SSL strict, Always Use HTTPS, `www` redirect, WAF custom rule reserved for `hooks` (phase 2) |

**Acceptance:** `terraform plan` shows only creates (no destroys) on first apply; Claude reviews `plan.txt`; after apply, `ops.torusmesh.com` requires login and returns status. **Gates:** G0 to G3, then apply by Rehaan.

### M7. Production cutover and burn-in

| Step | Owner |
|---|---|
| Lovable final message complete and QA passed (site on `workers.dev`) | Rehaan + Lovable |
| Site DNS cutover to Workers custom domain (Cloudflare doc Part 5) | Rehaan |
| `tis` deployed dry run (G4), then live lead sync (G5), then live booking sync (G5) | Rehaan |
| Full brief test plan T1 to T15 (T14 = Cloudflare rollback drill; add `deploy.sh` rollback drill) | Rehaan |
| 24-hour burn-in (G6); Claude reviews the burn-in bundle | Rehaan + Claude |

### Phase 2 milestones (triggered, same gates)

| ID | Milestone | Trigger | Notes |
|---|---|---|---|
| M8 | Stripe webhook (A15) | 5 payments | Adds `hooks.torusmesh.com` tunnel route, WAF rule allowing only `POST /stripe`, signature verification, idempotent on event id |
| M9 | Rolodex pipeline + queue page (GTM Stack 4.3) | Week 2 | Search API, public ATS boards, Claude scoring via Anthropic API, `prospects` table, queue page on `ops.torusmesh.com/queue`; **no LinkedIn access of any kind** (guard.py blocks `linkedin.com` in the allowlist) |
| M10 | Instantly reply poll (A22) | 20 positive replies/month | Read-only API |
| M11 | Aikido pull into the Sunday scorecard | Week 3 | Read-only API if available on free |
| M12 | Marketing email sync | 300 Nurture contacts | Zoho webhook via `hooks` hostname |

---

## Part 6. Egress allowlist (initial)

| Host | Purpose | Milestone |
|---|---|---|
| `accounts.zoho.com` | OAuth token refresh | M2 |
| `www.zohoapis.com` | CRM API | M2 |
| `challenges.cloudflare.com` | Turnstile siteverify | M2 |
| `oauth2.googleapis.com` | Service-account token | M3 |
| `www.googleapis.com` | Calendar API | M3 |
| `us.i.posthog.com` | Server events | M1 |
| `uptime.betterstack.com` | Heartbeats | M1 |
| `<project-ref>.supabase.co` | Content RPC keepalive | M4 |
| Supabase pooler host (Postgres, not HTTP) | Database | M1 |
| `<account-id>.r2.cloudflarestorage.com` | Backups (backup container only) | M5 |
| Access team domain `<team>.cloudflareaccess.com` | Access JWT keys | M4 |

Adding a host requires the G0 plan to name it, the allowlist diff in the bundle, and Claude's PASS.

---

## Part 7. Rehaan's manual steps (not delegable to Codex)

| When | Step |
|---|---|
| Before M2 | Zoho Self Client and refresh token; Zoho custom fields and workflows (GTM Stack Part 2 and 3); export field API names into `docs/zoho-fields.md` |
| Before M2 | Run the Lovable final message; confirm migrations; set the `tis_service` password in the Supabase SQL editor (never in a repo) |
| Before M3 | Google service account and domain-wide delegation; appointment schedule; one test booking for the fixture |
| Before M5 | age key pair on the server (`age-keygen`), public key into `.sops.yaml`, private key into the password manager; separate backup age key pair |
| Before M5 | Populate `secrets/prod.enc.env` with `sops` on the server or laptop that has the key, commit the ciphertext |
| M6 | Cloudflare API token for Terraform; R2 state bucket; `terraform plan` / `apply` |
| Every gate | Run `make verify-bundle`, send the bundle to Claude, record the verdict |
| Every deploy | `deploy.sh <tag>` |

---

## Part 8. How to hand work to Codex

**Codex cloud task template (one milestone at a time):**

```
Repository: torus-integrations
Read AGENTS.md, PROGRESS.md and docs/MASTER-PLAN.md before doing anything.

Task: <milestone id and task ids, e.g. M2.1 to M2.5>

1. Write the G0 plan into PROGRESS.md under the milestone (scope, files, protected paths touched, new dependencies with justification, new egress hosts, tests, rollback). Stop and open a draft PR containing only the PROGRESS.md change titled "G0 plan: <milestone>".
```

After Rehaan approves the plan (comment "G0 approved" on the draft PR):

```
G0 approved for <milestone>. Implement exactly the approved plan on the same branch.
Run make check until green. Update PROGRESS.md (task status, gate G1 evidence, decisions, open questions).
Run make verify-bundle and commit nothing from docs/bundles/ (it is gitignored); paste the bundle path in the PR description.
Mark the PR ready for review. Do not merge.
```

**Codex never:** merges, tags releases, deploys, runs Terraform plan/apply, touches the Lovable repo, or requests secrets.

---

## Part 9. Definition of done for the whole phase 1

- Website live on Cloudflare with Lovable final-message QA complete.
- `tis` running on the home server from a tagged image, deployed by digest, with automatic rollback tested.
- Leads reach Zoho within 60 seconds (p95), bookings within 3 minutes.
- Kill switch tested from the admin screen.
- Heartbeats for sync, health, backup and restore test all green for 7 days.
- One successful restore test from R2.
- All milestone bundles verified PASS by Claude and linked in `PROGRESS.md`.
- No secrets anywhere except SOPS ciphertext, the server's tmpfs, Cloudflare (for Cloudflare-native objects only) and the password manager.
