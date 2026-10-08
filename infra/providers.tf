provider "aws" {
  region  = var.aws_region
  profile = var.aws_profile != "" ? var.aws_profile : null

  dynamic "assume_role" {
    for_each = var.assume_role_arn != "" ? [1] : []
    content {
      role_arn = var.assume_role_arn
    }
  }

  default_tags {
    tags = local.common_tags
  }
}
