data "aws_caller_identity" "current" {}

data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  name_prefix = "${var.project}-${var.environment}"

  common_tags = merge({
    Project     = var.project
    Environment = var.environment
    ManagedBy   = "opentofu"
    Owner       = var.owner
    CostCenter  = var.cost_center
  }, var.additional_tags)

  # Network selection: create in Acies practice, reference in CG.
  vpc_id                  = var.create_vpc ? aws_vpc.this[0].id : var.existing_vpc_id
  private_subnet_ids      = var.create_vpc ? aws_subnet.private[*].id : var.existing_private_subnet_ids
  private_route_table_ids = var.create_vpc ? aws_route_table.private[*].id : var.existing_private_route_table_ids

  # Security group selection.
  vpclink_security_group_id = var.create_security_groups ? aws_security_group.vpclink[0].id : var.existing_vpclink_security_group_id
  alb_security_group_id     = var.create_security_groups ? aws_security_group.alb[0].id : var.existing_alb_security_group_id
  ecs_security_group_id     = var.create_security_groups ? aws_security_group.ecs[0].id : var.existing_ecs_security_group_id

  # ECR selection.
  ecr_repository_name = var.ecr_repository_name != "" ? var.ecr_repository_name : "${var.project}/backend"
  ecr_repository_url  = var.create_ecr ? aws_ecr_repository.backend[0].repository_url : var.existing_ecr_repository_url

  # IAM role selection.
  ecs_execution_role_arn = var.create_iam_roles ? aws_iam_role.ecs_execution[0].arn : var.existing_ecs_execution_role_arn
  ecs_task_role_arn      = var.create_iam_roles ? aws_iam_role.ecs_task[0].arn : var.existing_ecs_task_role_arn

  # S3 selection.
  generated_s3_bucket_name = "${local.name_prefix}-data-${data.aws_caller_identity.current.account_id}-${var.aws_region}"
  s3_bucket_name           = var.create_s3_bucket ? (var.s3_bucket_name != "" ? var.s3_bucket_name : local.generated_s3_bucket_name) : var.existing_s3_bucket_name
  s3_bucket_arn            = "arn:aws:s3:::${local.s3_bucket_name}"

  # DynamoDB names. These match the current app architecture: sessions, profiles, docs, audit log.
  dynamodb_table_names = var.create_dynamodb_tables ? {
    sessions  = aws_dynamodb_table.sessions[0].name
    profiles  = aws_dynamodb_table.profiles[0].name
    docs      = aws_dynamodb_table.docs[0].name
    audit_log = aws_dynamodb_table.audit_log[0].name
  } : var.existing_dynamodb_table_names

  dynamodb_table_arns = var.create_dynamodb_tables ? [
    aws_dynamodb_table.sessions[0].arn,
    aws_dynamodb_table.profiles[0].arn,
    aws_dynamodb_table.docs[0].arn,
    aws_dynamodb_table.audit_log[0].arn
  ] : var.existing_dynamodb_table_arns

  # Secrets. Secret values are intentionally NOT managed by OpenTofu.
  openrouter_secret_arn = var.enable_openrouter ? (var.create_placeholder_secrets ? aws_secretsmanager_secret.openrouter[0].arn : var.openrouter_secret_arn) : ""
  deepl_secret_arn      = var.enable_deepl ? (var.create_placeholder_secrets ? aws_secretsmanager_secret.deepl[0].arn : var.deepl_secret_arn) : ""
  secret_arns           = compact([local.openrouter_secret_arn, local.deepl_secret_arn])

  ecs_container_secrets = concat(
    var.enable_openrouter ? [{
      name      = "OPENROUTER_API_KEY"
      valueFrom = local.openrouter_secret_arn
    }] : [],
    var.enable_deepl ? [{
      name      = "DEEPL_API_KEY"
      valueFrom = local.deepl_secret_arn
    }] : []
  )

  # Names below are the ones the backend reads (backend/app/config.py, deploy/taskdef.json).
  # S3_BUCKET + DDB_SESSIONS + DDB_DOCS must all be set, or the backend falls back to local files.
  ecs_environment = concat([
    { name = "CORS_ORIGINS", value = join(",", var.api_gateway_cors_allowed_origins) },
    { name = "BEDROCK_PROMPT_IDS", value = jsonencode(var.bedrock_prompt_ids) },
    { name = "AWS_REGION", value = var.aws_region },
    { name = "TRANSLATE_REGION", value = var.aws_region },
    { name = "S3_BUCKET", value = local.s3_bucket_name },
    { name = "DDB_SESSIONS", value = lookup(local.dynamodb_table_names, "sessions", "") },
    { name = "DDB_DOCS", value = lookup(local.dynamodb_table_names, "docs", "") },
    { name = "DDB_PROFILES", value = lookup(local.dynamodb_table_names, "profiles", "") },
    { name = "DDB_AUDIT", value = lookup(local.dynamodb_table_names, "audit_log", "") }
    ], var.enable_bedrock ? [
    { name = "BEDROCK_REGION", value = var.aws_region },
    { name = "BEDROCK_CHEAP_MODEL", value = var.bedrock_model_id },
    { name = "BEDROCK_DEFAULT_MODEL", value = var.bedrock_model_id },
    { name = "BEDROCK_STRONG_MODEL", value = var.bedrock_model_id }
    ] : [],
    var.allow_anon ? [{ name = "ALLOW_ANON", value = "1" }] : [],
    var.entra_tenant_id != "" && var.entra_client_id != "" ? [
      { name = "ENTRA_TENANT_ID", value = var.entra_tenant_id },
      { name = "ENTRA_CLIENT_ID", value = var.entra_client_id }
  ] : [])
}
