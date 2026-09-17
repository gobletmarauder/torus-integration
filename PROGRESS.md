# PROGRESS.md: Torus Integration Service

Updated by Codex on every task and by Rehaan at every gate. Newest entries at the top of each section. Dates in YYYY-MM-DD, times UTC.

**Current milestone:** M0 · **Current gate:** G0 · **Production version:** none · **DRY_RUN in prod:** n/a · **Kill switch:** n/a

---

## 1. Gate board

| Milestone | G0 Plan | G1 Local | G2 CI | G3 Claude | G4 Dry run | G5 Live | G6 Burn-in | Bundle / PR |
|---|---|---|---|---|---|---|---|---|
| M0 Repo bootstrap | ☐ | ☐ | ☐ | ☐ | n/a | n/a | n/a | |
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
| M0.1 Layout, pyproject, tooling | ☐ | | |
| M0.2 Makefile | ☐ | | |
| M0.3 guard.py | ☐ | | |
| M0.4 verify_bundle.sh | ☐ | | |
| M0.5 CI and release workflows | ☐ | | |
| M0.6 CODEOWNERS, PR template | ☐ | | |
| M0.7 .env.example, .sops.yaml | ☐ | | |
| M0.8 PROGRESS.md initialized | ☐ | | |

**G0 plan**

```
(Codex writes the plan here using the AGENTS.md 3.1 template)
```

**G1 evidence**

```
(command, date, summary of results)
```

**G3 verdict (Claude)**

```
(PASS/FAIL, date, bundle file name, findings, required fixes)
```

**Decisions made during the milestone**

- 

**Deferred items**

- 

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
| AGENTS.md | | |
| scripts/guard.py | | |
| scripts/verify_bundle.sh | | |
| src/tis/http.py | | |
| src/tis/guards.py | | |
| .github/workflows/ci.yml | | |
| deploy/deploy.sh | | |
