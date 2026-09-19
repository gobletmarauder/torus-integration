resource "cloudflare_r2_bucket" "backups" {
  account_id = var.account_id
  name       = "torus-backups"
  location   = "ENAM"

  lifecycle {
    prevent_destroy = true
  }
}
