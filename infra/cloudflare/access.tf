resource "cloudflare_zero_trust_access_policy" "ops_admin" {
  account_id       = var.account_id
  name             = "Torus operations admin"
  decision         = "allow"
  session_duration = "12h"

  include = [
    {
      email = {
        email = var.admin_email
      }
    },
  ]
}

resource "cloudflare_zero_trust_access_application" "ops" {
  account_id       = var.account_id
  name             = "Torus operations"
  domain           = var.ops_hostname
  type             = "self_hosted"
  session_duration = "12h"

  policies = [
    {
      id         = cloudflare_zero_trust_access_policy.ops_admin.id
      precedence = 1
    },
  ]
}

resource "cloudflare_zero_trust_access_policy" "ssh_admin" {
  account_id       = var.account_id
  name             = "Torus SSH admin"
  decision         = "allow"
  session_duration = "12h"

  include = [
    {
      email = {
        email = var.admin_email
      }
    },
  ]
}

resource "cloudflare_zero_trust_access_application" "ssh" {
  account_id       = var.account_id
  name             = "Torus SSH"
  domain           = var.ssh_hostname
  type             = "self_hosted"
  session_duration = "12h"

  policies = [
    {
      id         = cloudflare_zero_trust_access_policy.ssh_admin.id
      precedence = 1
    },
  ]
}
