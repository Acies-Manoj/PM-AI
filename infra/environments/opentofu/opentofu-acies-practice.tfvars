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

# First apply: keep 0 until ECR image + secret values are ready.
# After pushing image and adding secret values, set this to 1 and apply again.
desired_count = 1

# Frontend/API CORS. Add Amplify URL after it is created.
api_gateway_cors_allowed_origins = [
  "http://localhost:5173",
  "https://enhanced-with-agents.d1hpje21fp462y.amplifyapp.com"
]

s3_cors_allowed_origins = [
  "http://localhost:5173",
  "https://enhanced-with-agents.d1hpje21fp462y.amplifyapp.com"
]

# ECR / app resources are created by OpenTofu.
create_ecr                = true
ecr_image_retention_count = 10
ecr_image_tag_mutability  = "MUTABLE"

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

# Amplify is part of target architecture, but enable only after repo URL/access is ready.
enable_amplify         = true
amplify_repository_url = "https://github.com/acies-Thakshana/PM-AI"
amplify_branch_name    = "enhanced-with-agents"
