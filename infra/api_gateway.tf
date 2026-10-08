resource "aws_cloudwatch_log_group" "api_gateway" {
  name              = "/aws/apigateway/${local.name_prefix}"
  retention_in_days = var.log_retention_days

  tags = {
    Name = "${local.name_prefix}-apigw-logs"
  }
}

resource "aws_apigatewayv2_api" "backend" {
  name          = "${local.name_prefix}-api"
  protocol_type = "HTTP"

  cors_configuration {
    allow_credentials = false
    allow_headers     = ["*"]
    allow_methods     = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
    allow_origins     = var.api_gateway_cors_allowed_origins
    expose_headers    = ["*"]
    max_age           = var.api_gateway_cors_max_age_seconds
  }

  tags = {
    Name = "${local.name_prefix}-api"
  }
}

resource "aws_apigatewayv2_vpc_link" "backend" {
  name               = "${local.name_prefix}-vpclink"
  security_group_ids = [local.vpclink_security_group_id]
  subnet_ids         = local.private_subnet_ids

  tags = {
    Name = "${local.name_prefix}-vpclink"
  }
}

resource "aws_apigatewayv2_integration" "alb" {
  api_id                 = aws_apigatewayv2_api.backend.id
  integration_type       = "HTTP_PROXY"
  integration_method     = "ANY"
  integration_uri        = aws_lb_listener.http.arn
  payload_format_version = "1.0"
  connection_type        = "VPC_LINK"
  connection_id          = aws_apigatewayv2_vpc_link.backend.id
  timeout_milliseconds   = var.api_gateway_timeout_ms
}

resource "aws_apigatewayv2_route" "default" {
  api_id    = aws_apigatewayv2_api.backend.id
  route_key = "$default"
  target    = "integrations/${aws_apigatewayv2_integration.alb.id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.backend.id
  name        = "$default"
  auto_deploy = true

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api_gateway.arn
    format = jsonencode({
      requestId      = "$context.requestId"
      ip             = "$context.identity.sourceIp"
      requestTime    = "$context.requestTime"
      httpMethod     = "$context.httpMethod"
      routeKey       = "$context.routeKey"
      status         = "$context.status"
      protocol       = "$context.protocol"
      responseLength = "$context.responseLength"
      integrationErr = "$context.integrationErrorMessage"
    })
  }

  tags = {
    Name = "${local.name_prefix}-api-stage"
  }
}
