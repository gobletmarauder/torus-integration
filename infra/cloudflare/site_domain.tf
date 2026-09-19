resource "cloudflare_workers_custom_domain" "apex" {
  count = var.enable_site_custom_domain ? 1 : 0

  account_id = var.account_id
  zone_id    = var.zone_id
  hostname   = var.zone_name
  service    = var.worker_name
}

resource "cloudflare_workers_custom_domain" "www" {
  count = var.enable_site_custom_domain ? 1 : 0

  account_id = var.account_id
  zone_id    = var.zone_id
  hostname   = "www.${var.zone_name}"
  service    = var.worker_name
}
