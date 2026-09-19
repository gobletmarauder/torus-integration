resource "cloudflare_zone_setting" "ssl" {
  zone_id    = var.zone_id
  setting_id = "ssl"
  value      = "strict"
}

resource "cloudflare_zone_setting" "always_use_https" {
  zone_id    = var.zone_id
  setting_id = "always_use_https"
  value      = "on"
}

resource "cloudflare_ruleset" "www_redirect" {
  zone_id     = var.zone_id
  name        = "Redirect www to apex"
  description = "Canonicalize the website hostname."
  kind        = "zone"
  phase       = "http_request_dynamic_redirect"

  rules = [
    {
      action      = "redirect"
      description = "Redirect www to apex"
      enabled     = true
      expression  = "(http.host eq \"www.${var.zone_name}\")"
      action_parameters = {
        from_value = {
          status_code = 301
          target_url = {
            expression = "concat(\"https://\", \"${var.zone_name}\", http.request.uri.path)"
          }
          preserve_query_string = true
        }
      }
    },
  ]
}
