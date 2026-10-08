resource "aws_ecr_repository" "backend" {
  count = var.create_ecr ? 1 : 0

  name                 = local.ecr_repository_name
  image_tag_mutability = var.ecr_image_tag_mutability

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = {
    Name = "${local.name_prefix}-backend-ecr"
  }
}

resource "aws_ecr_lifecycle_policy" "backend" {
  count = var.create_ecr ? 1 : 0

  repository = aws_ecr_repository.backend[0].name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep last ${var.ecr_image_retention_count} images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = var.ecr_image_retention_count
      }
      action = {
        type = "expire"
      }
    }]
  })
}
