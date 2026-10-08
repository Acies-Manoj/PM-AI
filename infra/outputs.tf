output "name_prefix" {
  description = "Common resource name prefix."
  value       = local.name_prefix
}

output "vpc_id" {
  description = "Created or referenced VPC ID."
  value       = local.vpc_id
}

output "private_subnet_ids" {
  description = "Private subnet IDs used by VPC Link, ALB, and ECS."
  value       = local.private_subnet_ids
}

output "ecr_repository_url" {
  description = "Backend ECR repository URL."
  value       = local.ecr_repository_url
}

output "docker_build_and_push_hint" {
  description = "Command hint for building and pushing the backend image. Replace profile if required."
  value = join("\n", [
    "cd backend",
    "docker build -t ${local.ecr_repository_name}:${var.image_tag} .",
    "aws ecr get-login-password --region ${var.aws_region}${var.aws_profile != "" ? " --profile ${var.aws_profile}" : ""} | docker login --username AWS --password-stdin ${data.aws_caller_identity.current.account_id}.dkr.ecr.${var.aws_region}.amazonaws.com",
    "docker tag ${local.ecr_repository_name}:${var.image_tag} ${local.ecr_repository_url}:${var.image_tag}",
    "docker push ${local.ecr_repository_url}:${var.image_tag}"
  ])
}

output "api_gateway_url" {
  description = "Public API Gateway URL for frontend backend calls."
  value       = aws_apigatewayv2_stage.default.invoke_url
}

output "internal_alb_dns_name" {
  description = "Internal ALB DNS name. This is private, not an internet URL."
  value       = aws_lb.backend.dns_name
}

output "s3_bucket_name" {
  description = "App data bucket name."
  value       = local.s3_bucket_name
}

output "dynamodb_table_names" {
  description = "DynamoDB table names used by the backend."
  value       = local.dynamodb_table_names
}

output "openrouter_secret_arn" {
  description = "OpenRouter secret ARN, if enabled. Insert the value separately."
  value       = local.openrouter_secret_arn
}

output "deepl_secret_arn" {
  description = "DeepL secret ARN, if enabled. Insert the value separately."
  value       = local.deepl_secret_arn
}

output "bedrock_model_id" {
  description = "Configured Bedrock model ID."
  value       = var.enable_bedrock ? var.bedrock_model_id : ""
}

output "amplify_default_domain" {
  description = "Amplify default domain, if Amplify is enabled."
  value       = var.enable_amplify ? aws_amplify_app.frontend[0].default_domain : ""
}
