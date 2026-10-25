terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Bucket/key/region are passed with -backend-config (see .github/workflows/infra.yml).
  backend "s3" {}
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project   = "transit-buddy"
      ManagedBy = "terraform"
    }
  }
}
