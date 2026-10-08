terraform {
  required_version = ">= 1.8.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  # For CG/UAT, configure remote state with backend.hcl instead of keeping local state.
  # Example command:
  # tofu init -backend-config=environments/opentofu/backend.hcl
  #
  # backend "s3" {}
}
