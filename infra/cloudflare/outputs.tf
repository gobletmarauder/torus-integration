output "tunnel_id" {
  description = "Identifier of the managed home tunnel."
  value       = cloudflare_zero_trust_tunnel_cloudflared.home.id
}

output "tunnel_token" {
  description = "Token consumed by cloudflared on the home server."
  value       = data.cloudflare_zero_trust_tunnel_cloudflared_token.home.token
  sensitive   = true
}

output "ops_access_aud" {
  description = "Cloudflare Access audience for the operations application."
  value       = cloudflare_zero_trust_access_application.ops.aud
}

output "turnstile_sitekey" {
  description = "Public Turnstile widget sitekey."
  value       = cloudflare_turnstile_widget.form.sitekey
}

output "turnstile_secret" {
  description = "Turnstile widget secret if the provider exposes it after import."
  value       = cloudflare_turnstile_widget.form.secret
  sensitive   = true
}
