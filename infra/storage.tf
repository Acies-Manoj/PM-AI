resource "aws_s3_bucket" "data" {
  count = var.create_s3_bucket ? 1 : 0

  bucket = local.s3_bucket_name

  tags = {
    Name = "${local.name_prefix}-data-bucket"
  }
}

resource "aws_s3_bucket_public_access_block" "data" {
  count = var.create_s3_bucket ? 1 : 0

  bucket = aws_s3_bucket.data[0].id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "data" {
  count = var.create_s3_bucket ? 1 : 0

  bucket = aws_s3_bucket.data[0].id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "data" {
  count = var.create_s3_bucket ? 1 : 0

  bucket = aws_s3_bucket.data[0].id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = var.s3_encryption_type
      kms_master_key_id = var.s3_encryption_type == "aws:kms" ? var.kms_key_arn : null
    }
  }
}

resource "aws_s3_bucket_cors_configuration" "data" {
  count = var.create_s3_bucket ? 1 : 0

  bucket = aws_s3_bucket.data[0].id

  cors_rule {
    allowed_headers = ["*"]
    allowed_methods = ["PUT", "GET", "HEAD"]
    allowed_origins = var.s3_cors_allowed_origins
    expose_headers  = ["ETag"]
    max_age_seconds = var.s3_cors_max_age_seconds
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "data" {
  count = var.create_s3_bucket ? 1 : 0

  bucket = aws_s3_bucket.data[0].id

  rule {
    id     = "expire-temporary-objects"
    status = "Enabled"

    filter {
      prefix = "tmp/"
    }

    expiration {
      days = var.temporary_object_expiry_days
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = var.s3_abort_multipart_days
    }
  }

  rule {
    id     = "expire-old-object-versions"
    status = "Enabled"

    filter {
      prefix = ""
    }

    noncurrent_version_expiration {
      noncurrent_days = var.s3_noncurrent_version_expiry_days
    }
  }
}

data "aws_iam_policy_document" "data_bucket" {
  count = var.create_s3_bucket ? 1 : 0

  statement {
    sid    = "DenyInsecureTransport"
    effect = "Deny"

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    actions = ["s3:*"]
    resources = [
      local.s3_bucket_arn,
      "${local.s3_bucket_arn}/*"
    ]

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "data" {
  count = var.create_s3_bucket ? 1 : 0

  bucket = aws_s3_bucket.data[0].id
  policy = data.aws_iam_policy_document.data_bucket[0].json
}

resource "aws_dynamodb_table" "sessions" {
  count = var.create_dynamodb_tables ? 1 : 0

  name         = "${local.name_prefix}-sessions"
  billing_mode = var.dynamodb_billing_mode
  hash_key     = var.dynamodb_hash_key
  range_key    = var.dynamodb_range_key

  attribute {
    name = var.dynamodb_hash_key
    type = "S"
  }

  attribute {
    name = var.dynamodb_range_key
    type = "S"
  }

  ttl {
    attribute_name = var.dynamodb_ttl_attribute
    enabled        = true
  }

  point_in_time_recovery {
    enabled = true
  }

  tags = {
    Name = "${local.name_prefix}-sessions"
  }
}

resource "aws_dynamodb_table" "profiles" {
  count = var.create_dynamodb_tables ? 1 : 0

  name         = "${local.name_prefix}-profiles"
  billing_mode = var.dynamodb_billing_mode
  hash_key     = var.dynamodb_hash_key
  range_key    = var.dynamodb_range_key

  attribute {
    name = var.dynamodb_hash_key
    type = "S"
  }

  attribute {
    name = var.dynamodb_range_key
    type = "S"
  }

  tags = {
    Name = "${local.name_prefix}-profiles"
  }
}

resource "aws_dynamodb_table" "docs" {
  count = var.create_dynamodb_tables ? 1 : 0

  name         = "${local.name_prefix}-docs"
  billing_mode = var.dynamodb_billing_mode
  hash_key     = var.dynamodb_hash_key
  range_key    = var.dynamodb_range_key

  attribute {
    name = var.dynamodb_hash_key
    type = "S"
  }

  attribute {
    name = var.dynamodb_range_key
    type = "S"
  }

  ttl {
    attribute_name = var.dynamodb_ttl_attribute
    enabled        = true
  }

  point_in_time_recovery {
    enabled = true
  }

  tags = {
    Name = "${local.name_prefix}-docs"
  }
}

resource "aws_dynamodb_table" "audit_log" {
  count = var.create_dynamodb_tables ? 1 : 0

  name         = "${local.name_prefix}-audit-log"
  billing_mode = var.dynamodb_billing_mode
  hash_key     = var.dynamodb_hash_key
  range_key    = var.dynamodb_range_key

  attribute {
    name = var.dynamodb_hash_key
    type = "S"
  }

  attribute {
    name = var.dynamodb_range_key
    type = "S"
  }

  ttl {
    attribute_name = var.dynamodb_ttl_attribute
    enabled        = true
  }

  tags = {
    Name = "${local.name_prefix}-audit-log"
  }
}
