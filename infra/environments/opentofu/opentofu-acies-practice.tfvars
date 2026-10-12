# ------------------------------------------------------------
# Acies practice mode
# This creates a fresh VPC and fresh app resources for learning.
# Do NOT use this file directly for CG unless CG approves VPC creation.
# ------------------------------------------------------------

project     = "pmai"
environment = "opentofu"
aws_region  = "eu-north-1"

# For local practice only. Replace with your AWS CLI/SSO profile name.
# For CI/CD or CG platform-run execution, leave aws_profile empty and use role-based auth.
aws_profile     = "rishikesh"
assume_role_arn = ""

owner       = "pmai-team"
cost_center = "pmai-practice"
additional_tags = {
  Application        = "ProgramManagerAI"
  DataClassification = "Internal"
}

# Create a new practice VPC similar to the manual E2E setup.
create_vpc           = true
vpc_cidr             = "10.0.0.0/16"
public_subnet_cidrs  = ["10.0.0.0/24", "10.0.1.0/24"]
private_subnet_cidrs = ["10.0.10.0/24", "10.0.11.0/24"]
enable_vpc_endpoints = true

# Create app-specific security groups.
create_security_groups = true
allowed_egress_cidrs   = ["0.0.0.0/0"]

# Backend sizing based on the manual ECS/Fargate setup.
container_port = 8000
ecs_cpu        = 1024
ecs_memory     = 4096
image_tag      = "1.1.0"

# 1-step method: start 1 container straight away. The ECR repo is empty during the apply, so
# the container cannot start until you push image_tag; push it, then force a new deployment.
# (3-step method: set 0 here, push the image, then set 1 and apply again.)
desired_count = 1

# CORS: the Amplify URL is added automatically (locals.tf). Only list EXTRA origins here.
extra_cors_origins = ["http://localhost:5173"]

# ECR / app resources are created by OpenTofu.
create_ecr                = true
ecr_image_retention_count = 10
ecr_image_tag_mutability  = "MUTABLE"

# Practice only: let `tofu destroy` delete the ECR repo and S3 bucket even when they hold data.
# Apply once with these set to true BEFORE running `tofu destroy`.
ecr_force_delete = true
s3_force_destroy = true

create_s3_bucket           = true
create_dynamodb_tables     = true
create_iam_roles           = true
create_placeholder_secrets = true

# Current backend can keep OpenRouter wiring for practice.
# If you fully move to Bedrock, set enable_openrouter=false and update backend code accordingly.
enable_openrouter = false
enable_deepl      = false

# Bedrock + Translate added for the new version.
enable_bedrock     = true
enable_translate   = true
bedrock_model_id   = "openai.gpt-oss-20b-1:0"
bedrock_model_arns = ["*"]

# API sign-in. With AWS storage on, the backend needs Entra OR allow_anon.
# Practice only: no sign-in. For a client environment set the two Entra IDs instead.
allow_anon      = true
entra_tenant_id = ""
entra_client_id = ""

# Amplify is part of target architecture, but enable only after repo URL/access is ready.
enable_amplify         = true
amplify_repository_url = "https://github.com/acies-Thakshana/PM-AI"
amplify_branch_name    = "enhanced-with-agents"

# Bedrock Prompt Management ids (from: python scripts/bedrock_prompts.py create).
# Without these the backend answers 503 "No system prompt for 'planner_agent'".
bedrock_prompt_ids = {
  planner_agent                    = "8DBE2WI9FO:1",
  drilldown_path                   = "6UL0FSAT59:1",
  feature_agent_think              = "2IM936UH9P:1",
  feature_agent_write_code         = "A2FYQ8K4CG:1",
  feature_agent_validate           = "PUFTNPNB54:1",
  feature_suggester                = "H3EPIZ7NIP:1",
  analysis_agent_think             = "N8HR6ATR60:1",
  analysis_agent_write_code        = "Q2Q371FEKT:1",
  analysis_agent_chart_suggestion  = "EC7LSY02QR:1",
  analysis_agent_interpret         = "FSZC2XYIGR:1",
  analysis_agent_drilldown         = "HPLYFJOPF7:1",
  analysis_designer_template_match = "SP5RSZVKJ0:1",
  analysis_designer_chart          = "NSE77L2OQI:1",
  analysis_suggester               = "T55QEVWPGQ:1",
  drilldown_agent                  = "L9OOWU040Z:1",
  drilldown_agent_more             = "KQHBQPEJVZ:1",
  audit_agent                      = "BBEA7GIIBA:1",
  overall_analysis_agent           = "WQLYTHR71Q:1",
  report_final_summary_agent       = "908YYO0K5S:1"
}
