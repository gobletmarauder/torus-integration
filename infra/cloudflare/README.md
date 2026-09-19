# Cloudflare infrastructure

This module is deliberately separated from application deployment. It manages the M6 Cloudflare resources only. It must never manage MX, TXT, NS, CAA, apex, or `www` DNS records. The optional Workers custom-domain resources use the Workers API and are disabled by default.

## Manual prerequisites

- Confirm the existing R2 bucket `torus-tfstate` exists. This module intentionally does not manage it.
- Create `infra/cloudflare/terraform.tfvars` locally with values for every variable that has no default. Do not commit that file.
- Export Cloudflare provider authentication and R2 backend credentials through their documented environment variable names. Never put credentials in Terraform files, tfvars, command lines, logs, or pull requests.
- Set `AWS_ENDPOINT_URL_S3` to the account-specific R2 S3 endpoint before backend initialization.
- Install Terraform 1.14.6 and TFLint 0.64.0.

The `torus-mesh-form` Turnstile widget already exists. Its import block uses `account_id/turnstile_sitekey`, so the first reviewed plan must show an import rather than a create. If the provider does not return its secret after import, retrieve the secret manually in the Cloudflare dashboard; never store it in this repository.

## Human-only execution

Codex may run formatting, linting, `terraform init -backend=false`, and validation. A human infra execution session supplies credentials and runs:

1. `make tf-init`
2. `make tf-plan`
3. Review `infra/cloudflare/plan.txt`, confirm the Turnstile import, and obtain the independent Claude review required by `docs/INFRA-EXECUTION.md`.
4. `make tf-gate`
5. `make tf-apply`

`make tf-apply` reruns the safety gate and applies only the saved plan. Never run an unsaved or unreviewed plan.
