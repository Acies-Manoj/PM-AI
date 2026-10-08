data "aws_iam_policy_document" "ecs_tasks_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ecs_execution" {
  count = var.create_iam_roles ? 1 : 0

  name                 = "${local.name_prefix}-ecs-execution-role"
  assume_role_policy   = data.aws_iam_policy_document.ecs_tasks_assume_role.json
  permissions_boundary = var.permissions_boundary_arn != "" ? var.permissions_boundary_arn : null

  tags = {
    Name = "${local.name_prefix}-ecs-execution-role"
  }
}

resource "aws_iam_role_policy_attachment" "ecs_execution_managed" {
  count = var.create_iam_roles ? 1 : 0

  role       = aws_iam_role.ecs_execution[0].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "ecs_execution_secrets" {
  count = var.create_iam_roles && length(local.secret_arns) > 0 ? 1 : 0

  statement {
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = local.secret_arns
  }
}

resource "aws_iam_role_policy" "ecs_execution_secrets" {
  count = var.create_iam_roles && length(local.secret_arns) > 0 ? 1 : 0

  name   = "${local.name_prefix}-execution-secrets"
  role   = aws_iam_role.ecs_execution[0].id
  policy = data.aws_iam_policy_document.ecs_execution_secrets[0].json
}

resource "aws_iam_role" "ecs_task" {
  count = var.create_iam_roles ? 1 : 0

  name                 = "${local.name_prefix}-ecs-task-role"
  assume_role_policy   = data.aws_iam_policy_document.ecs_tasks_assume_role.json
  permissions_boundary = var.permissions_boundary_arn != "" ? var.permissions_boundary_arn : null

  tags = {
    Name = "${local.name_prefix}-ecs-task-role"
  }
}

data "aws_iam_policy_document" "app_permissions" {
  count = var.create_iam_roles ? 1 : 0

  statement {
    sid    = "S3AppDataAccess"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject"
    ]
    resources = ["${local.s3_bucket_arn}/*"]
  }

  statement {
    sid       = "S3ListBucket"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [local.s3_bucket_arn]
  }

  statement {
    sid    = "DynamoDBAppTablesAccess"
    effect = "Allow"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
      "dynamodb:DeleteItem",
      "dynamodb:Query",
      "dynamodb:Scan",
      "dynamodb:BatchGetItem",
      "dynamodb:BatchWriteItem"
    ]
    resources = concat(local.dynamodb_table_arns, [for arn in local.dynamodb_table_arns : "${arn}/index/*"])
  }

  dynamic "statement" {
    for_each = length(local.secret_arns) > 0 ? [1] : []
    content {
      sid       = "SecretsRead"
      effect    = "Allow"
      actions   = ["secretsmanager:GetSecretValue"]
      resources = local.secret_arns
    }
  }

  dynamic "statement" {
    for_each = var.enable_translate ? [1] : []
    content {
      sid       = "TranslateText"
      effect    = "Allow"
      actions   = ["translate:TranslateText"]
      resources = ["*"]
    }
  }

  dynamic "statement" {
    for_each = var.enable_bedrock ? [1] : []
    content {
      sid    = "BedrockInvoke"
      effect = "Allow"
      actions = [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream"
      ]
      resources = var.bedrock_model_arns
    }
  }

  dynamic "statement" {
    for_each = var.enable_bedrock ? [1] : []
    content {
      sid       = "BedrockGetPrompt"
      effect    = "Allow"
      actions   = ["bedrock:GetPrompt"]
      resources = ["arn:aws:bedrock:${var.aws_region}:${data.aws_caller_identity.current.account_id}:prompt/*"]
    }
  }

}

resource "aws_iam_role_policy" "app_permissions" {
  count = var.create_iam_roles ? 1 : 0

  name   = "${local.name_prefix}-app-permissions"
  role   = aws_iam_role.ecs_task[0].id
  policy = data.aws_iam_policy_document.app_permissions[0].json
}
