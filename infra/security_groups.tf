resource "aws_security_group" "vpclink" {
  count = var.create_security_groups ? 1 : 0

  name        = "${local.name_prefix}-vpclink-sg"
  description = "API Gateway VPC Link security group"
  vpc_id      = local.vpc_id

  egress {
    description = "Allow outbound from VPC Link"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = var.allowed_egress_cidrs
  }

  tags = {
    Name = "${local.name_prefix}-vpclink-sg"
  }
}

resource "aws_security_group" "alb" {
  count = var.create_security_groups ? 1 : 0

  name        = "${local.name_prefix}-alb-sg"
  description = "Internal ALB security group"
  vpc_id      = local.vpc_id

  ingress {
    description     = "HTTP from API Gateway VPC Link"
    from_port       = var.alb_listener_port
    to_port         = var.alb_listener_port
    protocol        = "tcp"
    security_groups = [aws_security_group.vpclink[0].id]
  }

  egress {
    description = "Allow outbound from ALB to ECS"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = var.allowed_egress_cidrs
  }

  tags = {
    Name = "${local.name_prefix}-alb-sg"
  }
}

resource "aws_security_group" "ecs" {
  count = var.create_security_groups ? 1 : 0

  name        = "${local.name_prefix}-ecs-sg"
  description = "ECS backend task security group"
  vpc_id      = local.vpc_id

  ingress {
    description     = "Backend traffic from internal ALB"
    from_port       = var.container_port
    to_port         = var.container_port
    protocol        = "tcp"
    security_groups = [aws_security_group.alb[0].id]
  }

  egress {
    description = "Allow backend outbound traffic"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = var.allowed_egress_cidrs
  }

  tags = {
    Name = "${local.name_prefix}-ecs-sg"
  }
}
