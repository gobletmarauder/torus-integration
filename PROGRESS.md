# PROGRESS.md: Torus Integration Service

Updated by Codex on every task and by Rehaan at every gate. Newest entries at the top of each section. Dates in YYYY-MM-DD, times UTC.

**Current milestone:** M0 · **Current gate:** G2 · **Production version:** none · **DRY_RUN in prod:** n/a · **Kill switch:** n/a

---

## 1. Gate board

| Milestone | G0 Plan | G1 Local | G2 CI | G3 Claude | G4 Dry run | G5 Live | G6 Burn-in | Bundle / PR |
|---|---|---|---|---|---|---|---|---|
| M0 Repo bootstrap | ☑ | ☑ | ☐ | ☐ | n/a | n/a | n/a | pending PR |
| M1 Core library | ☐ | ☐ | ☐ | ☐ | n/a | n/a | n/a | |
| M2 Lead sync | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | |
| M3 Booking sync | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | |
| M4 Packaging | ☐ | ☐ | ☐ | ☐ | ☐ | n/a | n/a | |
| M5 Deploy tooling | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | |
| M6 Cloudflare IaC | ☐ | ☐ | ☐ | ☐ | plan reviewed ☐ | applied ☐ | n/a | |
| M7 Cutover | n/a | n/a | n/a | ☐ | ☐ | ☐ | ☐ | |

Legend: ☐ not started · ◐ in progress · ☑ passed · ✖ failed (see incidents)

---

## 2. Milestone log

### M0. Repo bootstrap and guardrails

**Tasks**

| Task | Status | PR | Notes |
|---|---|---|---|
| M0.1 Layout, pyproject, tooling | ☑ | pending | Python 3.12 skeleton, exact dev pins, lockfile, Dockerfile, and placeholder directories added. |
| M0.2 Makefile | ☑ | pending | setup, lint, type, test, guard, audit, license, check, build, verify-bundle, and Terraform validation targets added. |
| M0.3 guard.py | ☑ | pending | Static policy checks implemented; 27 unit tests include isolated planted violations. |
| M0.4 verify_bundle.sh | ☑ | pending | Fifteen-section, size-splitting, post-generation secret-scanned bundle generator added. |
| M0.5 CI and release workflows | ☑ | pending | SHA-pinned CI/release workflows added with least privilege, scan-before-push, SBOM, and conditional Terraform validation. |
| M0.6 CODEOWNERS, PR template | ☑ | pending | Ownership and required evidence/security/deviation prompts added. |
| M0.7 .env.example, .sops.yaml | ☑ | pending | Setting names are documented without values; SOPS policy is a non-key placeholder. |
| M0.8 PROGRESS.md initialized | ☑ | pending | M0 status, G1 evidence, decisions, open questions, and protected hashes recorded. |

**G0 plan**

### M0 G0 plan (2026-09-17)

Scope: M0.1, M0.2, M0.3, M0.4, M0.5, M0.6, M0.7, M0.8. Bootstrap the Python 3.12 repository and package skeleton, deterministic uv tooling, local check targets, static policy guard, verification-bundle generator, CI/release workflows, ownership/review metadata, configuration-name examples, and progress tracking. This plan is the only M0 change before approval; implementation stops until Rehaan comments `G0 approved`.

Files to create/modify: create `.dockerignore`, `.env.example`, `.gitignore`, `.sops.yaml`, `Dockerfile`, `Makefile`, `pyproject.toml`, `uv.lock`, `src/tis/__init__.py`, `src/tis/api/__init__.py`, `src/tis/integrations/__init__.py`, `src/tis/jobs/__init__.py`, `src/tis/mapping/__init__.py`, `tests/unit/test_guard.py`, `tests/contract/.gitkeep`, `tests/fixtures/.gitkeep`, `scripts/guard.py`, `scripts/verify_bundle.sh`, `docs/dependencies.md`, `docs/sql/.gitkeep`, `docs/runbooks/.gitkeep`, `docs/bundles/.gitignore`, `.github/CODEOWNERS`, `.github/pull_request_template.md`, `.github/workflows/ci.yml`, and `.github/workflows/release.yml`; modify `PROGRESS.md` only for the G0 plan now and, after approval during M0 implementation, task/gate evidence and protected-file hashes. No files under `deploy/`, `infra/`, or `secrets/` will be created in M0 because their executable contents belong to later milestones.

Protected paths touched: yes (`.sops.yaml`, `scripts/guard.py`, `scripts/verify_bundle.sh`, `.github/CODEOWNERS`, `.github/pull_request_template.md`, `.github/workflows/ci.yml`, `.github/workflows/release.yml`). The implementation PR must carry `protected-change`; `AGENTS.md`, `deploy/**`, `infra/**`, `secrets/**`, `src/tis/http.py`, and `src/tis/guards.py` will not change.

New dependencies: direct development dependencies only, all exact pins in `pyproject.toml` and `uv.lock`: `ruff==0.16.8` (MIT; lint and format), `mypy==2.1.0` (MIT; strict type checking for `src/tis`), `pytest==9.0.3` (MIT; tests), `pytest-cov==7.1.0` (MIT; coverage reporting and thresholds), `pip-audit==2.10.1` (Apache-2.0; Python dependency vulnerability audit), and `pip-licenses==5.5.5` (MIT; dependency-license inventory and GPL/AGPL runtime rejection). There are no runtime dependencies and no build-backend dependency; M0 configures a non-packaged uv project and imports `src/` through test/tool configuration. `docs/dependencies.md` will record version, license, purpose, and alternatives for every direct dependency. The non-Python tools uv, gitleaks, Docker/Buildx, Trivy, and Terraform are CI/developer executables, not project dependencies, and will be version-pinned where invoked.

New egress hosts: none. M0 adds no service HTTP client, allowlist entry, or runtime network behavior. GitHub-hosted setup/build/security jobs may access their normal package, action, vulnerability-database, and GHCR endpoints; those are build infrastructure, not service egress.

New scopes/privileges: GitHub Actions default and CI permissions are `contents: read`; no `pull_request_target` trigger is allowed. The tag-only `release.yml` job narrows its permissions to `contents: read` and `packages: write` solely to publish `ghcr.io/<owner>/tis:<tag>` with the built-in `GITHUB_TOKEN`. No OAuth scopes, database grants, cloud roles, repository secrets, or production credentials are added.

External writes added: GitHub Container Registry, tag-triggered image publish by `release.yml`; idempotency key is the immutable Git tag plus source commit/image digest, and the workflow publishes only `ghcr.io/<owner>/tis:<tag>` (no `latest` tag). Budget is one image manifest per matching `v*` tag workflow run; reruns may replace only that same tag with the same source-derived image, and the resulting digest is printed. This is CI packaging rather than a service write, so `@external_write` does not apply. No Zoho, PostHog, Google, Stripe, R2, Supabase, Cloudflare, or home-server writes are added.

Tests: unit tests in `tests/unit/test_guard.py` will create isolated `tmp_path` repositories and invoke `scripts/guard.py` with an explicit root/base so each rule is exercised without real network or production data. The safe synthetic tree must exit zero. Separate planted cases must exit non-zero and identify file/rule for: forbidden direct imports (`requests`, `urllib.request`, `http.client`, `aiohttp`, and `socket`) outside `src/tis/http.py`; `subprocess` with `shell=True`; `eval` and `exec`; `pickle.loads`; encoded/base64-like blobs longer than 200 characters; hardcoded HTTP(S) URLs in executable source whose host is not allowlisted; SQL containing `DROP`, `TRUNCATE`, `ALTER`, `GRANT`, `REVOKE`, `CREATE ROLE`, or `DELETE`; and `print(` in `src/`. Test violation strings will be assembled at runtime before being written to the temporary tree so the guard does not flag its own test fixtures. A temporary git history will prove that a dependency change in `pyproject.toml` fails when `docs/dependencies.md` is unchanged and passes when both change. A planted protected-path change will prove the guard reports the complete protected-file list but does not fail solely for that report. Workflow fixtures will also prove that a mutable/non-SHA `uses:` reference and `pull_request_target` fail, while full 40-character action SHAs and least-privilege permissions pass. Contract tests are not applicable because M0 performs no service I/O; `make check` will prove ruff, format check, strict mypy, pytest/coverage, guard, gitleaks, pip-audit, license policy, and the empty-service Docker build locally, while G2 repeats those checks and adds Trivy, SBOM, and conditional Terraform format/validate checks.

`scripts/guard.py` checks: parse Python with `ast` where possible and use narrowly scoped text checks for non-Python files; fail with stable rule id, path, and line for forbidden network imports outside `src/tis/http.py`; `subprocess` calls with `shell=True`; calls to `eval`/`exec`; `pickle.loads`; encoded blobs over 200 characters; non-allowlisted hardcoded HTTP(S) URLs in executable source/config; prohibited SQL tokens (`DROP`, `TRUNCATE`, `ALTER`, `GRANT`, `REVOKE`, `CREATE ROLE`, `DELETE`); and `print(` under `src/`. It also compares the requested base-to-head git diff and fails when project dependencies change without a matching `docs/dependencies.md` change, rejects workflow `pull_request_target`, and rejects any action `uses:` value not pinned to a full 40-character commit SHA. It reports, but does not fail solely because of, every changed protected path. Generated caches, `.git`, `.venv`, `uv.lock`, the gitignored bundle directory, and synthetic fixture data are excluded only where scanning them would create false positives; tests and executable scripts otherwise remain in scope. Output is deterministic, contains no file contents or secret values, and returns non-zero if any failing rule is found.

GitHub Actions pinned by commit SHA: both workflows will use only `actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1` (`v7.0.1`), `actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97` (`v7.0.0`), `astral-sh/setup-uv@bec219d24cd3e171d82865faccec33120bb574f4` (`v10.1.0`), `docker/setup-buildx-action@f87e5991a6d7451dcb8d9637bfbc97413f497069` (`v4.4.1`), `docker/build-push-action@c3c9e263c25d99ce0380d002d59b67737d91b0dc` (`v7.4.0`), and `aquasecurity/trivy-action@ed142fd0673e97e23eac54620cfb913e5ce36c25` (`v0.36.0`). CI artifact publication will additionally use `actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a` (`v7.0.1`), and infra-change validation will use `hashicorp/setup-terraform@dfe3c3f87815947d99a8997f908cb6525fc44e9e` (`v4.0.1`) without running `terraform plan`. Release authentication will additionally use `docker/login-action@dbcb813823bdd20940b903addbd779551569679f` (`v4.6.0`). Trivy will scan the locally built image for fixable HIGH/CRITICAL findings and generate the CycloneDX SBOM uploaded by `upload-artifact`; release will scan before login/push so a failing image is never published.

`scripts/verify_bundle.sh` output: write only gitignored `docs/bundles/<MILESTONE>-<shortsha>.md` (or deterministic `-part1`, `-part2`, etc. files when the bundle would exceed approximately 40 KB), then run gitleaks against the generated output and delete/abort on any finding. In the exact `docs/VERIFICATION.md` order it will contain: (1) header with milestone, branch, base/head commits, UTC date, task ids; (2) verbatim G0 plan; (3) name-status scope table with `in plan: yes/no`; (4) changed protected paths, hashes of all protected files, and full changed-protected diffs; (5) `pyproject.toml` diff, summarized `uv.lock` package/version changes, `docs/dependencies.md` diff, and new-package licenses; (6) `src/tis/http.py` allowlist diff; (7) grep results for OAuth scopes, `ENV`/`DRY_RUN` defaults, budgets, and SQL; (8) `@external_write` inventory and non-GET `http.client()` calls lacking the decorator; (9) full guard output; (10) ruff, mypy, pytest counts/package coverage, gitleaks, pip-audit, license, Docker, and Trivy summaries; (11) added/changed test names plus any skips, xfails, or deletions; (12) required source diffs with the 400-line fallback; (13) Terraform fmt/validate output when infra changed; (14) previous M0 verdict and diff since its head, if present; and (15) PR Security notes, Open questions, and Deviations from plan. Missing tools, dirty/unresolvable base state, out-of-plan files, or failed checks are represented as explicit failures rather than silently omitted. The script never emits environment values, secrets, raw payloads, or real personal data.

Rollback: before merge, revert the M0 implementation commit(s) on the feature branch or close the PR; after merge, create a normal revert PR for the M0 commits. No migrations, production deployment, external-system records, or mutable infrastructure are involved. If a release test tag published an image, leave the immutable digest for audit and remove only the tag/package version through GitHub’s reviewed UI if Rehaan explicitly chooses to do so.

Open questions: none. The repository stores the master plan as `docs/torus-mesh-MASTER-PLAN.md`, not the `docs/MASTER-PLAN.md` path named by the task; this plan used the former because it contains the requested Parts 2–5 and M0 definition. The `<owner>` portion of the GHCR name will be derived from `github.repository_owner`, so no owner value is hardcoded.

**G1 evidence**

```
Command: make check
Date: 2026-09-17 UTC
Result: PASS
- ruff check: passed
- ruff format --check: 15 files already formatted
- mypy src/tis: success, no issues in 5 source files
- pytest: 27 passed; 100% bootstrap source coverage; required 85% reached
- scripts/guard.py: passed; 7 protected changes reported
- pip-audit: no known vulnerabilities
- pip-licenses: passed the GPL/AGPL rejection policy
- gitleaks detect --no-git: no leaks in 257.86 KB of repository content
- docker build --tag tis:m0-local .: passed
```

**G3 verdict (Claude)**

G3 VERDICT: PASS WITH NOTES
Milestone: M0   Bundle: M0-cad58e01-part1.md, M0-cad58e01-part2.md   Head: cad58e01

Blocking before merge:
1. G2: CI must be green on GitHub for this PR (bundle only shows local checks).
2. CODEOWNERS uses @rehaan; confirm that is the exact GitHub handle, otherwise ownership rules silently do nothing.

Required before M1 starts (task M0.9, protected-change):
1. [B-integrity] scripts/verify_bundle.sh section 15 prints a hardcoded "no security issues" note instead of Codex's real PR notes. Read notes from docs/pr-notes/<MILESTONE>.md and fail if the file is missing.
2. [B-integrity] verify_bundle.sh hardcodes M0 (task ids, "### M0 G0 plan" heading, image tag tis:m0-local) and reads the first G3 verdict in PROGRESS.md regardless of milestone. Parameterize by milestone.
3. [B1] Scope check marks a file "in plan" if its path appears anywhere in PROGRESS.md. Limit the search to the current milestone's G0 plan text.
4. [B10/B11] Bundle omits non-src changes (Dockerfile, Makefile, pyproject.toml, .env.example, .gitignore, .dockerignore, tests/**). Include their diffs (400-line cap each). Dockerfile and tests were not reviewable in this bundle.
5. [B5] guard.py forbidden imports omit httpx (the planned HTTP client), urllib3, websockets, smtplib, ftplib. Add them. Also flag importlib.import_module / __import__, attribute calls to eval/exec, and any shell= value that is not the constant False.
6. [B11] ci.yml terraform job uses hashFiles() in a job-level if, which runs before checkout; the job will never run. Move the condition to a step after checkout or use a paths filter.
7. [B11] release.yml builds the image twice: Trivy scans one build, then build-push-action publishes a new build. Split into a build-and-scan job (contents: read) and a publish job (packages: write) that pushes the exact scanned image. This also keeps packages: write away from dependency installs and tests.

Non-blocking notes:
1. Rename docs/torus-mesh-MASTER-PLAN.md to docs/MASTER-PLAN.md (and the other prefixed docs) so AGENTS.md references resolve.
2. Bundle size: drop the duplicate license listing and exclude docs/** and *.md from the section 7 grep.
3. Split bundle parts on line boundaries instead of byte counts.
4. The run shows Docker pulls from a Windows machine; if Codex CLI ran these, it had network access. Approving network use per session is fine; keep full-access mode off.

Checks confirmed: B2 no secrets (gitleaks clean) · B3 protected files listed with hashes · B4 dev dependencies exact-pinned, licenses clean, docs/dependencies.md present, no runtime deps · B6 no unsafe execution · B7/B8 no external writes or SQL · B10 27 tests pass, no skips · B11 actions pinned by SHA, default contents: read, no pull_request_target · image 57 MB, Trivy 0 fixable HIGH/CRITICAL.

---

### M1. Core library

(same structure: tasks table, G0 plan, G1 evidence, G3 verdict, decisions, deferred)

### M2. Lead sync

(same structure, plus:)

**G4 dry run (Rehaan)**

```
Tag/digest:
Start/end (UTC):
integration_log skipped rows:
Errors:
Heartbeats:
```

**G5 live enable (Rehaan)**

| Test | Result | Evidence |
|---|---|---|
| T3 Lead happy path | ☐ | |
| T4 Existing Contact | ☐ | |
| T5 Turnstile failure | ☐ | |
| T6 Zoho outage recovery | ☐ | |
| T7 Honeypot | ☐ | |
| T13 Admin resync (RPC) | ☐ | |
| Kill switch from admin | ☐ | |

**G6 burn-in (24 h)**

```
Window:
Unsynced > 30 min:
Error rows:
Restarts:
Verdict:
```

### M3. Booking sync

(same structure as M2; G5 tests T8, T9, T10)

### M4. Service packaging
### M5. Deployment tooling
(G5: deploy, forced smoke failure with automatic rollback, backup, restore test)
### M6. Cloudflare infrastructure
(G4 replaced by: plan.txt reviewed by Claude; G5 replaced by: apply output and post-apply checks)
### M7. Production cutover

---

## 3. Open questions

| # | Question | Raised by | Date | Answer | Answered by |
|---|---|---|---|---|---|
| | | | | | |

## 4. Decisions log

| Date | Decision | Why | Source (PR/plan) |
|---|---|---|---|
| 2026-09-16 | Integration layer on home server in Docker Compose; website stays on Cloudflare | Master plan A1, A2 | MASTER-PLAN |
| 2026-09-16 | Secrets via SOPS + age; age key only on server and password manager | A6 | MASTER-PLAN |
| 2026-09-16 | Pull-based, human-triggered deploys by digest with automatic rollback | A8 | MASTER-PLAN |

## 5. Incidents and stop conditions

| Date | What happened | Impact | Actions (revert, rotate, fix) | Follow-up |
|---|---|---|---|---|
| | | | | |

## 6. Deploy history (Rehaan)

| Date (UTC) | Tag | Digest (short) | DRY_RUN | Smoke | Rolled back? | Notes |
|---|---|---|---|---|---|---|
| | | | | | | |

## 7. Protected-file hashes (updated by verify_bundle)

| File | SHA-256 (first 16) | Changed in |
|---|---|---|
| AGENTS.md | e2e0a98b4f84016c | unchanged in M0 |
| scripts/guard.py | 74f3461961dcef20 | M0 |
| scripts/verify_bundle.sh | 0f1ffb56d63dc63b | M0 |
| src/tis/http.py | not present | deferred to M1 |
| src/tis/guards.py | not present | deferred to M1 |
| .github/workflows/ci.yml | 3eac93db15d9252a | M0 |
| deploy/deploy.sh | not present | deferred to M5 |
