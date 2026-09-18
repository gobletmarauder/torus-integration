# INFRA-EXECUTION.md: how the agent runs Cloudflare and Terraform

Place at `docs/INFRA-EXECUTION.md`. Version 1.0 · 17 September 2026
Companion to `AGENTS.md` section 7, `docs/CLOUDFLARE.md` and `docs/MASTER-PLAN.md` milestone M6.

**What changed from the earlier plan:** the coding agent now runs Terraform itself, in a clearly marked session, with a machine gate in front of `apply`. Cloudflare Turnstile is created by Terraform too. The human still exports the credentials, reads the gate output, and types the approval.

---

## Part 1. Why this is safe enough to automate

| Risk | Control |
|---|---|
| A plan deletes DNS records that carry company email | `scripts/tf_gate.py` fails on any delete or replace, and on any change to `MX`, `TXT`, `NS`, `CAA` records or to `@` and `www`. Terraform also has `prevent_destroy` on critical resources, and the module never declares email records |
| The agent applies something you have not seen | `apply` is allowed only against a saved plan file, after the gate passes, after you type `apply approved` in that session |
| The agent leaks a token | Credentials exist only as environment variables exported by you in that shell; `AGENTS.md` 7.2 forbids printing them; `terraform output -raw` is human-only |
| The token itself is over-powered | Scoped to one zone and four account permissions, with a 90-day expiry and optional IP restriction |
| A compromised repo runs Terraform in CI | CI runs `fmt` and `validate` only; no Cloudflare credentials exist in GitHub |
| Drift between code and reality | State in R2; `terraform plan` run at the start of every infra session must show no unexpected changes |

Things the agent still may not do: `destroy`, `-target`, `-auto-approve`, state surgery, `wrangler deploy`, `wrangler secret`, curl against the Cloudflare API, or any work on the home server.

---

## Part 2. Which agent

| Tool | Use it for | Setup |
|---|---|---|
| **Codex CLI** (recommended) | Everything, including infra sessions, because it already reads `AGENTS.md` and your repo rules | Part 3.1 |
| **Claude Code** | Same tasks if you prefer it; add a `CLAUDE.md` at the repo root containing `@AGENTS.md` so it loads the same rules, and start infra sessions with the same prompt | Part 3.2 |
| Codex cloud | Code milestones only. It has no network by default and must never hold Cloudflare credentials | unchanged |

Use one agent per session. Do not run two agents against the same working copy.

---

## Part 3. One-time setup (you, about 20 minutes)

### 3.0 Credentials you create in the dashboard

| # | Item | Where | Notes |
|---|---|---|---|
| 1 | API token `terraform-torus` | Cloudflare → My Profile → API Tokens → Create Custom Token. Permissions: Account · Cloudflare Tunnel · Edit; Account · Access: Apps and Policies · Edit; Account · Turnstile · Edit; Account · Workers R2 Storage · Edit; Account · Workers Scripts · Edit (needed only for the custom-domain step); Account · Account Settings · Read; Zone (torusmesh.com only) · DNS · Edit; Zone · Zone Settings · Edit; Zone · Zone · Read; Zone · Dynamic Redirect · Edit; Zone · Zone WAF · Edit | TTL 90 days; add your home and laptop IPs if they are stable |
| 2 | R2 state bucket | The agent creates it with `wrangler r2 bucket create torus-tfstate` using the same token | |
| 3 | R2 access keys for the Terraform backend | Cloudflare → R2 → Manage API tokens → Create token, Object Read and Write, bucket `torus-tfstate` | S3-style keys cannot be created with the token above, so this one stays manual |

### 3.1 Codex CLI profile for infra

Add to `~/.codex/config.toml` (keep your existing default settings):

```toml
# default profile stays network-off for code work
sandbox_mode = "workspace-write"
approval_policy = "on-request"

[sandbox_workspace_write]
network_access = false

[profiles.infra]
sandbox_mode = "workspace-write"
approval_policy = "on-request"

[profiles.infra.sandbox_workspace_write]
network_access = true
```

[VERIFY the nested profile key against `codex config --help` for your version; if profiles do not accept the nested table, start infra sessions with `codex --sandbox workspace-write --config sandbox_workspace_write.network_access=true` instead.]

Start an infra session:

```bash
cd ~/path/to/torus-integration && git pull
set -a; source ~/.torus/terraform.env; set +a     # the file from START-HERE Part 3
terraform -version && npx wrangler whoami          # sanity check before handing over
codex --profile infra
```

### 3.2 Claude Code alternative

```bash
printf '@AGENTS.md\n' > CLAUDE.md      # commit this; it makes Claude Code load the same rules
set -a; source ~/.torus/terraform.env; set +a
claude
```

Keep tool permissions on ask for `Bash`, and approve each Terraform command as it comes.

---

## Part 4. The session shape

1. You export credentials and start the agent (Part 3.1).
2. You paste the **infra execution prompt** (Part 5).
3. Agent runs `init`, `validate`, `plan`, writes `plan.txt` and `plan.json`, runs `scripts/tf_gate.py`, and pastes the gate output plus a change summary.
4. You read the gate output. Optional but recommended for the first two applies: upload `infra/cloudflare/plan.txt` to Claude and ask for the plan review in `docs/VERIFICATION.md` 3.4.
5. You type `apply approved`.
6. Agent applies that plan file and pastes the apply output, then the summary block (Part 6).
7. You retrieve sensitive outputs yourself:
   ```bash
   terraform -chdir=infra/cloudflare output -raw tunnel_token      # into the vault, later into cloudflared.enc.env
   terraform -chdir=infra/cloudflare output -raw turnstile_secret  # into the vault, later into tis.enc.env
   terraform -chdir=infra/cloudflare output turnstile_sitekey      # public: paste into /admin Settings
   terraform -chdir=infra/cloudflare output ops_access_aud         # not secret: tis.env
   ```
8. You `unset` the credentials and close the shell.

---

## Part 5. Prompts

### 5.1 Build the Terraform (normal task, no credentials, no network needed)

```
Repository: torus-integration. Read AGENTS.md, PROGRESS.md, docs/MASTER-PLAN.md (milestone M6), docs/CLOUDFLARE.md (Parts 0, 3, 8) and docs/INFRA-EXECUTION.md.

Task: milestone M6, G0 plan only. This is a protected-change (infra/**, scripts/tf_gate.py, Makefile).

Cover in the plan:
- infra/cloudflare module: versions.tf with the cloudflare provider pinned to an exact 5.x version and the R2 S3 backend; providers.tf; variables.tf (account_id, zone_id, zone_name, admin_email, worker_name, site_hostnames, ops_hostname, ssh_hostname, enable_site_custom_domain default false); tunnel.tf; dns.tf; access.tf; turnstile.tf; r2.tf; zone.tf; site_domain.tf (cloudflare_workers_custom_domain for torusmesh.com and www, created only when enable_site_custom_domain is true); outputs.tf.
- Turnstile IS managed here: widget torus-mesh-form, Managed mode, domains torusmesh.com, www.torusmesh.com and the current workers.dev hostname. Outputs: sitekey (plain) and secret (sensitive).
- lifecycle prevent_destroy on tunnel hostname records, the Turnstile widget and the backups bucket.
- The module must never declare MX, TXT, NS or CAA records, and never an apex or www DNS record.
- scripts/tf_gate.py: reads a terraform show -json plan file and exits non-zero on: any delete or replace action; any cloudflare_dns_record with type MX, TXT, NS or CAA, or name @, www, torusmesh.com or www.torusmesh.com; any access policy whose include list is not exactly the admin email; any resource type outside an explicit allowlist; more than 30 total changes; any change to a zone or account id not in terraform.tfvars. It prints a table of actions by address and a PASS or FAIL line, and never prints attribute values other than resource type, address, action and the fields it checks.
- Makefile targets tf-init, tf-plan (writes plan.tfplan, plan.txt, plan.json), tf-gate, tf-apply (refuses unless plan.tfplan and a passing plan.json exist).
- .gitignore additions: infra/cloudflare/plan.tfplan, plan.txt, plan.json, terraform.tfvars, .terraform/, *.tfstate*.
- Unit tests for tf_gate.py using saved JSON fixtures: a clean create-only plan passes; a plan with a delete fails; an MX record change fails; a broadened access policy fails; an over-large plan fails.
- CI: keep terraform fmt and validate only, with the M0.9 fix so the job actually runs; never plan or apply in CI.
The Turnstile widget torus-mesh-form already exists in the dashboard. Write the resource and an import block for it rather than creating a new one, so the plan shows an import, not a create.

Stop after writing the plan into PROGRESS.md.
```

Then the usual `G0 approved for M6. Implement exactly the approved plan...` message, bundle, and Claude verification before merge.

### 5.2 Infra execution session (after M6 merges)

```
INFRA EXECUTION SESSION: M6 Cloudflare apply.

Read AGENTS.md section 7 and docs/INFRA-EXECUTION.md before running anything. Credentials are already in the environment; never print or copy them.

Do this in order and paste each command's output:
1. git status (must be clean) and git log -1 --oneline.
2. npx wrangler whoami, then npx wrangler r2 bucket list. If torus-tfstate does not exist, create it with npx wrangler r2 bucket create torus-tfstate.
3. make tf-init, then make tf-validate.
4. make tf-plan.
5. make tf-gate. Paste the full gate output and a one-line-per-resource summary of what will be created.
6. STOP. Do not apply. Wait for me to type "apply approved".

After I approve: run make tf-apply against that same plan file, paste the apply output, then list the output names only (terraform -chdir=infra/cloudflare output, never -raw), then give the session summary from docs/INFRA-EXECUTION.md Part 6.

If anything fails, stop and report. Do not retry with different flags, do not use -target, -replace or -auto-approve, and do not touch state.
```

### 5.3 Later infra sessions

Same prompt with the milestone changed (for example `INFRA EXECUTION SESSION: enable_site_custom_domain for the torusmesh.com cutover`). For the cutover session, add:

```
Before planning, confirm in the plan that only cloudflare_workers_custom_domain resources are created and that no DNS record is deleted. The old Lovable A and CNAME records for @ and www are removed by me in the dashboard, not by Terraform.
```

---

## Part 6. Session summary the agent must produce

```
INFRA SESSION SUMMARY
Session type: <build | execution>   Milestone: <id>   Date (UTC):
Repo: torus-integration   Branch:   Commit:

Commands run (in order, with exit codes):
1.
2.

Files changed (path: what changed):

Terraform:
- init: <ok/fail>   validate: <ok/fail>
- plan: <N to add, N to change, N to destroy>
- gate: <PASS/FAIL> (<rules triggered, if any>)
- applied: <yes/no> at <time>; apply result: <N added, N changed, N destroyed>

Resources now managed (type and address only):

Outputs available (names only):

Manual follow-ups for Rehaan:
1.

Anything I could not do, and why:

Deviations from the approved plan or from AGENTS.md: none | <list>
```

Paste that block, plus the gate output and `plan.txt` if the session applied anything, into Claude for the record.

---

## Part 7. What still cannot be automated

| Task | Why | Who, how long |
|---|---|---|
| Workers Builds GitHub connection | OAuth app authorization in the browser | You, done already |
| R2 S3-style access keys | Not creatable with the Terraform token | You, 3 minutes |
| Cloudflare Access identity method (one-time PIN) | Zero Trust onboarding flow | You, 5 minutes |
| Google Calendar appointment schedule | No public API for appointment schedules | You, 20 minutes |
| Zoho workflow rules, Blueprint, layouts | No public creation API | You, about 60 minutes |
| Zoho custom fields | There is a fields metadata API [VERIFY for your edition]; if it works, this becomes optional milestone **M2.0**: the agent writes `scripts/zoho_bootstrap.py` with `--dry-run` default and idempotent create-or-skip per field, and you run it once with the refresh token in your environment | Agent writes, you run, 15 minutes |
| Supabase schema changes | Owned by Lovable | Lovable |
| Home server bootstrap and deploys | Root on your machine, secrets present | You, with the scripts from M5 |
