resource "cloudflare_dns_record" "ops" {
  zone_id = var.zone_id
  name    = var.ops_hostname
  type    = "CNAME"
  content = "${cloudflare_zero_trust_tunnel_cloudflared.home.id}.cfargotunnel.com"
  ttl     = 1
  proxied = true

  lifecycle {
    prevent_destroy = true
  }
}

resource "cloudflare_dns_record" "ssh" {
  zone_id = var.zone_id
  name    = var.ssh_hostname
  type    = "CNAME"
  content = "${cloudflare_zero_trust_tunnel_cloudflared.home.id}.cfargotunnel.com"
  ttl     = 1
  proxied = true

  lifecycle {
    prevent_destroy = true
  }
}
