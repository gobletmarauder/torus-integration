# Torus Mesh Cloudflare Setup

**Everything Cloudflare does for Torus Mesh, set up two ways: Terraform written by Codex and applied by Rehaan (recommended), or explicit dashboard steps.**
Version 1.0 · 16 September 2026 · Owner: Rehaan Merchant
Reads with: `torus-mesh-MASTER-PLAN.md` (A2, A7, A9, milestone M6), `torus-mesh-HOME-SERVER-HOSTING.md`. Copy into the repo as `docs/CLOUDFLARE.md`.

**Rule:** Codex writes Terraform and never runs it. Rehaan runs `plan`, Claude reviews the plan text, Rehaan runs `apply`. A Cloudflare token that can edit DNS can take down the website and company email in one call.

---

## Part 0. What Cloudflare does, and how each piece is managed

| Piece | Purpose | Managed by | Why |
|---|---|---|---|
| Zone `torusmesh.com` | DNS, TLS, WAF | Already exists (dashboard) | |
| Existing email and verification records (MX, SPF, DKIM, DMARC, Google/Zoho TXT) | Company email | **Dashboard only; never Terraform** | Removes any chance a plan deletes them |
| Website hosting | Lovable TanStack Start app (SSR) as a Worker | **Workers Builds** (dashboard, GitHub connection) + `wrangler.jsonc` in the Lovable repo | GitHub app authorization is a dashboard flow |
| Website custom domains `torusmesh.com`, `www` | Point the domain at the site | **Dashboard at cutover** (Part 5) | Done once, deliberately, with a rollback plan |
| Tunnel `torus-home` | Outbound connection from the home server | Terraform | |
| Tunnel hostnames `ops.torusmesh.com`, `ssh.torusmesh.com` | Ops status page, SSH | Terraform (DNS + tunnel config) | |
| Access applications and policies | Login in front of ops and SSH | Terraform | |
| Turnstile widget | Bot check on the lead form | **Dashboard** (created early to unblock the site; left unmanaged by Terraform) | Avoids recreate churn |
| R2 bucket `torus-backups` | Encrypted database backups | Terraform | |
| R2 bucket `torus-tfstate` | Terraform state | **Dashboard, once** | Chicken-and-egg |
| Zone settings (SSL, HTTPS) and the `www` redirect | Security and canonical host | Terraform | |
| Phase 2: `hooks.torusmesh.com`, WAF rule for webhooks | Stripe webhooks | Terraform | |

---

## Part 1. Before touching anything (20 minutes, dashboard)

1. **Account security:** Cloudflare account → My Profile → Authentication: add a passkey or hardware key; confirm two-factor is on.
2. **Snapshot DNS:** DNS → Records → Import and Export → **Export** the zone file. Save it in the password manager or a private drive. This is your rollback for any DNS mistake.
3. **Write down** the record(s) currently serving the website (the Lovable A or CNAME on `@` and `www`). You will remove only those at cutover.
4. **Account id and zone id:** zone Overview page, right sidebar. Note both.
5. **Zero Trust team:** Zero Trust dashboard → Settings → Custom pages / Team domain. If not created yet, create team `torusmesh` (team domain `torusmesh.cloudflareaccess.com`). Add **One-time PIN** as a login method (Settings → Authentication) so Access works with rehaan@torusmesh.com without extra identity providers. Optionally add Google Workspace as an identity provider later.

---

## Part 2. Website hosting on Workers Builds (dashboard)

The Lovable site is **TanStack Start with server-side rendering**, so it deploys as a Worker built with the Cloudflare Vite plugin (not as assets only). The Lovable fix-up message in `torus-mesh-NEXT-STEPS.md` Part 4 sets this up; the repo should then contain:

```jsonc
// wrangler.jsonc
{
  "$schema": "node_modules/wrangler/config-schema.json",
  "name": "torus-mesh-site",
  "compatibility_date": "2026-09-14",
  "compatibility_flags": ["nodejs_compat"],
  "main": "@tanstack/react-start/server-entry",
  "observability": { "enabled": true }
}
```

and `cloudflare({ viteEnvironment: { name: 'ssr' } })` as the first plugin in `vite.config`.

Steps:

1. Workers & Pages → **Create** → **Import a repository** → authorize the Cloudflare GitHub app for the Lovable repo only (not all repositories).
2. Settings:
   - Project name: `torus-mesh-site` (must match `name` in `wrangler.jsonc`)
   - Production branch: `main`
   - Build command: `bun install --frozen-lockfile && bun run build`
   - Deploy command: `bunx wrangler deploy`
   - Non-production branch builds: on (preview URLs)
   - Variables: only the names Lovable reports in its fix-up report (publishable values). Mark nothing secret here; if Lovable lists a secret, stop and review before deploying.
3. Deploy. Open `https://torus-mesh-site.<account-subdomain>.workers.dev`; confirm pages render, `curl -s <url>/audit | grep -i "<title>"` shows a real title, and `curl -sI <url>/audit` shows the security headers.
4. Do **not** add custom domains yet (Part 5).
5. Observability stays on for build and request errors.

Rollback of a bad Lovable push: Workers & Pages → `torus-mesh-site` → Deployments → pick the previous version → Rollback.

---

## Part 3. Terraform (recommended)

### 3.1 API token for Terraform

My Profile → API Tokens → Create token → **Custom token** `terraform-torus`:

| Scope | Permission | Level |
|---|---|---|
| Account | Cloudflare Tunnel | Edit |
| Account | Access: Apps and Policies | Edit |
| Account | Turnstile | Edit |
| Account | Workers R2 Storage | Edit |
| Account | Account Settings | Read |
| Zone (`torusmesh.com` only) | DNS | Edit |
| Zone | Zone Settings | Edit |
| Zone | Zone | Read |
| Zone | Dynamic Redirect (Single Redirect rules) | Edit |
| Zone | Zone WAF | Edit (phase 2) |

Permission names in the token UI change occasionally [VERIFY]; match by meaning. Set **Client IP Address Filtering** to your home and laptop public IPs if they are stable, and a **TTL** (for example 90 days, renewed). Store the token only in the password manager and export it as `CLOUDFLARE_API_TOKEN` in the shell session where you run Terraform. Never give it to Codex or put it in GitHub.

### 3.2 State backend in R2 (dashboard, once)

1. R2 → Create bucket `torus-tfstate` (location hint: North America).
2. R2 → Manage API tokens → Create token `tfstate-rw`: Object Read & Write, **specific bucket** `torus-tfstate`. Note the access key id and secret.
3. Export for Terraform sessions: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`.

### 3.3 Module layout (Codex writes; protected path `infra/cloudflare/`)

```
infra/cloudflare/
  versions.tf      terraform and provider version pins, backend
  providers.tf
  variables.tf     account_id, zone_id, zone_name, admin_email, access_team_domain (no defaults for ids)
  tunnel.tf        tunnel, tunnel config (ingress), token data source (sensitive output)
  dns.tf           tunnel CNAMEs (prevent_destroy)
  access.tf        policy + applications for ops and ssh
  (no turnstile.tf: the widget was created in the dashboard and stays unmanaged)
  r2.tf            torus-backups bucket (prevent_destroy)
  zone.tf          SSL strict, Always Use HTTPS, www → apex redirect ruleset
  outputs.tf       tunnel_id, ops_aud, turnstile_sitekey; tunnel_token (sensitive), turnstile_secret (sensitive)
  README.md        commands and the review gate
```

### 3.4 Reference Terraform (Codex must validate every attribute against the pinned provider docs; the v5 provider renamed many resources and some schemas change between minor versions)

```hcl
# versions.tf
terraform {
  required_version = ">= 1.9.0"
  required_providers {
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5.19"          # pin to the minor version you validated
    }
  }
  backend "s3" {
    bucket                      = "torus-tfstate"
    key                         = "cloudflare/terraform.tfstate"
    region                      = "auto"
    endpoints                   = { s3 = "https://<ACCOUNT_ID>.r2.cloudflarestorage.com" }
    skip_credentials_validation = true
    skip_region_validation      = true
    skip_requesting_account_id  = true
    skip_metadata_api_check     = true
    skip_s3_checksum            = true
    use_path_style              = true
  }
}

# providers.tf
provider "cloudflare" {}   # reads CLOUDFLARE_API_TOKEN from the environment

# tunnel.tf
resource "cloudflare_zero_trust_tunnel_cloudflared" "home" {
  account_id = var.account_id
  name       = "torus-home"
  config_src = "cloudflare"
}

data "cloudflare_zero_trust_tunnel_cloudflared_token" "home" {
  account_id = var.account_id
  tunnel_id  = cloudflare_zero_trust_tunnel_cloudflared.home.id
}

resource "cloudflare_zero_trust_tunnel_cloudflared_config" "home" {
  account_id = var.account_id
  tunnel_id  = cloudflare_zero_trust_tunnel_cloudflared.home.id
  config = {
    ingress = [
      { hostname = "ops.${var.zone_name}", service = "http://tis-api:8080" },
      { hostname = "ssh.${var.zone_name}", service = "ssh://host-gateway:22" },
      { service = "http_status:404" }
    ]
  }
}

# dns.tf
resource "cloudflare_dns_record" "ops" {
  zone_id = var.zone_id
  name    = "ops"
  type    = "CNAME"
  content = "${cloudflare_zero_trust_tunnel_cloudflared.home.id}.cfargotunnel.com"
  proxied = true
  ttl     = 1
  lifecycle { prevent_destroy = true }
}

resource "cloudflare_dns_record" "ssh" {
  zone_id = var.zone_id
  name    = "ssh"
  type    = "CNAME"
  content = "${cloudflare_zero_trust_tunnel_cloudflared.home.id}.cfargotunnel.com"
  proxied = true
  ttl     = 1
  lifecycle { prevent_destroy = true }
}

# access.tf
resource "cloudflare_zero_trust_access_policy" "admin_only" {
  account_id       = var.account_id
  name             = "Rehaan only"
  decision         = "allow"
  session_duration = "12h"
  include          = [{ email = { email = var.admin_email } }]
}

resource "cloudflare_zero_trust_access_application" "ops" {
  account_id       = var.account_id
  name             = "Torus ops"
  type             = "self_hosted"
  domain           = "ops.${var.zone_name}"
  session_duration = "12h"
  policies         = [{ id = cloudflare_zero_trust_access_policy.admin_only.id, precedence = 1 }]
}

resource "cloudflare_zero_trust_access_application" "ssh" {
  account_id       = var.account_id
  name             = "Torus SSH"
  type             = "self_hosted"
  domain           = "ssh.${var.zone_name}"
  session_duration = "12h"
  policies         = [{ id = cloudflare_zero_trust_access_policy.admin_only.id, precedence = 1 }]
}

# turnstile.tf (reference only; omit, because the widget already exists from the dashboard)
resource "cloudflare_turnstile_widget" "form" {
  account_id = var.account_id
  name       = "torus-mesh-form"
  domains    = [var.zone_name, "www.${var.zone_name}", "torus-mesh-site.<ACCOUNT_SUBDOMAIN>.workers.dev"]
  mode       = "managed"
  region     = "world"
}

# r2.tf
resource "cloudflare_r2_bucket" "backups" {
  account_id = var.account_id
  name       = "torus-backups"
  location   = "enam"
  lifecycle { prevent_destroy = true }
}

# zone.tf
resource "cloudflare_zone_setting" "ssl" {
  zone_id    = var.zone_id
  setting_id = "ssl"
  value      = "strict"
}

resource "cloudflare_zone_setting" "always_https" {
  zone_id    = var.zone_id
  setting_id = "always_use_https"
  value      = "on"
}

resource "cloudflare_ruleset" "redirects" {
  zone_id = var.zone_id
  name    = "canonical host"
  kind    = "zone"
  phase   = "http_request_dynamic_redirect"
  rules = [{
    ref         = "www_to_apex"
    description = "www to apex"
    expression  = "(http.host eq \"www.${var.zone_name}\")"
    action      = "redirect"
    action_parameters = {
      from_value = {
        status_code           = 301
        preserve_query_string = true
        target_url = { expression = "concat(\"https://${var.zone_name}\", http.request.uri.path)" }
      }
    }
  }]
}

# outputs.tf
output "tunnel_token" {
  value     = data.cloudflare_zero_trust_tunnel_cloudflared_token.home.token
  sensitive = true
}

output "ops_access_aud" {
  value = cloudflare_zero_trust_access_application.ops.aud
}

output "turnstile_sitekey" {
  value = cloudflare_turnstile_widget.form.sitekey
}

output "turnstile_secret" {
  value     = cloudflare_turnstile_widget.form.secret
  sensitive = true
}
```

**Codex tasks for M6** (in addition to the above): `terraform fmt`, `terraform validate` with the backend disabled in CI (`terraform init -backend=false`), `tflint`, a README with the exact command sequence in 3.5, and a check in `guard.py` that fails if any `cloudflare_dns_record` resource has a `type` of `MX` or `TXT`, or a name of `@` or `www`.

### 3.5 The apply workflow (Rehaan)

```bash
cd infra/cloudflare
export CLOUDFLARE_API_TOKEN=...           # from password manager, this shell only
export AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=...   # tfstate-rw
cat > terraform.tfvars <<'VARS'            # gitignored
account_id         = "..."
zone_id            = "..."
zone_name          = "torusmesh.com"
admin_email        = "rehaan@torusmesh.com"
access_team_domain = "torusmesh.cloudflareaccess.com"
VARS

terraform init
terraform plan -out plan.tfplan
terraform show -no-color plan.tfplan > plan.txt
```

1. Send `plan.txt` to Claude with the Terraform plan review prompt (`docs/VERIFICATION.md` 3.4). Sensitive outputs appear as `(sensitive value)`.
2. On PASS: `terraform apply plan.tfplan`.
3. Move the outputs into secrets, never into files in the repo:
   ```bash
   terraform output -raw tunnel_token      # paste into secrets/cloudflared.enc.env via sops as TUNNEL_TOKEN
   terraform output -raw turnstile_secret  # paste into secrets/tis.enc.env as TURNSTILE_SECRET_KEY
   terraform output ops_access_aud         # tis.env ACCESS_AUD (not secret)
   terraform output turnstile_sitekey      # admin settings security.turnstile_site_key (public)
   ```
4. `unset CLOUDFLARE_API_TOKEN AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY` and close the shell.

**Drift rule:** anything Terraform manages is changed only through Terraform. If you change it in the dashboard in an emergency, record it in `PROGRESS.md` and have Codex reconcile the code next.

### 3.6 SSH through Access (laptop, once)

```bash
# macOS
brew install cloudflared
# ~/.ssh/config
Host torus
  HostName ssh.torusmesh.com
  User <your-admin-user>
  ProxyCommand /opt/homebrew/bin/cloudflared access ssh --hostname %h
```

`ssh torus` opens a browser for Access login (one-time PIN to rehaan@torusmesh.com), then connects. The server's sshd still requires your SSH key.

---

## Part 4. Dashboard alternative (if not using Terraform)

Do these in order; each step names the equivalent Terraform resource so you can import later.

| # | Step | Where | Equivalent |
|---|---|---|---|
| 1 | **Tunnel:** Create tunnel → Cloudflared → name `torus-home` → choose **Docker** → copy only the token value from the shown command (do not run the command; the Compose stack runs cloudflared) | Zero Trust → Networks → Tunnels | `cloudflare_zero_trust_tunnel_cloudflared` |
| 2 | **Published application routes** on the tunnel: `ops.torusmesh.com` → HTTP `tis-api:8080`; `ssh.torusmesh.com` → SSH `host-gateway:22`. Cloudflare creates the proxied CNAMEs automatically | Tunnel → Published application routes | tunnel config + DNS |
| 3 | **Access policy** `Rehaan only`: Allow, Include → Emails → rehaan@torusmesh.com, session 12 hours | Zero Trust → Access → Policies | `cloudflare_zero_trust_access_policy` |
| 4 | **Access applications:** Self-hosted `Torus ops` for `ops.torusmesh.com`, and `Torus SSH` for `ssh.torusmesh.com`, each using the policy above. Copy the ops application's **Application Audience (AUD) tag** | Zero Trust → Access → Applications | `cloudflare_zero_trust_access_application` |
| 5 | **Turnstile widget** `torus-mesh-form`: hostnames `torusmesh.com`, `www.torusmesh.com`, the `workers.dev` site hostname; Managed mode. Copy site key and secret key | Turnstile | `cloudflare_turnstile_widget` |
| 6 | **R2 bucket** `torus-backups`; API token scoped to that bucket with Object Read & Write | R2 | `cloudflare_r2_bucket` |
| 7 | **SSL/TLS:** Full (strict); Edge Certificates → Always Use HTTPS on | Zone | `cloudflare_zone_setting` |
| 8 | **Redirect rule:** Rules → Redirect Rules → `www.torusmesh.com` → `https://torusmesh.com` + path, 301, preserve query string | Zone | `cloudflare_ruleset` |
| 9 | **Security:** Security → Bots → Bot Fight Mode on | Zone | (dashboard) |

After the dashboard path, secrets go into SOPS exactly as in 3.5 step 3.

---

## Part 5. Website cutover to Workers custom domains

Only after the Lovable final-message QA passes on the `workers.dev` URL.

1. Confirm you have the DNS export from Part 1.
2. DNS → delete **only** the Lovable web records for `@` and `www`. Leave MX, TXT (SPF, DKIM, DMARC, verification), and the tunnel CNAMEs untouched.
3. Workers & Pages → `torus-mesh-site` → Settings → Domains & Routes → **Add → Custom domain** → `torusmesh.com`. Repeat for `www.torusmesh.com` (the redirect rule sends it to the apex).
4. Wait for the certificates to show **Active** (usually minutes).
5. Lovable → project settings → Domains: remove the custom domain so Lovable hosting stops expecting it.
6. Verify:
   ```bash
   curl -sI https://torusmesh.com | head -5
   curl -sI https://www.torusmesh.com | grep -i location      # 301 to https://torusmesh.com/
   curl -s https://torusmesh.com/robots.txt
   dig +short MX torusmesh.com                                # unchanged
   ```
   Load `/`, `/audit`, `/book`; submit a test lead with `?utm_source=test`; confirm it reaches Zoho through `tis`.
7. **Rollback:** remove the Worker custom domains and re-add the saved Lovable records from the export (about 2 minutes).

---

## Part 6. Security checklist

| Item | Setting | Check |
|---|---|---|
| Account login | Passkey or hardware key | Profile → Authentication |
| API tokens | Scoped, TTL, IP filter where possible; no Global API Key use | My Profile → API Tokens |
| GitHub app access | Only the Lovable repo | GitHub → Settings → Applications |
| TLS | Full (strict), Always Use HTTPS, HSTS via the site's `_headers` | `curl -sI` shows `strict-transport-security` |
| Bot Fight Mode | On | Security → Bots |
| Turnstile | Widget limited to the site hostnames | Turnstile → widget settings |
| Access | Only Rehaan's email; no Bypass or Everyone rules; 12-hour sessions | Access → Applications |
| Tunnel | Only `ops` and `ssh` hostnames plus 404 catch-all | Tunnel → routes |
| Origin exposure | No A records pointing at the home IP anywhere | DNS records list |
| R2 | Buckets private; tokens bucket-scoped | R2 → bucket settings |

---

## Part 7. Post-setup verification

| # | Test | Pass when |
|---|---|---|
| C1 | `https://ops.torusmesh.com/ops/status` in a private window | Access login page appears; after PIN, JSON status loads |
| C2 | `curl -sI https://ops.torusmesh.com/ops/status` without login | 302 to `torusmesh.cloudflareaccess.com` |
| C3 | `ssh torus` | Access browser login, then SSH key auth |
| C4 | Stop `cloudflared` for 10 minutes | Better Stack H7 alerts; restart clears it |
| C5 | Lead form on production | Turnstile renders; lead syncs with `verified = true` |
| C6 | `dig torusmesh.com`, `dig ops.torusmesh.com` | Cloudflare proxied addresses only; no home IP |
| C7 | `terraform plan` a day later | No changes (no drift) |

---

## Part 8. Phase 2 additions (M8 Stripe webhooks)

| Addition | Detail |
|---|---|
| Tunnel route | `hooks.torusmesh.com` → `http://tis-api:8080` (before the 404 catch-all) |
| DNS | CNAME `hooks` to the tunnel |
| **No Access** on `hooks` | Stripe cannot log in; security is the Stripe signature check in `tis` plus WAF |
| WAF custom rule | Block any request to `hooks.torusmesh.com` unless `http.request.method eq "POST" and http.request.uri.path eq "/stripe"` (add `/zoho` in M12) |
| Rate limiting rule | `hooks.torusmesh.com/stripe`, modest per-IP limit within the plan's allowance |
| Token permission | Zone WAF Edit added to `terraform-torus` |

---

## Sources

- Cloudflare Tunnel with Terraform (v5 resources, remotely managed tunnels, token data source): developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/deployment-guides/terraform/
- Cloudflare Terraform provider v5 (`cloudflare_dns_record` and renamed resources): registry.terraform.io/providers/cloudflare/cloudflare/latest/docs; github.com/cloudflare/terraform-provider-cloudflare
- Workers static assets: developers.cloudflare.com/workers/static-assets/
