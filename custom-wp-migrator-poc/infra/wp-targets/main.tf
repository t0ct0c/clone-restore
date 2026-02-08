terraform {
  required_version = ">= 1.4.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
  }
}

provider "aws" {
  region = var.region
}

########################
# Networking (VPC + Subnets)
########################

resource "aws_vpc" "wp_targets" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = {
    Name = "wp-targets-vpc"
  }
}

resource "aws_internet_gateway" "wp_targets" {
  vpc_id = aws_vpc.wp_targets.id

  tags = {
    Name = "wp-targets-igw"
  }
}

data "aws_availability_zones" "available" {
  state = "available"
}

resource "aws_subnet" "public" {
  count                   = 2
  vpc_id                  = aws_vpc.wp_targets.id
  cidr_block              = cidrsubnet(aws_vpc.wp_targets.cidr_block, 4, count.index)
  availability_zone       = data.aws_availability_zones.available.names[count.index]
  map_public_ip_on_launch = true

  tags = {
    Name = "wp-targets-public-${count.index}"
  }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.wp_targets.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.wp_targets.id
  }

  tags = {
    Name = "wp-targets-public-rt"
  }
}

resource "aws_route_table_association" "public" {
  count          = length(aws_subnet.public)
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

########################
# Security Groups
########################

resource "aws_security_group" "alb" {
  name        = "wp-targets-alb-sg"
  description = "ALB SG for WP targets"
  vpc_id      = aws_vpc.wp_targets.id

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "wp_targets" {
  name        = "wp-targets-ec2-sg"
  description = "EC2 SG for WP target hosts"
  vpc_id      = aws_vpc.wp_targets.id

  # HTTP from ALB
  ingress {
    from_port       = 80
    to_port         = 80
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  # SSH for provisioning (can be 0.0.0.0/0; access still gated by SSH key)
  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.admin_cidr]
  }

  # Container direct access from VPC (for wp-setup-service and logging)
  ingress {
    from_port   = 8001
    to_port     = 8050
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/16"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

########################
# ALB + Target Group
########################

resource "aws_lb" "wp_targets" {
  name               = "wp-targets-alb"
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = [for s in aws_subnet.public : s.id]
}

resource "aws_lb_target_group" "wp_targets" {
  name        = "wp-targets-tg"
  port        = 80
  protocol    = "HTTP"
  target_type = "instance"
  vpc_id      = aws_vpc.wp_targets.id

  health_check {
    path                = "/"
    port                = "80"
    protocol            = "HTTP"
    healthy_threshold   = 3
    unhealthy_threshold = 3
    timeout             = 5
    interval            = 30
  }
}

# ACM certificate for clones.betaweb.ai
data "aws_acm_certificate" "clones" {
  domain   = "clones.betaweb.ai"
  statuses = ["ISSUED"]
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.wp_targets.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "redirect"

    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.wp_targets.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-2016-08"
  certificate_arn   = data.aws_acm_certificate.clones.arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.wp_targets.arn
  }
}

########################
# IAM Role for EC2
########################

resource "aws_iam_role" "wp_targets" {
  name = "wp-targets-ec2-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Action = "sts:AssumeRole",
        Effect = "Allow",
        Principal = {
          Service = "ec2.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_instance_profile" "wp_targets" {
  name = "wp-targets-ec2-instance-profile"
  role = aws_iam_role.wp_targets.name
}

resource "aws_iam_role_policy_attachment" "cloudwatch" {
  role       = aws_iam_role.wp_targets.name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy"
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.wp_targets.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# Custom policy for ASG scaling and EC2 describe operations
resource "aws_iam_role_policy" "wp_targets_custom" {
  name = "wp-targets-ec2-custom-policy"
  role = aws_iam_role.wp_targets.id

  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Effect = "Allow",
        Action = [
          "autoscaling:UpdateAutoScalingGroup",
          "autoscaling:DescribeAutoScalingGroups",
          "ec2:DescribeInstances"
        ],
        Resource = "*"
      },
      {
        Effect = "Allow",
        Action = [
          "ecr:GetAuthorizationToken",
          "ecr:BatchCheckLayerAvailability",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage"
        ],
        Resource = "*"
      },
      {
        Effect = "Allow",
        Action = [
          "elasticloadbalancing:DescribeRules",
          "elasticloadbalancing:DescribeTargetGroups",
          "elasticloadbalancing:CreateRule",
          "elasticloadbalancing:CreateTargetGroup",
          "elasticloadbalancing:RegisterTargets",
          "elasticloadbalancing:ModifyRule",
          "elasticloadbalancing:DeleteRule",
          "elasticloadbalancing:DeleteTargetGroup",
          "elasticloadbalancing:DeregisterTargets"
        ],
        Resource = "*"
      }
    ]
  })
}

########################
# MySQL Configuration
########################

resource "random_password" "mysql_root" {
  length  = 32
  special = true
}

########################
# SSH Key Pair (generated by Terraform)
########################

resource "tls_private_key" "wp_targets" {
  algorithm = "RSA"
  rsa_bits  = 4096
}

resource "aws_key_pair" "wp_targets" {
  key_name   = "wp-targets-key"
  public_key = tls_private_key.wp_targets.public_key_openssh
}

########################
# Launch Template + Auto Scaling Group
########################

data "aws_ami" "amazon_linux_2" {
  most_recent = true

  owners = ["amazon"]

  filter {
    name   = "name"
    values = ["amzn2-ami-hvm-*-x86_64-gp2"]
  }
}

resource "aws_launch_template" "wp_targets" {
  name_prefix   = "wp-targets-lt-"
  image_id      = data.aws_ami.amazon_linux_2.id
  instance_type = var.instance_type
  key_name      = aws_key_pair.wp_targets.key_name

  iam_instance_profile {
    name = aws_iam_instance_profile.wp_targets.name
  }

  vpc_security_group_ids = [aws_security_group.wp_targets.id]

  block_device_mappings {
    device_name = "/dev/xvda"
    ebs {
      volume_size = 50
      volume_type = "gp3"
    }
  }

  user_data = base64encode(templatefile("${path.module}/../../wp-setup-service/ec2-user-data.sh", {
    mysql_root_password = random_password.mysql_root.result
  }))

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_autoscaling_group" "wp_targets" {
  name                      = "wp-targets-asg"
  min_size                  = var.asg_min_size
  max_size                  = var.asg_max_size
  desired_capacity          = var.asg_desired_capacity
  vpc_zone_identifier       = [for s in aws_subnet.public : s.id]
  health_check_type         = "EC2"
  health_check_grace_period = 300

  launch_template {
    id      = aws_launch_template.wp_targets.id
    version = "$Latest"
  }

  target_group_arns = [aws_lb_target_group.wp_targets.arn]

  tag {
    key                 = "Name"
    value               = "wp-target-host"
    propagate_at_launch = true
  }
}
