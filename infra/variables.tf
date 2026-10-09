# -----------------------------
# Global / environment
# -----------------------------
variable "project" {
  description = "Short project name used in resource names."
  type        = string
  default     = "pmai"
}

variable "environment" {
  description = "Environment name. Requested value for this handoff is opentofu."
  type        = string
  default     = "opentofu"
}

variable "aws_region" {
  description = "AWS region where resources are deployed."
  type        = string
  default     = "eu-north-1"
}

variable "aws_profile" {
  description = "Local AWS CLI profile. Leave empty when CG runs through CI/CD or an assumed role."
  type        = string
  default     = ""
}

variable "assume_role_arn" {
  description = "Optional role ARN for OpenTofu to assume. Usually used in client/CI environments."
  type        = string
  default     = ""
}

variable "owner" {
  description = "Resource owner tag."
  type        = string
  default     = "pmai-team"
}

variable "cost_center" {
  description = "Cost center tag. Replace with CG/Acies approved value."
  type        = string
  default     = "pmai"
}

variable "additional_tags" {
  description = "Extra tags required by the client/platform team."
  type        = map(string)
  default     = {}
}

# -----------------------------
# Network / VPC
# -----------------------------
variable "create_vpc" {
  description = "true = create a new VPC for Acies practice; false = use existing VPC/subnets, expected for CG."
  type        = bool
  default     = true
}

variable "vpc_cidr" {
  description = "CIDR for newly-created practice VPC. Ignored when create_vpc=false."
  type        = string
  default     = "10.0.0.0/16"
}

variable "public_subnet_cidrs" {
  description = "Public subnet CIDRs for practice VPC. Ignored when create_vpc=false."
  type        = list(string)
  default     = ["10.0.0.0/24", "10.0.1.0/24"]
}

variable "private_subnet_cidrs" {
  description = "Private subnet CIDRs for practice VPC. Ignored when create_vpc=false."
  type        = list(string)
  default     = ["10.0.10.0/24", "10.0.11.0/24"]
}

variable "existing_vpc_id" {
  description = "Existing CG VPC ID when create_vpc=false."
  type        = string
  default     = ""
}

variable "existing_private_subnet_ids" {
  description = "Existing private subnet IDs for API Gateway VPC Link, internal ALB, and ECS when create_vpc=false."
  type        = list(string)
  default     = []
}

variable "existing_private_route_table_ids" {
  description = "Private route table IDs for S3/DynamoDB VPC endpoints when create_vpc=false and enable_vpc_endpoints=true."
  type        = list(string)
  default     = []
}

variable "enable_vpc_endpoints" {
  description = "Create S3 and DynamoDB gateway VPC endpoints for private access. Disable if CG already provides them."
  type        = bool
  default     = true
}

# -----------------------------
# Security groups
# -----------------------------
variable "create_security_groups" {
  description = "true = create app security groups; false = use existing CG-provided security groups."
  type        = bool
  default     = true
}

variable "existing_vpclink_security_group_id" {
  description = "Existing security group for API Gateway VPC Link when create_security_groups=false."
  type        = string
  default     = ""
}

variable "existing_alb_security_group_id" {
  description = "Existing security group for internal ALB when create_security_groups=false."
  type        = string
  default     = ""
}

variable "existing_ecs_security_group_id" {
  description = "Existing security group for ECS tasks when create_security_groups=false."
  type        = string
  default     = ""
}

variable "allowed_egress_cidrs" {
  description = "Outbound CIDRs for created security groups. CG may restrict this."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

# -----------------------------
# Backend container / ECS
# -----------------------------
variable "container_port" {
  description = "FastAPI backend container port."
  type        = number
  default     = 8000
}

variable "image_tag" {
  description = "Backend Docker image tag used by ECS."
  type        = string
  default     = "1.0.0"
}

variable "ecs_cpu" {
  description = "Fargate task CPU units. 1024 = 1 vCPU."
  type        = number
  default     = 1024
}

variable "ecs_memory" {
  description = "Fargate task memory in MiB."
  type        = number
  default     = 4096
}

variable "desired_count" {
  description = "Number of ECS backend tasks. Keep 0 for first apply; set 1 after image/secrets are ready."
  type        = number
  default     = 0
}

variable "cpu_architecture" {
  description = "Container CPU architecture. Use X86_64 if Docker image was built on a normal Windows/Intel machine."
  type        = string
  default     = "X86_64"

  validation {
    condition     = contains(["X86_64", "ARM64"], var.cpu_architecture)
    error_message = "cpu_architecture must be X86_64 or ARM64."
  }
}

variable "enable_container_insights" {
  description = "Enable ECS container insights."
  type        = bool
  default     = true
}

variable "log_retention_days" {
  description = "CloudWatch log retention in days."
  type        = number
  default     = 14
}

# -----------------------------
# ALB / target group
# -----------------------------
variable "alb_idle_timeout_seconds" {
  description = "Internal ALB idle timeout."
  type        = number
  default     = 300
}

variable "alb_listener_protocol" {
  description = "Internal ALB listener protocol. HTTP is aligned to the current setup; use HTTPS only if CG requires it."
  type        = string
  default     = "HTTP"

  validation {
    condition     = contains(["HTTP", "HTTPS"], var.alb_listener_protocol)
    error_message = "alb_listener_protocol must be HTTP or HTTPS."
  }
}

variable "alb_listener_port" {
  description = "Internal ALB listener port."
  type        = number
  default     = 80
}

variable "alb_certificate_arn" {
  description = "ACM certificate ARN if alb_listener_protocol=HTTPS."
  type        = string
  default     = ""
}

variable "health_check_path" {
  description = "ALB health check path. The backend must return 200 here."
  type        = string
  default     = "/health"
}

variable "health_check_matcher" {
  description = "Expected success code for target group health check."
  type        = string
  default     = "200"
}

variable "health_check_interval_seconds" {
  description = "Target group health check interval."
  type        = number
  default     = 30
}

variable "health_check_timeout_seconds" {
  description = "Target group health check timeout."
  type        = number
  default     = 5
}

variable "health_check_healthy_threshold" {
  description = "Successful health checks before target is healthy."
  type        = number
  default     = 2
}

variable "health_check_unhealthy_threshold" {
  description = "Failed health checks before target is unhealthy."
  type        = number
  default     = 3
}

# -----------------------------
# API Gateway
# -----------------------------
variable "api_gateway_cors_allowed_origins" {
  description = "Allowed browser origins for API Gateway CORS. Replace with Amplify/custom frontend URL."
  type        = list(string)
  default     = ["http://localhost:5173"]
}

variable "api_gateway_timeout_ms" {
  description = "API Gateway integration timeout in milliseconds. HTTP API maximum is 30000 ms."
  type        = number
  default     = 30000
}

variable "api_gateway_cors_max_age_seconds" {
  description = "API Gateway CORS preflight cache seconds."
  type        = number
  default     = 300
}

# -----------------------------
# ECR
# -----------------------------
variable "create_ecr" {
  description = "true = create ECR repository; false = use existing_ecr_repository_url."
  type        = bool
  default     = true
}

variable "existing_ecr_repository_url" {
  description = "Existing ECR repository URL when create_ecr=false."
  type        = string
  default     = ""
}

variable "ecr_repository_name" {
  description = "ECR repository name when create_ecr=true. Empty uses project/backend."
  type        = string
  default     = ""
}

variable "ecr_image_retention_count" {
  description = "Number of recent ECR images to retain."
  type        = number
  default     = 10
}

variable "ecr_force_delete" {
  description = "true = `tofu destroy` also deletes the repo with its images inside. Practice/dev only; keep false for prod. Must be applied once BEFORE the destroy."
  type        = bool
  default     = false
}

variable "ecr_image_tag_mutability" {
  description = "ECR image tag mutability. MUTABLE is easier for practice; IMMUTABLE is better for prod."
  type        = string
  default     = "MUTABLE"

  validation {
    condition     = contains(["MUTABLE", "IMMUTABLE"], var.ecr_image_tag_mutability)
    error_message = "ecr_image_tag_mutability must be MUTABLE or IMMUTABLE."
  }
}

# -----------------------------
# IAM
# -----------------------------
variable "create_iam_roles" {
  description = "true = create ECS execution/task roles; false = use existing role ARNs."
  type        = bool
  default     = true
}

variable "existing_ecs_execution_role_arn" {
  description = "Existing ECS execution role ARN when create_iam_roles=false."
  type        = string
  default     = ""
}

variable "existing_ecs_task_role_arn" {
  description = "Existing ECS application task role ARN when create_iam_roles=false."
  type        = string
  default     = ""
}

variable "permissions_boundary_arn" {
  description = "Optional IAM permissions boundary ARN for roles created by this infra."
  type        = string
  default     = ""
}

# -----------------------------
# Secrets
# -----------------------------
variable "create_placeholder_secrets" {
  description = "true = create empty secret containers. Secret VALUES must be inserted separately, not in OpenTofu."
  type        = bool
  default     = true
}

variable "enable_openrouter" {
  description = "Enable OpenRouter secret/env wiring. Set false if Bedrock fully replaces OpenRouter."
  type        = bool
  default     = true
}

variable "openrouter_secret_arn" {
  description = "Existing OpenRouter secret ARN when create_placeholder_secrets=false."
  type        = string
  default     = ""
}

variable "enable_deepl" {
  description = "Enable DeepL secret/env wiring. Set false if Amazon Translate replaces DeepL."
  type        = bool
  default     = false
}

variable "deepl_secret_arn" {
  description = "Existing DeepL secret ARN when enable_deepl=true and create_placeholder_secrets=false."
  type        = string
  default     = ""
}

# -----------------------------
# Bedrock / Translate
# -----------------------------
variable "enable_bedrock" {
  description = "Enable Bedrock environment variables and IAM permissions."
  type        = bool
  default     = true
}

variable "bedrock_model_id" {
  description = "Bedrock model ID used by the backend. Replace with CG-approved model."
  type        = string
  default     = "anthropic.claude-3-5-sonnet-20240620-v1:0"
}

variable "bedrock_model_arns" {
  description = "Allowed Bedrock model ARNs for IAM. Use specific ARNs when CG provides them; '*' is easiest for practice."
  type        = list(string)
  default     = ["*"]
}

variable "enable_translate" {
  description = "Allow backend to call Amazon Translate."
  type        = bool
  default     = true
}

# -----------------------------
# API sign-in (read by the backend as ENTRA_TENANT_ID / ENTRA_CLIENT_ID / ALLOW_ANON)
# With AWS storage on, the backend refuses requests unless Entra is set or allow_anon = true.
# -----------------------------
variable "entra_tenant_id" {
  description = "Microsoft Entra tenant ID. Set together with entra_client_id to require sign-in. Empty = not set."
  type        = string
  default     = ""
}

variable "entra_client_id" {
  description = "Microsoft Entra API app (client) ID. Set together with entra_tenant_id. Empty = not set."
  type        = string
  default     = ""
}

variable "allow_anon" {
  description = "true = run the API without sign-in (ALLOW_ANON=1). Practice only; leave false for client environments."
  type        = bool
  default     = false
}

# -----------------------------
# S3
# -----------------------------
variable "create_s3_bucket" {
  description = "true = create app data bucket; false = use existing_s3_bucket_name."
  type        = bool
  default     = true
}

variable "existing_s3_bucket_name" {
  description = "Existing app data S3 bucket name when create_s3_bucket=false."
  type        = string
  default     = ""
}

variable "s3_force_destroy" {
  description = "true = `tofu destroy` also deletes every object and version in the bucket. Practice/dev only; keep false for prod. Must be applied once BEFORE the destroy."
  type        = bool
  default     = false
}

variable "s3_bucket_name" {
  description = "Bucket name when create_s3_bucket=true. Empty generates pmai-opentofu-data-account-region."
  type        = string
  default     = ""
}

variable "s3_encryption_type" {
  description = "S3 server-side encryption type."
  type        = string
  default     = "AES256"

  validation {
    condition     = contains(["AES256", "aws:kms"], var.s3_encryption_type)
    error_message = "s3_encryption_type must be AES256 or aws:kms."
  }
}

variable "kms_key_arn" {
  description = "KMS key ARN when s3_encryption_type=aws:kms."
  type        = string
  default     = ""
}

variable "s3_cors_allowed_origins" {
  description = "Allowed browser origins for S3 direct upload/download."
  type        = list(string)
  default     = ["http://localhost:5173"]
}

variable "s3_cors_max_age_seconds" {
  description = "S3 CORS max age seconds."
  type        = number
  default     = 3000
}

variable "temporary_object_expiry_days" {
  description = "Delete tmp/ objects after this many days."
  type        = number
  default     = 7
}

variable "s3_noncurrent_version_expiry_days" {
  description = "Expire old object versions after this many days."
  type        = number
  default     = 30
}

variable "s3_abort_multipart_days" {
  description = "Abort incomplete multipart uploads after this many days."
  type        = number
  default     = 1
}

# -----------------------------
# DynamoDB
# -----------------------------
variable "create_dynamodb_tables" {
  description = "true = create app DynamoDB tables; false = use existing table names/ARNs."
  type        = bool
  default     = true
}

variable "dynamodb_billing_mode" {
  description = "DynamoDB billing mode."
  type        = string
  default     = "PAY_PER_REQUEST"
}

variable "dynamodb_ttl_attribute" {
  description = "TTL attribute name. Backend writes epoch seconds here. Table keys are fixed per table in storage.tf to match the backend (sessions: session_id; docs: session_id+doc; profiles: user_id+profile; audit-log: session_id+ts_event + by-user index)."
  type        = string
  default     = "ttl"
}

variable "existing_dynamodb_table_names" {
  description = "Existing table names when create_dynamodb_tables=false. Keys: sessions, profiles, docs, audit_log."
  type        = map(string)
  default     = {}
}

variable "existing_dynamodb_table_arns" {
  description = "Existing table ARNs when create_dynamodb_tables=false."
  type        = list(string)
  default     = []
}

# -----------------------------
# Amplify frontend
# -----------------------------
variable "enable_amplify" {
  description = "Create Amplify app/branch for frontend. Requires repository details."
  type        = bool
  default     = false
}

variable "amplify_repository_url" {
  description = "Git repository URL for Amplify."
  type        = string
  default     = ""
}

variable "amplify_branch_name" {
  description = "Branch deployed by Amplify."
  type        = string
  default     = "main"
}

variable "amplify_access_token" {
  description = "Optional Git access token for Amplify. Prefer CG-managed repo connection; token may enter state."
  type        = string
  default     = ""
  sensitive   = true
}


variable "bedrock_prompt_ids" {
  description = "Map of call name to Bedrock Prompt Management id:version."
  type        = map(string)
  default     = {}
}