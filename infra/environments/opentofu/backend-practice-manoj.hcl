# Remote state for the "practice-manoj" environment (existing VPC).
# The bucket name and, locally, the AWS profile are passed at init time, not stored here:
#   tofu init -backend-config=environments/opentofu/backend-practice-manoj.hcl -backend-config="bucket=<state bucket>" -backend-config="profile=<aws profile>"
# One key per environment, so two environments never share a state.
key          = "pmai/practice-manoj/tofu.tfstate"
region       = "eu-north-1"
encrypt      = true
use_lockfile = true
