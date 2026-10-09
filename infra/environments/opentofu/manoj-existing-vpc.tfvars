# ------------------------------------------------------------
# Manoj practice: existing VPC mode, in the Acies account
# Reuses the existing VPC "pm ai-vpc" instead of creating one, the same
# way a client environment with a provided VPC works. Practice only.
# Keep a separate state from the other practice file.
# ------------------------------------------------------------

project     = "pmai"
environment = "practice-manoj"
aws_region  = "eu-north-1"

# Local CLI runs use the profile. In a GitHub Actions run, override with
# -var 'aws_profile=' so the role from OIDC is used instead.
aws_profile     = "manoj"
assume_role_arn = ""

owner       = "pmai-manoj"
cost_center = "pmai-team"
additional_tags = {
  Application        = "ProgramManagerAI"
  DataClassification = "Internal"
}

# Existing VPC "pm ai-vpc" (10.0.0.0/16). We do NOT create a VPC.
create_vpc      = false
existing_vpc_id = "vpc-07409b0b668f5756c"

# Private subnets (default route goes to the NAT), in eu-north-1a and eu-north-1b.
# Used by the API Gateway VPC Link, the internal ALB and the ECS service.
existing_private_subnet_ids = [
  "subnet-0b0228d376bb4aac2",
  "subnet-03a42560b833c149f"
]

# The VPC already has S3 and DynamoDB gateway endpoints on the private route tables.
enable_vpc_endpoints             = false
existing_private_route_table_ids = []

# Create app-specific security groups inside the existing VPC.
create_security_groups = true
allowed_egress_cidrs   = ["0.0.0.0/0"]

# Backend sizing.
container_port = 8000
ecs_cpu        = 1024
ecs_memory     = 4096
image_tag      = "1.1.0"

# First apply: keep 0 until the image is pushed to ECR.
# Then set to 1 and apply again.
desired_count = 1

# Frontend/API CORS. Add the Amplify branch URL after the app is created:
# https://<branch>.<amplify id>.amplifyapp.com
api_gateway_cors_allowed_origins = [
  "http://localhost:5173","https://enhanced-with-agents-infra.dp7wiuaiiygwo.amplifyapp.com"
]

s3_cors_allowed_origins = [
  "http://localhost:5173","https://enhanced-with-agents-infra.dp7wiuaiiygwo.amplifyapp.com"
]

# App resources created by OpenTofu.
create_ecr                = true
ecr_repository_name       = "pmai/backend-practice-manoj"
ecr_image_retention_count = 10
ecr_image_tag_mutability  = "MUTABLE"

# Practice only: let `tofu destroy` delete the ECR repo and S3 bucket even when they hold data.
ecr_force_delete = true
s3_force_destroy = true

create_s3_bucket           = true
create_dynamodb_tables     = true
create_iam_roles           = true
create_placeholder_secrets = true

enable_openrouter = false
enable_deepl      = false

# Bedrock + Translate.
enable_bedrock     = true
enable_translate   = true
bedrock_model_id   = "openai.gpt-oss-20b-1:0"
bedrock_model_arns = ["*"]

# API sign-in. Practice only: no sign-in. For a client environment set allow_anon = false and the Entra ids.
allow_anon      = true
entra_tenant_id = ""
entra_client_id = ""

# Amplify builds from the fork. The Amplify GitHub App must be authorised on that account
# ("Update required" in the Amplify console) before the first build.
enable_amplify         = true
amplify_repository_url = "https://github.com/Acies-Manoj/PM-AI"
amplify_branch_name    = "enhanced-with-agents-infra"

# Bedrock Prompt Management ids (created earlier with: python scripts/bedrock_prompts.py create).
# They live outside OpenTofu and survive `tofu destroy`.
bedrock_prompt_ids = {
  planner_agent                    = "8DBE2WI9FO:1"
  drilldown_path                   = "6UL0FSAT59:1"
  feature_agent_think              = "2IM936UH9P:1"
  feature_agent_write_code         = "A2FYQ8K4CG:1"
  feature_agent_validate           = "PUFTNPNB54:1"
  feature_suggester                = "H3EPIZ7NIP:1"
  analysis_agent_think             = "N8HR6ATR60:1"
  analysis_agent_write_code        = "Q2Q371FEKT:1"
  analysis_agent_chart_suggestion  = "EC7LSY02QR:1"
  analysis_agent_interpret         = "FSZC2XYIGR:1"
  analysis_agent_drilldown         = "HPLYFJOPF7:1"
  analysis_designer_template_match = "SP5RSZVKJ0:1"
  analysis_designer_chart          = "NSE77L2OQI:1"
  analysis_suggester               = "T55QEVWPGQ:1"
  drilldown_agent                  = "L9OOWU040Z:1"
  drilldown_agent_more             = "KQHBQPEJVZ:1"
  audit_agent                      = "BBEA7GIIBA:1"
  overall_analysis_agent           = "WQLYTHR71Q:1"
  report_final_summary_agent       = "908YYO0K5S:1"
}
