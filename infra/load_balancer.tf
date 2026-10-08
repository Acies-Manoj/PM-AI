resource "aws_lb" "backend" {
  name               = "${local.name_prefix}-alb"
  internal           = true
  load_balancer_type = "application"
  security_groups    = [local.alb_security_group_id]
  subnets            = local.private_subnet_ids
  idle_timeout       = var.alb_idle_timeout_seconds

  tags = {
    Name = "${local.name_prefix}-alb"
  }
}

resource "aws_lb_target_group" "backend" {
  name        = "${local.name_prefix}-tg"
  port        = var.container_port
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = local.vpc_id

  health_check {
    enabled             = true
    path                = var.health_check_path
    matcher             = var.health_check_matcher
    port                = "traffic-port"
    protocol            = "HTTP"
    interval            = var.health_check_interval_seconds
    timeout             = var.health_check_timeout_seconds
    healthy_threshold   = var.health_check_healthy_threshold
    unhealthy_threshold = var.health_check_unhealthy_threshold
  }

  tags = {
    Name = "${local.name_prefix}-tg"
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.backend.arn
  port              = var.alb_listener_port
  protocol          = var.alb_listener_protocol
  certificate_arn   = var.alb_listener_protocol == "HTTPS" ? var.alb_certificate_arn : null
  ssl_policy        = var.alb_listener_protocol == "HTTPS" ? "ELBSecurityPolicy-TLS13-1-2-2021-06" : null

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.backend.arn
  }

  tags = {
    Name = "${local.name_prefix}-alb-listener"
  }
}
