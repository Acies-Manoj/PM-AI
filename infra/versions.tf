terraform {
  required_version = ">= 1.8.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  # State lives in S3 so the GitHub Actions pipeline and a laptop share one copy.
  # The bucket name is not stored in git: pass it at init, for example locally:
  #   tofu init -backend-config=environments/opentofu/backend-practice-manoj.hcl ^
  #             -backend-config="bucket=<state bucket>" -backend-config="profile=<aws profile>"
  # In CI the workflow passes the bucket from a GitHub variable and uses the OIDC role.
  backend "s3" {}
}
