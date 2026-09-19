resource "cloudflare_turnstile_widget" "form" {
  account_id = var.account_id
  name       = "torus-mesh-form"
  mode       = "managed"
  domains    = distinct(concat([var.zone_name, "www.${var.zone_name}"], var.site_hostnames))

  lifecycle {
    prevent_destroy = true
  }
}

import {
  to = cloudflare_turnstile_widget.form
  id = "${var.account_id}/${var.turnstile_sitekey}"
}
