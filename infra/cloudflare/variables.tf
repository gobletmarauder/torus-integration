variable "account_id" {
  description = "Cloudflare account identifier."
  type        = string
  sensitive   = true
  nullable    = false
}

variable "zone_id" {
  description = "Cloudflare zone identifier."
  type        = string
  sensitive   = true
  nullable    = false
}

variable "zone_name" {
  description = "Cloudflare zone name."
  type        = string
  nullable    = false
}

variable "admin_email" {
  description = "The sole identity permitted by Cloudflare Access."
  type        = string
  sensitive   = true
  nullable    = false
}

variable "worker_name" {
  description = "Existing Cloudflare Worker service name used for optional custom domains."
  type        = string
  nullable    = false
}

variable "site_hostnames" {
  description = "Hostnames accepted by the existing Turnstile widget."
  type        = list(string)
  nullable    = false
}

variable "ops_hostname" {
  description = "Protected operations hostname routed through the tunnel."
  type        = string
  nullable    = false
}

variable "ssh_hostname" {
  description = "Protected SSH hostname routed through the tunnel."
  type        = string
  nullable    = false
}

variable "turnstile_sitekey" {
  description = "Public sitekey of the existing torus-mesh-form Turnstile widget."
  type        = string
  nullable    = false
}

variable "enable_site_custom_domain" {
  description = "Opt in to managing the existing Worker's apex and www custom domains."
  type        = bool
  default     = false
}
