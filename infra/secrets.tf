resource "aws_secretsmanager_secret" "openrouter" {
  count = var.create_placeholder_secrets && var.enable_openrouter ? 1 : 0

  name                    = "${local.name_prefix}/openrouter-api-key"
  description             = "OpenRouter API key placeholder for ${local.name_prefix}. Value must be inserted outside OpenTofu."
  recovery_window_in_days = 0

  tags = {
    Name = "${local.name_prefix}-openrouter-secret"
  }
}

resource "aws_secretsmanager_secret" "deepl" {
  count = var.create_placeholder_secrets && var.enable_deepl ? 1 : 0

  name                    = "${local.name_prefix}/deepl-api-key"
  description             = "DeepL API key placeholder for ${local.name_prefix}. Value must be inserted outside OpenTofu."
  recovery_window_in_days = 0

  tags = {
    Name = "${local.name_prefix}-deepl-secret"
  }
}
