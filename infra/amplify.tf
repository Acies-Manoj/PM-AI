resource "aws_amplify_app" "frontend" {
  count = var.enable_amplify ? 1 : 0

  name         = "${local.name_prefix}-frontend"
  repository   = var.amplify_repository_url
  access_token = var.amplify_access_token != "" ? var.amplify_access_token : null

  platform = "WEB"

  build_spec = <<-YAML
    version: 1
    applications:
      - appRoot: frontend
        frontend:
          phases:
            preBuild:
              commands:
                - npm ci
            build:
              commands:
                - npm run build
          artifacts:
            baseDirectory: dist
            files:
              - '**/*'
          cache:
            paths:
              - node_modules/**/*
  YAML

  environment_variables = {
    VITE_API_BASE_URL         = trimsuffix(aws_apigatewayv2_stage.default.invoke_url, "/")
    AMPLIFY_MONOREPO_APP_ROOT = "frontend"
  }

  tags = {
    Name = "${local.name_prefix}-frontend"
  }
}

resource "aws_amplify_branch" "frontend" {
  count = var.enable_amplify ? 1 : 0

  app_id      = aws_amplify_app.frontend[0].id
  branch_name = var.amplify_branch_name

  framework = "React"
  stage     = upper(var.environment) == "PROD" ? "PRODUCTION" : "DEVELOPMENT"

  environment_variables = {
    VITE_API_BASE_URL = trimsuffix(aws_apigatewayv2_stage.default.invoke_url, "/")
  }

  tags = {
    Name = "${local.name_prefix}-frontend-${var.amplify_branch_name}"
  }
}
