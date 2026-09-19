terraform {
  required_version = "= 1.14.6"

  required_providers {
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "= 5.25.0"
    }
  }

  backend "s3" {
    bucket                      = "torus-tfstate"
    key                         = "cloudflare/terraform.tfstate"
    region                      = "auto"
    use_path_style              = true
    skip_credentials_validation = true
    skip_region_validation      = true
    skip_requesting_account_id  = true
    skip_metadata_api_check     = true
    skip_s3_checksum            = true
  }
}
