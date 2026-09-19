# PROGRESS.md: Torus Integration Service

Updated by Codex on every task and by Rehaan at every gate. Newest entries at the top of each section. Dates in YYYY-MM-DD, times UTC.

**Current milestone:** M6 · **Current gate:** G2 CI pending · **Production version:** none · **DRY_RUN in prod:** n/a · **Kill switch:** n/a

---

## 1. Gate board

| Milestone | G0 Plan | G1 Local | G2 CI | G3 Claude | G4 Dry run | G5 Live | G6 Burn-in | Bundle / PR |
|---|---|---|---|---|---|---|---|---|
| M0 Repo bootstrap | ☑ | ☑ | ☑ | ☑ | n/a | n/a | n/a | PR #1 merged; M0.9 follow-up in PR #2 |
| M1 Core library | ☑ | ☑ | ☑ | ☑ | n/a | n/a | n/a | PR #3 merged; G3 PASS at `45a022b4` |
| M2 Lead sync | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | |
| M3 Booking sync | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | |
| M4 Packaging | ☐ | ☐ | ☐ | ☐ | ☐ | n/a | n/a | |
| M5 Deploy tooling | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | |
| M6 Cloudflare IaC | ☑ | ☑ | ◐ | ☐ | plan reviewed ☐ | applied ☐ | n/a | PR #4; local G1 green |
| M7 Cutover | n/a | n/a | n/a | ☐ | ☐ | ☐ | ☐ | |

Legend: ☐ not started · ◐ in progress · ☑ passed · ✖ failed (see incidents)

---

## 2. Milestone log

### M0. Repo bootstrap and guardrails

**Tasks**

| Task | Status | PR | Notes |
|---|---|---|---|
| M0.1 Layout, pyproject, tooling | ☑ | #1 merged | Python 3.12 skeleton, exact dev pins, lockfile, Dockerfile, and placeholder directories added. |
| M0.2 Makefile | ☑ | #1 merged | setup, lint, type, test, guard, audit, license, check, build, verify-bundle, and Terraform validation targets added. |
| M0.3 guard.py | ☑ | #1 merged | Static policy checks implemented; 27 unit tests include isolated planted violations. |
| M0.4 verify_bundle.sh | ☑ | #1 merged | Fifteen-section, size-splitting, post-generation secret-scanned bundle generator added. |
| M0.5 CI and release workflows | ☑ | #1 merged | SHA-pinned CI/release workflows added with least privilege, scan-before-push, SBOM, and conditional Terraform validation. |
| M0.6 CODEOWNERS, PR template | ☑ | #1 merged | Ownership and required evidence/security/deviation prompts added. |
| M0.7 .env.example, .sops.yaml | ☑ | #1 merged | Setting names are documented without values; SOPS policy is a non-key placeholder. |
| M0.8 PROGRESS.md initialized | ☑ | #1 merged | M0 status, G1 evidence, decisions, open questions, and protected hashes recorded. |
| M0.9 Verification and workflow integrity fixes | ☑ | #2 merged | G3 PASS accepted from PR diff and green CI because local Docker was unavailable; all seven required findings resolved. |

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

Open questions: none. The master plan is now stored at the canonical `docs/MASTER-PLAN.md` path. The `<owner>` portion of the GHCR name is derived from `github.repository_owner`, so no owner value is hardcoded.

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

### M0.9 G0 plan (2026-09-18)

Scope: M0.9. Resolve every M0 G3 item marked “Required before M1 starts,” plus the directly related non-blocking verification-bundle and documentation-path hygiene items. This is a plan-only change; implementation stops until Rehaan comments `G0 approved` on the draft PR.

Files to create/modify: create `docs/pr-notes/M0.9.md`, `tests/unit/test_verify_bundle.py`, and `tests/unit/test_repository_configuration.py`; modify `Makefile`, `scripts/guard.py`, `scripts/verify_bundle.sh`, `tests/unit/test_guard.py`, `.github/workflows/ci.yml`, `.github/workflows/release.yml`, and `PROGRESS.md`; rename `docs/torus-mesh-MASTER-PLAN.md` to `docs/MASTER-PLAN.md`, `docs/torus-mesh-HOME-SERVER-HOSTING.md` to `docs/HOSTING.md`, and `docs/torus-mesh-CLOUDFLARE-SETUP.md` to `docs/CLOUDFLARE.md`, updating repository-relative references in the renamed documents and `docs/INFRA-EXECUTION.md`. No application source, infrastructure, deployment, secret, or SOPS files will change.

Protected paths touched: yes (`scripts/guard.py`, `scripts/verify_bundle.sh`, `.github/workflows/ci.yml`, `.github/workflows/release.yml`). The implementation PR must carry `protected-change`. `AGENTS.md`, `.sops.yaml`, `deploy/**`, `infra/**`, `secrets/**`, `src/tis/http.py`, and `src/tis/guards.py` will not change.

New dependencies: none. No Python/runtime/development dependency or lockfile change is planned. Release artifact transfer will add the first-party action `actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c` (`v8.0.1`) pinned to its full commit SHA; the existing pinned `actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a` (`v7.0.1`) will upload the exact scanned image archive and its CycloneDX SBOM.

New egress hosts: none. Service runtime egress remains empty. GitHub Actions artifact storage, GHCR, and the existing package/vulnerability-database endpoints are build infrastructure already within M0’s approved CI/release behavior.

New scopes/privileges: no broadened scope. CI remains `contents: read`. `release.yml` will default to `contents: read`; its build-and-scan job will have read-only permissions, and only the publish job will add `packages: write`. The publish job will not check out source, install dependencies, run tests, or rebuild the image.

External writes added: GitHub Actions artifact storage will receive one scanned Docker image archive and one CycloneDX SBOM per tag workflow run, keyed by workflow run/source commit with normal artifact retention; these are immutable handoff evidence between the read-only build job and the publish job. GHCR publication is not new: it remains one tag-specific image manifest per `v*` run, keyed by tag and source commit/image digest, but the publish job will load and push the exact previously scanned archive rather than rebuild it. No service external writes are added, so `@external_write` does not apply.

Tests: extend `tests/unit/test_guard.py` with isolated planted violations proving `httpx`, `urllib3`, `websockets`, `smtplib`, and `ftplib` imports fail outside `src/tis/http.py`; `importlib.import_module` and `__import__` fail; name and attribute forms of `eval`/`exec` fail; and every `subprocess` `shell=` value except the literal constant `False` fails. Preserve positive cases for the allowed HTTP module and `shell=False`. Add `tests/unit/test_verify_bundle.py` using synthetic temporary git repositories and fake command shims so no network or real Docker call occurs; prove milestone-specific G0/task/verdict extraction, scope checks restricted to that plan block, required `docs/pr-notes/<MILESTONE>.md` failure/success behavior, configurable image selection, inclusion of every changed reviewable non-bundle file with an explicit 400-line-per-file truncation marker, exclusion of docs/Markdown from the section 7 grep, removal of the duplicate license inventory, and line-boundary bundle splitting. Add `tests/unit/test_repository_configuration.py` to prove the Terraform presence check runs only after checkout, action references remain full-SHA pinned, release build/scan has read-only permissions, only publish has `packages: write`, and publish downloads/loads/pushes the artifact without rebuilding. `make check` must remain green and the M0.9 bundle must contain all 15 sections and pass its post-generation gitleaks scan.

Implementation details: `scripts/verify_bundle.sh` will derive the selected milestone’s task ids, G0 plan, and previous G3 verdict from that milestone’s bounded section in `PROGRESS.md`; use only the extracted G0 text for scope membership; accept the image through the existing `IMAGE` make variable with a milestone-neutral default; fail when `docs/pr-notes/<MILESTONE>.md` is absent; copy that file verbatim into section 15; enumerate changed reviewable files in section 12 (including Dockerfile, Makefile, project configuration, dotfiles, and tests) with a 400-line cap and explicit truncation; and split oversized bundles on complete line boundaries. CI will detect Terraform files in a post-checkout step and conditionally run setup/fmt/validate steps. Release will build and scan once, save that tagged image, create a CycloneDX SBOM, transfer both artifacts, then load and push that exact image in the narrowly privileged publish job and print the pushed digest.

Rollback: before merge, revert the M0.9 implementation commits or close the PR. After merge, use a normal revert PR. The changes affect repository validation and CI/release mechanics only; no production deploy, schema, Cloudflare resource, home server, or service record is changed. A failed tag run may leave only a GitHub Actions artifact; no GHCR image is pushed unless the scan and artifact handoff succeed.

Open questions: none. M1 must wait until M0.9 completes G0-G3 and Rehaan merges it. Per the master plan’s one-milestone-at-a-time rule, M1 will receive its own G0 plan next; M6 will receive a separate G0 plan only after the preceding milestone is complete. Terraform plan/apply remain prohibited during code milestones.

**M0.9 G1 evidence (incomplete)**

```
Command: make check
Date: 2026-09-18 UTC
Result: BLOCKED by the local Docker Desktop installation; G1 is not marked passed.
- ruff check: passed
- ruff format --check: 19 files already formatted
- mypy src/tis: success, no issues in 5 source files
- pytest: 57 passed; 100% bootstrap source coverage; required 85% reached
- scripts/guard.py: passed; 4 protected changes reported
- pip-audit: no known vulnerabilities
- pip-licenses: passed the GPL/AGPL rejection policy
- local gitleaks/Docker build: not run because Docker Desktop 4.54.0 crashes while initializing its dockerInference socket
- hosted CI run 35395117127 at head 649a26e: passed both jobs; make check, real Docker build, gitleaks, Trivy, and CycloneDX SBOM all passed
- make verify-bundle MILESTONE=M0.9: started successfully after the portable Makefile fix, then was interrupted after the unavailable Docker engine left its first Docker call blocked; no M0.9 bundle was emitted
```
G3 VERDICT: PASS (M0.9)
Bundle: not generated (local Docker down); verified from PR #2 diff + green CI at c4de8de.
All 7 required M0.9 items confirmed. No secrets, no production writes. Merge approved.

**M0.9 decisions made**

- Canonicalized the three planning/hosting/Cloudflare document names so the binding repository paths resolve directly.
- Kept verification parsing in sourceable shell helpers, allowing synthetic repositories and fake command shims to test milestone bounds, scope membership, notes, configurable images, diff truncation, and line-safe splitting without network access.
- Release builds and scans once under read-only permissions, transfers the exact image archive and SBOM as an Actions artifact, and grants `packages: write` only to the load-and-push job.

**M0.9 open questions / blocker**

No implementation questions. Local G1 and `make verify-bundle MILESTONE=M0.9` require a working Docker engine. Docker Desktop currently crashes before its engine starts because Windows reports its generated `dockerInference` socket as inaccessible; backend and WSL restarts did not clear it. A Docker Desktop repair or Windows restart is required before those mandatory local commands can complete. M1 remains blocked.

---

### M1. Core library

**Tasks**

| Task | Status | PR | Notes |
|---|---|---|---|
| M1.1 Configuration and safe defaults | ☑ | #3 | Exact runtime pins, typed environment settings, safe dry-run invariant, job flags, and positive budgets implemented. |
| M1.2 Controlled HTTP client | ☑ | #3 | Exact two-host allowlist, redirect revalidation, ten-second timeout, and bounded idempotent retry implemented. |
| M1.3 Structured redacted logging | ☑ | #3 | JSON logging, correlation ids, and recursive secret/PII redaction implemented and tested. |
| M1.4 Async database pool and helpers | ☑ | #3 | Lazy Psycopg async pool, transaction rollback, fixed parameterized queries, and ten-second statement timeout implemented. |
| M1.5 Integration state and kill switch | ☑ | #3 | Authoritative JSON state contract, UTC last-run values, and 15-second kill-switch cache implemented. |
| M1.6 External-write guard | ☑ | #3 | Dry run, kill switch, atomic idempotency claim, audit statuses, and per-run/per-day budgets implemented. |
| M1.7 Better Stack and PostHog helpers | ☑ | #3 | Pydantic outgoing payloads and guarded heartbeat/capture helpers implemented with synthetic-only tests. |

### M1 — G3 Verification: PASS
Reviewer: Claude (Opus) — verification-only
Commit verified: 45a022b4 (CI green at c4de8de/head)
Bundle: sections=15 checks=PASS guard=PASS gitleaks=PASS trivy=PASS protected_changes=3
Tests: 90 passed / 90.12% coverage

Findings:
- Egress allowlist correct and enforced on initial + redirect requests (http.py only)
- Guard NET003/NET004 enforce runtime↔guard allowlist parity; httpx confined to http.py
- External writes limited to betterstack heartbeat + posthog capture, both guarded
- DRY_RUN-safe (skipped, zero HTTP); kill switch, budgets, idempotency on (source, external_id, action)
- SQL parameterized; PII redaction covers emails/phones/sensitive keys
- No secrets; gitleaks + trivy clean

Verdict: PASS. Cleared to merge PR #3.
Next: M6 (Terraform, infra execution session), then M2 (Zoho lead sync).

### M1 G0 plan (2026-09-18)

Scope: M1.1, M1.2, M1.3, M1.4, M1.5, M1.6, and M1.7. Build the typed configuration, controlled HTTP, structured logging, async database, state/kill-switch, external-write guard, Better Stack heartbeat, and PostHog capture foundations required by later jobs. This is a plan-only change; implementation stops until Rehaan comments `G0 approved` on the draft PR.

Files to create/modify: create `src/tis/config.py`, `src/tis/errors.py`, `src/tis/http.py`, `src/tis/log.py`, `src/tis/db.py`, `src/tis/state.py`, `src/tis/guards.py`, `src/tis/integrations/betterstack.py`, `src/tis/integrations/posthog.py`, `tests/conftest.py`, `tests/unit/test_config.py`, `tests/unit/test_http.py`, `tests/unit/test_log.py`, `tests/unit/test_db.py`, `tests/unit/test_state.py`, `tests/unit/test_guards.py`, `tests/unit/test_betterstack.py`, `tests/unit/test_posthog.py`, `docs/runbooks/core-library.md`, and `docs/pr-notes/M1.md`; modify `pyproject.toml`, `uv.lock`, `.env.example`, `docs/dependencies.md`, `scripts/guard.py`, `tests/unit/test_guard.py`, and `PROGRESS.md`. No workflow, deployment, infrastructure, secret, SOPS, API, mapping, scheduler, or job files will change.

Protected paths touched: yes (`src/tis/http.py`, `src/tis/guards.py`, and `scripts/guard.py`). The implementation PR must carry `protected-change`. `AGENTS.md`, `.github/**`, `deploy/**`, `infra/**`, `.sops.yaml`, `secrets/**`, and `scripts/verify_bundle.sh` will not change.

New dependencies: runtime dependencies will be exact-pinned as `pydantic==2.13.5` (MIT; explicit external-payload and configuration models; relying on an unpinned transitive install was rejected because every runtime dependency must be reviewable), `pydantic-settings==2.15.0` (MIT; typed environment configuration; a hand-written environment parser was rejected because it would duplicate validation and error reporting), `httpx==0.28.1` (BSD-3-Clause; the required async HTTP client; aiohttp and requests are disallowed by repository policy), `psycopg==3.3.6` (LGPL-3.0-only; required Psycopg 3 async database interface; asyncpg was rejected because the master plan specifies Psycopg and its pool), `psycopg-binary==3.3.6` (LGPL-3.0-only; deterministic prebuilt libpq implementation for CI/runtime; a source build was rejected because the final image must not contain compilers), and `psycopg-pool==3.3.2` (LGPL-3.0-only; async connection pooling; a custom pool was rejected as unsafe concurrency infrastructure). The exact-pinned test dependency will be `respx==0.23.1` (BSD-3-Clause; blocks and asserts HTTPX calls in tests; hand-written transports alone were rejected because request routing and no-unexpected-network assertions would be weaker). `docs/dependencies.md` and `uv.lock` will record every direct pin and the resolved transitive graph. No GPL or AGPL dependency will be added.

New egress hosts: exactly `us.i.posthog.com` for server-side PostHog capture and `uptime.betterstack.com` for heartbeat delivery, with no schemes, paths, ports, wildcards, suffix matching, or additional hosts. `src/tis/http.py` will enforce those two normalized hostnames on the initial request and every redirect. `scripts/guard.py` will retain `httpx` as a forbidden import everywhere except `src/tis/http.py`, mirror the two-host allowlist only for that protected module, and fail when the runtime and guard allowlists drift or when another module imports `httpx` or hardcodes either service URL. The current baseline has no `httpx` import under `src/tis`; only the planted guard fixtures mention it. Tests will use reserved synthetic hosts and `respx`; they will make no real network calls. No Supabase REST, Zoho, Google, Turnstile, Cloudflare API, LinkedIn, or other HTTP host will be added.

New scopes/privileges: none. No OAuth scope, GitHub permission, database role, RLS policy, schema privilege, Cloudflare token permission, or host capability changes are included. Database access remains through the configured `tis_service` DSN and is limited in code to parameterized helper statements for `integration_log` and `integration_state`; no migration or schema SQL will be executed.

External writes added: (1) PostHog event capture through `@external_write(source="posthog", action="capture", key=...)`; the idempotency key is the stable event name plus caller-provided external id, falling back only to the per-run correlation id for run-level events, with budgets of 25 events per run and 200 per UTC day. (2) Better Stack heartbeat delivery through `@external_write(source="betterstack", action="heartbeat", key=...)`; the idempotency key is job/monitor name plus run correlation id, with budgets of 10 heartbeats per run and 400 per UTC day so the later five-minute health schedule can operate without bypassing a budget. Both helpers use only `tis.http`, honor kill switch and dry run, and write `skipped` audit rows without making HTTP calls when blocked. The decorator’s own bounded, parameterized `integration_log` idempotency/audit upserts and `integration_state` control writes are internal safety-state operations and cannot recursively decorate themselves; tests will constrain them to those two tables and prove rollback on failure.

Tests: configuration tests will prove `DRY_RUN` defaults to `true`, cannot become false in `dev`, requires an explicit false value in `prod`, validates positive budgets, and exposes per-job enable flags without reading any real environment file. HTTP tests will plant allowed and denied hosts, reject redirect escapes, assert the ten-second default timeout, retry only idempotent requests on 429/5xx with bounded jitter/backoff, never retry unsafe requests implicitly, raise typed `EgressDenied`/`ExternalError`, and prove logs redact authorization/cookie headers, sensitive query values, and request/response bodies. Logging tests will capture JSON output and prove raw email local parts, names, phone numbers, tokens, message bodies, and note bodies never appear while email domains and correlation ids remain. Database/state tests will use fakes only (no real database), assert async pool configuration and ten-second statement timeout, parameterized fixed SQL, transaction rollback, 15-second kill-switch caching, key/value state, and UTC last-run stamps. External-write guard tests will prove kill switch, dry run, budget exhaustion, duplicate idempotency, success, and downstream-error paths; dry run must assert zero HTTP calls and one `skipped` audit row, kill switch must block before the wrapped function, duplicates must not call it, and failures must produce the appropriate typed error/audit status without consuming a success. Repository guard tests will plant `httpx` imports in every disallowed location, preserve the sole positive case in `src/tis/http.py`, detect any difference between the exact runtime and static two-host allowlists, and reject service URL literals outside `src/tis/http.py`. Better Stack/PostHog tests will use `respx` to prove exact allowlisted requests, synthetic payload models, idempotency keys, budgets, retry/error handling, and redacted logs. An autouse test fixture will deny unexpected network access. No Docker or Terraform command is part of G0 planning; implementation must still follow the binding G1/G2 gates, with CI serving as G2 rather than as a silent replacement for a repository check. `make check` must remain green with at least 85% coverage for the new core modules and no skipped or xfailed tests.

Rollback: before merge, revert the M1 implementation commits or close the PR. After merge, use a normal revert PR for the M1 commits and restore the previous lockfile. M1 will not deploy, execute migrations, call production endpoints, or change external-system records; with `DRY_RUN=true` as the default, later callers remain write-disabled until an explicit production setting and all subsequent gates permit them.

Open questions: before M1.4/M1.6 implementation, Rehaan must provide or confirm the redacted column contract for the existing `integration_log` and `integration_state` tables (column names/types, allowed status values, timestamps, and conflict keys) without sharing a connection string or production rows. The master plan defines the unique key `(source, external_id, action)` and required state keys but not the complete columns. If the tables do not yet exist, a separate approved plan will be required to add a human-applied SQL draft under `docs/sql/`; M1 will not guess or execute a schema. This amendment adds the direct `pydantic` pin and the protected `scripts/guard.py` scope after the first approval, so a fresh `G0 approved` comment is required. M6 is intentionally not planned or implemented in this PR because `docs/MASTER-PLAN.md` requires one milestone at a time; its protected Terraform G0 begins only after the preceding milestone sequence permits it.

**M1 G1 evidence (2026-09-19)**

- Fresh `G0 approved` was confirmed on PR #3 after the direct `pydantic` and protected `scripts/guard.py` amendment.
- Rehaan supplied the authoritative redacted contracts for `public.integration_log` and `public.integration_state`; no production rows or credentials were used.
- `uv run ruff check .`: PASS; `uv run ruff format --check .`: PASS (39 files formatted); `uv run mypy src/tis`: PASS (14 source files).
- `uv run pytest`: PASS, 90 tests, no skips or xfails, 90.12% total coverage (`db` 86%, `guards` 94%, `http` 89%, `state` 95%). Tests use synthetic values and an autouse RESPX router that rejects every unmocked HTTP request.
- `uv run python scripts/guard.py`: PASS; reports the three approved protected paths (`scripts/guard.py`, `src/tis/guards.py`, `src/tis/http.py`). `rg` confirms `src/tis/http.py` is the only file that imports `httpx` directly.
- `uv run pip-audit`: PASS, no known vulnerabilities. `uv run pip-licenses --fail-on=...`: PASS; no GPL/AGPL package rejected.
- `make check`: reached the containerized gitleaks step after all preceding checks passed, then failed because the local Docker Desktop Linux engine pipe does not exist. Native `gitleaks` is not installed, and the Docker image build therefore also could not run. Per the approved instruction, Codex did not wait for or attempt to repair Docker; G2 CI remains the container/gitleaks gate. Local G1 stays partial until those two Docker-backed checks run.
- G2 CI run `35425097047`: PASS. The `checks` job installed the frozen dependency graph, ran G1 checks, built the image, passed the fixable HIGH/CRITICAL Trivy gate, generated the CycloneDX SBOM, and uploaded it. The conditional Terraform job also passed with its Terraform steps correctly skipped because M1 has no infrastructure files.
- `make verify-bundle MILESTONE=M1`: failed immediately when `scripts/verify_bundle.sh` could not connect to the local Docker API; no bundle file was emitted or committed.
- After Docker Desktop became available, `make check`: PASS end to end. The containerized gitleaks scan inspected approximately 884 KB with no leaks, and the local `tis:local` Docker image built successfully.

**M1 decisions made**

- The supplied `Prefer: resolution=merge-duplicates` instruction is a Supabase REST header. Because M1 approved Psycopg and no Supabase HTTP egress host, the implementation uses the equivalent parameterized PostgreSQL `ON CONFLICT (source, external_id, action)` path and records this interpretation in `docs/pr-notes/M1.md`.
- A live write first makes an atomic `integration_log` claim using the authoritative unique key. An existing `ok` or in-progress claim cannot execute twice; prior `error` or dry-run `skipped` rows may be reclaimed safely.
- Better Stack endpoint paths can contain monitor credentials, so HTTP logs redact all non-root URL paths in addition to sensitive headers, query parameters, and every request/response body.
- The static guard mirrors the exact runtime allowlist, fails on drift, and permits only the `httpx` client import in `src/tis/http.py`; other network clients remain forbidden even in that module.

**M1 open questions / blockers**

No implementation or schema questions remain. The earlier local Docker blocker is resolved. M6 has not started and requires its own plan-only PR after M1 completes its review sequence.

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

**Tasks**

| Task | Status | PR | Notes |
|---|---|---|---|
| M6.1 Provider, backend, variables | ☑ | #4 | Provider 5.25.0 locked; R2 S3 backend and no-default identifiers validated. |
| M6.2 Tunnel and ingress | ☑ | #4 | Remotely managed tunnel has ops, SSH, and final 404 ingress. |
| M6.3 Access applications and policies | ☑ | #4 | Two self-hosted apps use exact-admin policies and 12-hour sessions. |
| M6.4 Tunnel DNS records | ☑ | #4 | Only `ops` and `ssh` proxied CNAMEs; both have `prevent_destroy`. |
| M6.5 Existing Turnstile widget import | ☑ | #4 | Existing managed widget is declared with import block and `prevent_destroy`. |
| M6.6 R2 backups bucket | ☑ | #4 | `torus-backups` has `prevent_destroy`; state bucket remains a manual prerequisite. |
| M6.7 Zone settings and conditional site domains | ☑ | #4 | Strict TLS/HTTPS, www redirect, and default-off Workers domains validate. |

### M6 G0 plan (2026-09-19)

Scope: M6.1, M6.2, M6.3, M6.4, M6.5, M6.6, and M6.7. Build the reviewed Cloudflare Terraform module and local plan-safety tooling described by `docs/INFRA-EXECUTION.md` Part 5.1. This is the plan-only gate: no Terraform command, Cloudflare API/dashboard query, import, plan, apply, state operation, or infrastructure mutation will occur before a fresh `G0 approved` comment. Rehaan alone runs the later credentialed plan/apply session, and Claude reviews `plan.txt` before apply.

Files to create/modify: create `infra/cloudflare/versions.tf`, `infra/cloudflare/providers.tf`, `infra/cloudflare/variables.tf`, `infra/cloudflare/tunnel.tf`, `infra/cloudflare/dns.tf`, `infra/cloudflare/access.tf`, `infra/cloudflare/turnstile.tf`, `infra/cloudflare/r2.tf`, `infra/cloudflare/zone.tf`, `infra/cloudflare/site_domain.tf`, `infra/cloudflare/outputs.tf`, `infra/cloudflare/README.md`, `infra/cloudflare/.tflint.hcl`, `infra/cloudflare/.terraform.lock.hcl`, `scripts/tf_gate.py`, `tests/unit/test_tf_gate.py`, `tests/fixtures/terraform/clean-create.json`, `tests/fixtures/terraform/delete.json`, `tests/fixtures/terraform/forbidden-mx.json`, `tests/fixtures/terraform/broadened-access.json`, `tests/fixtures/terraform/over-limit.json`, and `docs/pr-notes/M6.md`; modify `.gitignore`, `Makefile`, `scripts/guard.py`, `tests/unit/test_guard.py`, and `PROGRESS.md`. The PR-notes file is the one implementation-time scope correction: M0.9 made it mandatory input to `make verify-bundle`, but it was inadvertently absent from this list at approval. Adding this non-protected documentation file changes no dependency, host, privilege, external write, or protected path and therefore does not require re-approval under AGENTS.md 3.2. `.github/workflows/ci.yml` will not change: its M0.9 configuration already detects `infra/cloudflare/*.tf`, pins Terraform `1.14.6`, and runs only `make tf-fmt` and `make tf-validate`; it never plans or applies. No application source, deployment, secret, SOPS, dependency-lock, or verification-script file will change.

Protected paths touched: yes (`infra/**`, `scripts/guard.py`, and, as explicitly designated for this milestone, `scripts/tf_gate.py` and `Makefile`). The implementation PR must carry `protected-change`. `AGENTS.md`, `.github/**`, `deploy/**`, `.sops.yaml`, `secrets/**`, `scripts/verify_bundle.sh`, `src/tis/http.py`, and `src/tis/guards.py` will not change.

New dependencies: no Python runtime or development package. Terraform will continue at the CI-pinned `1.14.6` (Business Source License 1.1; existing developer/CI executable) and will lock `cloudflare/cloudflare==5.25.0` (Apache-2.0; exact provider version verified from the official release; required to manage the approved Cloudflare resources) in `.terraform.lock.hcl`. Local lint documentation/configuration will pin TFLint `0.64.0` (MPL-2.0; static Terraform linting required by `docs/CLOUDFLARE.md`); it is a developer executable, not installed by Python or CI. No provider or tool may float to `latest`, and no additional Terraform provider or GitHub Action will be added.

New egress hosts: none for the `tis` service, and `src/tis/http.py` remains unchanged. In the later human credentialed session, Terraform itself will contact Cloudflare's provider API and the account-scoped R2 S3 endpoint configured for the backend; those are infrastructure-tool connections, not service egress entries. Tests, G0 work, `terraform fmt`, `terraform validate -backend=false`, TFLint, and `tf_gate.py` use no Cloudflare credentials and make no Cloudflare API calls.

New scopes/privileges: no service, database, OAuth, GitHub, or host privilege. The later human-created `terraform-torus` Cloudflare token is limited to Account Access Apps and Policies Edit, Turnstile Edit, Workers R2 Storage Edit, Account Settings Read, and for the `torusmesh.com` zone only DNS Edit, Zone Settings Edit, Zone Read, and Dynamic Redirect Edit. Backend credentials are limited to Object Read & Write on the existing `torus-tfstate` bucket. Values for `account_id`, `zone_id`, `zone_name`, `admin_email`, `worker_name`, `site_hostnames`, `ops_hostname`, `ssh_hostname`, and the existing public `turnstile_sitekey` have no repository defaults and are supplied only through gitignored `terraform.tfvars`; `enable_site_custom_domain` is the sole behavior switch and defaults to `false`. No token, secret, account/zone id, personal email, state credential, or `.tfvars` value is committed.

External writes added: Terraform declarations for: the remotely managed `torus-home` tunnel and its configuration; proxied `ops` and `ssh` tunnel CNAMEs; two self-hosted Access applications and exact-admin allow policies with 12-hour sessions; the existing `torus-mesh-form` Turnstile widget managed only after import; private `torus-backups`; strict SSL/Always Use HTTPS and the `www` redirect; and, only when `enable_site_custom_domain=true`, Workers custom-domain resources for the apex and `www`. Terraform addresses plus the R2-backed state provide idempotency; `tf_gate.py` caps an approved plan at 30 total changes and rejects every delete or replace. `@external_write` does not apply to declarative Terraform executed manually outside the service. `lifecycle { prevent_destroy = true }` is required on both tunnel DNS records, the Turnstile widget, and `torus-backups`. No WAF/hooks resource is created in M6; it remains reserved for M8.

Terraform design and import safety: `versions.tf` configures the exact provider and the S3 backend bucket `torus-tfstate` with key `cloudflare/terraform.tfstate`, region `auto`, an account-specific endpoint supplied at initialization, and the required S3 validation/checksum skips without embedding credentials. `tunnel.tf` routes `ops.torusmesh.com` to `http://tis-api:8080`, `ssh.torusmesh.com` to `ssh://host-gateway:22`, and ends with `http_status:404`. `dns.tf` declares only proxied CNAME records for the configured `ops` and `ssh` hostnames. `access.tf` includes exactly `var.admin_email`, never Bypass or Everyone. `turnstile.tf` declares `cloudflare_turnstile_widget.form` in Managed mode for `torusmesh.com`, `www.torusmesh.com`, and the supplied current `workers.dev` hostname(s), plus an import block whose id is `${var.account_id}/${var.turnstile_sitekey}`; the first reviewed plan must therefore show an import, not a create. `r2.tf` manages only `torus-backups`; `torus-tfstate` is never a managed resource. `site_domain.tf` uses `cloudflare_workers_custom_domain` only behind the default-false switch and does not declare DNS records. Outputs include tunnel id, sensitive tunnel token, ops Access audience, public Turnstile sitekey, and sensitive Turnstile secret. The specific Part 5.1 instructions to import Turnstile and conditionally manage Workers custom domains supersede older prose in `docs/MASTER-PLAN.md`/`docs/CLOUDFLARE.md` that says those objects stay dashboard-only.

Plan gate and repository guard: `scripts/tf_gate.py` accepts a `terraform show -json` plan file plus the gitignored tfvars source, parses both without third-party Python packages, and prints only resource type, address, action, the explicitly checked DNS name/type or policy email comparison, and a final `PASS`/`FAIL`; it never prints general attribute values. The explicit managed-resource allowlist is exactly `cloudflare_zero_trust_tunnel_cloudflared`, `cloudflare_zero_trust_tunnel_cloudflared_config`, `cloudflare_dns_record`, `cloudflare_zero_trust_access_application`, `cloudflare_zero_trust_access_policy`, `cloudflare_turnstile_widget`, `cloudflare_r2_bucket`, `cloudflare_zone_setting`, `cloudflare_ruleset`, and `cloudflare_workers_custom_domain`; the read-only `cloudflare_zero_trust_tunnel_cloudflared_token` data source is the only allowed data-source type. The gate exits non-zero for any delete or replace; any type outside that allowlist; more than 30 changes; any `cloudflare_dns_record` of type `MX`, `TXT`, `NS`, or `CAA`; any DNS record named `@`, `www`, `torusmesh.com`, `www.torusmesh.com`, or their normalized apex equivalents; any Access include list not exactly the configured admin email; or any resource whose planned `account_id`/`zone_id` differs from gitignored tfvars. `scripts/guard.py` independently scans Terraform source and fails if a `cloudflare_dns_record` block can manage MX/TXT/NS/CAA or apex/www, including variable/literal forms that cannot be proven safe. These complementary rules never permit existing email, verification, nameserver, CAA, apex, or `www` DNS records to enter Terraform.

Make and artifact safety: add `tf-init`, `tf-lint`, `tf-plan`, `tf-gate`, and `tf-apply`. `tf-plan` writes only `infra/cloudflare/plan.tfplan`, `plan.txt`, and `plan.json`; `tf-gate` evaluates that JSON and gitignored tfvars; `tf-apply` refuses unless both artifacts exist and a fresh rerun of the gate passes, then applies the saved plan only. `.gitignore` adds `infra/cloudflare/plan.tfplan`, `plan.txt`, `plan.json`, `terraform.tfvars`, `.terraform/`, and `*.tfstate*`. No target prints credentials or tfvars. Codex will run only formatting, TFLint, `terraform init -backend=false`, and validate after approval; Codex will never invoke `tf-plan`, `tf-apply`, `terraform plan`, `terraform apply`, import, state commands, or credentialed initialization.

Tests: `tests/unit/test_tf_gate.py` invokes the gate against saved synthetic JSON and synthetic tfvars without network access. A clean create/import-only M6 plan must pass and produce a bounded action table plus `PASS`. Planted fixtures must fail separately for a delete, replace, forbidden/unapproved resource type, MX/TXT/NS/CAA records, apex/www record names, broadened or non-exact Access includes, mismatched zone/account ids, and 31 changes. Tests also prove the output excludes unrelated before/after values and synthetic credentials. `tests/unit/test_guard.py` plants Terraform source violations for each forbidden DNS type and apex/www name, including attempts to hide values behind locals/variables, while safe `ops`/`ssh` CNAME blocks pass. After approval, G1 runs `make check`, `make tf-fmt`, `make tf-validate`, and pinned TFLint; G2 repeats format/validate only. No test, CI job, or Codex command contacts Cloudflare or runs a plan/apply.

Rollback: before any human apply, revert or close the implementation PR and delete only local ignored plan artifacts. After apply, do not delete, replace, or remove protected resources ad hoc. Rehaan restores the last reviewed Terraform commit/state and produces a new saved plan; `tf_gate.py` and Claude must approve it before another apply. Existing DNS export remains the disaster-recovery reference, and any emergency dashboard change is recorded in `PROGRESS.md` then reconciled through a new approved plan. The imported Turnstile widget, tunnel DNS records, and backups bucket remain protected by `prevent_destroy` throughout.

Open questions: Rehaan must confirm in the Cloudflare dashboard that the manually created `torus-tfstate` bucket exists before the later backend initialization; repository policy forbids Codex from querying Cloudflare, so absence is treated as a manual prerequisite. Before the human plan session, Rehaan supplies through gitignored tfvars—not chat or the repository—the account/zone ids, admin email, exact current `workers.dev` hostname, worker name, hostnames, and existing public Turnstile sitekey. During implementation, offline provider-schema validation must confirm that the imported widget exposes a sensitive secret output; if Cloudflare does not return the secret after import, Rehaan retrieves it from the dashboard and no secret is written to state output or the repository. The first plan is blocked unless it shows the Turnstile import (not create), contains no delete/replace, and passes `tf_gate.py`; Claude then reviews `plan.txt` before Rehaan applies. No other question authorizes widening DNS ownership, token scopes, resource types, or the 30-change ceiling.

(G4 replaced by: `plan.txt` reviewed by Claude; G5 replaced by: apply output and post-apply checks.)

**M6 G1 evidence (2026-09-19)**

- G0 approval: repository-owner comment `G0 approved` on draft PR #4 before implementation.
- `make check`: PASS. Ruff check/format and mypy passed; pytest passed 119 tests with 90.12% total coverage and no skips/xfails; repository guard passed while reporting 15 protected changes; pip-audit found no known vulnerabilities; the license gate passed; gitleaks found no leaks; Docker built `tis:local` successfully.
- `make tf-fmt`: PASS with Terraform 1.14.6.
- `make tf-validate`: PASS after `terraform init -backend=false`; Cloudflare provider 5.25.0 was selected from the committed lock file and the configuration is valid. No backend, credentials, Terraform plan, import, state, apply, or Cloudflare API operation was used.
- `make tf-lint`: PASS with TFLint 0.64.0 and its bundled Terraform ruleset.
- Planted safety checks: PASS. Tests reject removal/replacement, unapproved resource types, MX/TXT/NS/CAA and apex/www DNS, broadened Access includes, missing or mismatched account/zone ids, 31 changes, unsafe Terraform DNS expressions, and leakage of unchecked values. The clean synthetic create-plus-import fixture passes.

**M6 decisions and open questions**

- Provider validation requires Access application policy precedence to begin at 1; both exact-admin attachments use precedence 1.
- Import records with a Terraform `no-op` action are still counted and checked by `tf_gate.py` when the JSON contains import metadata.
- Offline provider-schema validation confirmed the imported Turnstile resource exposes `secret`; the Terraform output remains marked sensitive. Whether the real imported object returns a populated value is verified only in the later human execution session.
- Open: Rehaan must confirm the manually created `torus-tfstate` bucket exists before credentialed backend initialization and must supply all no-default inputs through gitignored tfvars. The first human plan must show the Turnstile import rather than a create, contain no removal/replacement, pass `tf_gate.py`, and receive the required Claude review before apply.
- Deviation: `docs/pr-notes/M6.md` was added because the merged M0.9 bundle contract requires it. No other deviation from the approved implementation plan occurred.

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
| 2026-09-19 | M6 imports the existing Turnstile widget and gates every saved plan before human apply | Prevent recreation and block destructive or out-of-scope Cloudflare changes | PR #4 / M6 G0 plan |

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
| scripts/guard.py | ae34b60a6ca3d3c3 | M0.9 |
| scripts/verify_bundle.sh | 972e4c131054f0dd | M0.9 |
| src/tis/http.py | not present | deferred to M1 |
| src/tis/guards.py | not present | deferred to M1 |
| .github/workflows/ci.yml | 2da7d04ad3321338 | M0.9 |
| .github/workflows/release.yml | 0e838e82f03a5f5d | M0.9 |
| deploy/deploy.sh | not present | deferred to M5 |
