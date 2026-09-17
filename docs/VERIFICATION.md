# VERIFICATION.md: How Claude verifies Codex's work

Place at `docs/VERIFICATION.md` in `torus-integrations`. Claude (Opus) is used **only** at gate G3, for Terraform plan reviews, for burn-in summaries, and for incidents. Every review is done from a compact **evidence bundle**, not the whole repository, to keep usage low and the review focused.

---

## 1. The workflow

1. Codex finishes a task set and runs `make verify-bundle MILESTONE=<id>`.
2. Rehaan checks the bundle is under ~40 KB (if larger, it is split by the script into `-part1`, `-part2`).
3. Rehaan starts a message to Claude in the Torus Mesh project with the prompt in Part 5 and attaches the bundle file.
4. Claude replies with the verdict format in Part 4.
5. Rehaan pastes the verdict into `PROGRESS.md` (G3 row and milestone section). FAIL means Codex fixes the listed items on the same branch and a new bundle is produced; Claude re-verifies only the delta (the bundle includes the previous verdict and a diff since it).

---

## 2. Evidence bundle specification (`scripts/verify_bundle.sh`, protected)

The script writes `docs/bundles/<MILESTONE>-<shortsha>.md` with these sections, in this order. It must never include secret values; it runs `gitleaks` on its own output and aborts if anything is found.

| # | Section | Content |
|---|---|---|
| 1 | Header | Milestone, branch, base commit, head commit, date, Codex task ids |
| 2 | G0 plan | Verbatim from `PROGRESS.md` |
| 3 | Scope check | Files changed (`git diff --name-status base...head`) with a column "in plan: yes/no" computed against the plan's file list |
| 4 | Protected paths | List of protected files changed; SHA-256 of every protected file at head; full diff of each changed protected file |
| 5 | Dependencies | Diff of `pyproject.toml` and summarized `uv.lock` changes (package, old → new version); `docs/dependencies.md` diff; license list for new packages |
| 6 | Egress allowlist | Diff of the allowlist in `src/tis/http.py` |
| 7 | Scopes and privileges | Grep results for OAuth scopes, `ENV`/`DRY_RUN` defaults, write budgets, and any SQL strings |
| 8 | External writes | List of functions decorated with `@external_write` (module, function, source, action, key expression); list of functions that call `http.client()` with non-GET methods **without** the decorator (should be empty) |
| 9 | Guard output | Full `scripts/guard.py` output |
| 10 | Checks summary | `ruff`, `mypy`, `pytest` (counts, coverage per package), `gitleaks`, `pip-audit`, and for images: Trivy summary |
| 11 | Tests added | Test names added or changed, and any `skip`, `xfail` or deleted tests (should be none) |
| 12 | Source diff | Full diff for `src/tis/mapping/**`, `src/tis/jobs/**`, `src/tis/guards.py`, `src/tis/http.py`; for other `src/` files, full diff if under 400 lines total, otherwise diffstat plus the 400 most relevant lines by path priority |
| 13 | Infra | For `infra/**` changes: `terraform fmt -check` and `validate` output. (Plans are reviewed separately; see Part 3.4) |
| 14 | Previous verdict | The last G3 verdict for this milestone, if any, and `git diff` since that verdict's head commit |
| 15 | Codex notes | PR description sections "Security notes", "Open questions", "Deviations from plan" |

---

## 3. Checklists

### 3.1 Every bundle (baseline)

| # | Check | Fail if |
|---|---|---|
| B1 | Plan matches diff | Files changed that are not in the plan; plan says no protected paths but section 4 lists some |
| B2 | Secrets | Anything that looks like a key, token, password, private key, connection string or real email outside fixtures |
| B3 | Protected files | Changed without `protected-change` in the plan; hash of `AGENTS.md`, `guard.py` or `verify_bundle.sh` changed unexpectedly |
| B4 | Dependencies | New package not in plan; unknown or low-reputation package; name close to a popular package (typosquat); GPL/AGPL runtime license; unpinned versions |
| B5 | Egress | New host not in plan; any LinkedIn domain; wildcard hosts; allowlist bypass |
| B6 | Execution safety | `eval`, `exec`, `shell=True`, `pickle`, dynamic import from data, remote code download, large encoded blobs |
| B7 | External writes | Any write without `@external_write`; missing idempotency key; dry run or kill switch bypass; budget increased without plan |
| B8 | SQL | `DROP`, `TRUNCATE`, `ALTER`, `GRANT`, `REVOKE`, `DELETE`, string-formatted SQL with user data (must be parameterized) |
| B9 | Logging and PII | Logging of emails, names, notes, raw payloads; `print` in `src/` |
| B10 | Tests | Skipped/xfail/deleted tests; tests making network calls; missing dry-run, kill-switch or error-path tests for new writes |
| B11 | CI integrity | Workflow permissions broadened; unpinned third-party actions; `pull_request_target`; steps removed or made non-blocking |
| B12 | Prompt injection | Code or comments that treat fetched content as instructions; suspicious TODOs asking to disable checks |

### 3.2 Milestone-specific checks

**M1 Core library**
- Egress allowlist enforced for every request path, including redirects (redirects to non-allowlisted hosts must fail).
- `DRY_RUN` default true unless `ENV=prod` and explicit `false`; tests prove it.
- Redaction covers headers (`Authorization`), query strings (`token`, `code`, `refresh_token`) and bodies.
- Kill switch cache no longer than 30 seconds.

**M2 Lead sync**
- Row locking with `FOR UPDATE SKIP LOCKED`; batch size ≤ 25.
- Turnstile verified only for rows younger than ~5 minutes; token cleared after the attempt.
- Existing Contact path creates note + task, never a Lead.
- `Lead_Source` never overwritten for outbound sources; single-word names; company fallback; segment mapping matches the brief Part 8.
- Backoff formula and 10-attempt cap; `needs_attention` set; no infinite retry on 4xx data errors (they go straight to `needs_attention` after 3).
- `is_test` rows skipped unless allowed.
- Zoho `INVALID_TOKEN` handled with one refresh and one retry only.

**M3 Booking sync**
- Parser fixture is real and redacted; parser handles missing answers.
- Idempotency on `(google_calendar, event_id, action)`; reschedule detected by start-time change; cancel handled.
- 410 Gone triggers bounded full resync (7 days).
- Service account scope is read-only calendar events; no write calls to Google.
- Personal email domain branch.

**M4 Packaging**
- Dockerfile: pinned base digest, non-root user, no build tools in final image, healthcheck present.
- `/ops/status` validates Access JWT (issuer, audience, signature, expiry) and exposes no personal data.
- `/healthz` not published to the host network.
- Scheduler `max_instances=1`, heartbeat only on success.

**M5 Deploy tooling (highest scrutiny)**
- `bootstrap.sh`: no pipe-to-shell; official Docker apt repo with signed key; requires `--confirm`; idempotent; no password auth changes that could lock Rehaan out without warning; UFW rule order does not cut an active SSH session.
- `deploy.sh`: uses image digests, not mutable tags; verifies digest; decrypts to tmpfs with mode 600 and removes on exit; smoke test then rollback; never prints env contents; exits non-zero on any failure (`set -euo pipefail`).
- Compose: `read_only: true`, `cap_drop: [ALL]`, `security_opt: [no-new-privileges:true]`, non-root `user`, memory limits, `restart: unless-stopped`, no `privileged`, no host network, no Docker socket mounted into any container.
- Backups: encrypted before upload; retention; restore test destroys its container; no plaintext dump left on disk.

**M6 Cloudflare Terraform**
- Provider pinned `~> 5.x` minor; backend in R2; no secrets in `.tf` or `.tfvars` committed.
- No resources for existing MX, SPF, DKIM, DMARC or verification TXT records.
- `prevent_destroy` on tunnel hostnames and the backups bucket.
- Access policies allow only Rehaan's email; session duration set; no "bypass" or "everyone" rules.
- Tunnel ingress ends with a catch-all `http_status:404`.

### 3.3 G6 burn-in summary review
Rehaan sends: `/ops/status` JSON at start and end, count of `integration_log` rows by status and source, Better Stack incident list, `docker ps` restart counts, deploy history row. Claude checks for silent failures (heartbeats green while error rows grow), unexplained restarts, and write counts that exceed expected volumes.

### 3.4 Terraform plan review
Rehaan runs `terraform plan -out plan.tfplan && terraform show -no-color plan.tfplan > plan.txt` and sends `plan.txt` (it contains no secret values when variables are marked `sensitive`). Claude fails the plan if it contains: any `destroy` or `replace` not explicitly expected; changes to DNS records not created by Terraform; Access policy includes beyond Rehaan's email; public hostnames other than those in the plan; WAF rules that disable security features.

---

## 4. Verdict format (Claude's reply)

```
G3 VERDICT: PASS | PASS WITH NOTES | FAIL
Milestone: <id>   Bundle: <file>   Head: <sha>

Blocking findings (must fix before merge):
1. [B7] src/tis/jobs/lead_sync.py:88 upsert_lead called without @external_write. Fix: ...

Non-blocking notes:
1. ...

Checks confirmed:
B1 ✓ B2 ✓ B3 ✓ ... plus milestone checks: ...

Tests Rehaan should run at G4/G5:
1. ...
```

PASS WITH NOTES allows merge; notes become tasks in `PROGRESS.md`.

---

## 5. Prompt to send Claude

```
Role: verifier for the torus-integrations repo. Use docs/VERIFICATION.md (baseline checks B1 to B12 and the milestone checklist) and the Torus Mesh master plan in this project. Review only the attached evidence bundle.

Milestone: <id>. Gate: G3 (or: Terraform plan review / G6 burn-in / incident).
Be strict on secrets, egress, external writes, protected files, dependencies and deploy scripts. Do not rewrite the code; list findings with file and line, why it matters, and the minimal fix.
Reply in the verdict format from Part 4.
```
