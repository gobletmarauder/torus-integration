resource "cloudflare_zero_trust_tunnel_cloudflared" "home" {
  account_id = var.account_id
  name       = "torus-home"
  config_src = "cloudflare"
}

resource "cloudflare_zero_trust_tunnel_cloudflared_config" "home" {
  account_id = var.account_id
  tunnel_id  = cloudflare_zero_trust_tunnel_cloudflared.home.id

  config = {
    ingress = [
      {
        hostname = var.ops_hostname
        service  = "http://tis-api:8080"
      },
      {
        hostname = var.ssh_hostname
        service  = "ssh://host-gateway:22"
      },
      {
        service = "http_status:404"
      },
    ]
  }
}

data "cloudflare_zero_trust_tunnel_cloudflared_token" "home" {
  account_id = var.account_id
  tunnel_id  = cloudflare_zero_trust_tunnel_cloudflared.home.id
}
