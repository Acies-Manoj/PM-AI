# ------------------------------------------------------------
# CG-style existing VPC mode
# Use this when CG provides an existing VPC and private subnets.
# This keeps the same app service configuration while reusing CG network.
# ------------------------------------------------------------

project     = "pmai"
environment = "UAT"
aws_region  = "CHANGE_ME_CG_REGION"

# If CG runs this via CI/CD/role, keep aws_profile empty.
aws_profile     = ""
assume_role_arn = "CHANGE_ME_OPTIONAL_CG_DEPLOY_ROLE_ARN_OR_EMPTY"

owner       = "CHANGE_ME_OWNER"
cost_center = "CHANGE_ME_COST_CENTER"
additional_tags = {
  Application        = "ProgramManagerAI"
  DataClassification = "CHANGE_ME"
  BusinessUnit       = "CHANGE_ME"
}

# CG provides VPC/subnet details. We do NOT create VPC in CG.
create_vpc      = false
existing_vpc_id = "CHANGE_ME_VPC_ID"

# Same approved private subnet list is used by:
# - API Gateway VPC Link
# - Internal ALB
# - ECS Fargate service
existing_private_subnet_ids = [
  "CHANGE_ME_PRIVATE_SUBNET_ID_A",
  "CHANGE_ME_PRIVATE_SUBNET_ID_B"
]

# Required only if /infra should create S3/DynamoDB gateway endpoints.
# If CG endpoints already exist, set enable_vpc_endpoints=false and leave this empty.
enable_vpc_endpoints             = false
existing_private_route_table_ids = []

# Usually app-specific security groups can be created.
# If CG gives existing SGs, set create_security_groups=false and fill IDs below.
create_security_groups             = true
existing_vpclink_security_group_id = ""
existing_alb_security_group_id     = ""
existing_ecs_security_group_id     = ""

# Backend sizing based on existing manual setup.
container_port = 8000
ecs_cpu        = 1024
ecs_memory     = 4096
image_tag      = "1.0.0"

# Recommended CG handoff flow:
# 1) First run with 0
# 2) Push image + add secrets
# 3) Change to 1 and run apply again
desired_count = 0

# Replace with CG Amplify/custom UAT frontend URL after frontend is known.
api_gateway_cors_allowed_origins = [
  "CHANGE_ME_FRONTEND_ORIGIN"
]

s3_cors_allowed_origins = [
  "CHANGE_ME_FRONTEND_ORIGIN"
]

# App resources: create unless CG gives existing resources.
create_ecr                 = true
create_s3_bucket           = true
create_dynamodb_tables     = true
create_iam_roles           = true
create_placeholder_secrets = true

# If CG gives existing ECR/S3/DDB/IAM/secrets, change the create_* toggles and fill the existing values.
existing_ecr_repository_url     = ""
existing_s3_bucket_name         = ""
existing_ecs_execution_role_arn = ""
existing_ecs_task_role_arn      = ""
permissions_boundary_arn        = ""

# Secret approach.
# If Bedrock replaces OpenRouter completely, set enable_openrouter=false.
enable_openrouter     = false
openrouter_secret_arn = ""
enable_deepl          = false
deepl_secret_arn      = ""

# Bedrock + Translate.
enable_bedrock   = true
enable_translate = true
bedrock_model_id = "CHANGE_ME_CG_APPROVED_BEDROCK_MODEL_ID"
bedrock_model_arns = [
  "CHANGE_ME_CG_APPROVED_BEDROCK_MODEL_ARN_OR_STAR_FOR_INITIAL_TEST"
]

# API sign-in (Microsoft Entra). Required when AWS storage is on, unless allow_anon = true.
# Keep allow_anon = false for CG.
allow_anon      = false
entra_tenant_id = "CHANGE_ME_ENTRA_TENANT_ID"
entra_client_id = "CHANGE_ME_ENTRA_API_CLIENT_ID"

# Amplify. Enable after repo details/access are ready.
enable_amplify         = true
amplify_repository_url = "CHANGE_ME_REPO_URL"
amplify_branch_name    = "CHANGE_ME_BRANCH_NAME"
