# IAM Roles for Service Accounts (IRSA)
# These roles allow Kubernetes pods to access AWS services

# IAM role for ACK RDS controller
module "ack_rds_irsa" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.0"

  role_name = "${var.cluster_name}-ack-rds-controller"

  role_policy_arns = {
    policy = aws_iam_policy.ack_rds_controller.arn
  }

  oidc_providers = {
    main = {
      provider_arn               = module.eks.oidc_provider_arn
      namespace_service_accounts = ["ack-system:ack-rds-controller"]
    }
  }

  tags = {
    Name = "${var.cluster_name}-ack-rds-controller"
  }
}

# IAM policy for ACK RDS controller
resource "aws_iam_policy" "ack_rds_controller" {
  name_prefix = "${var.cluster_name}-ack-rds-"
  description = "IAM policy for ACK RDS controller"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "rds:CreateDBInstance",
          "rds:DeleteDBInstance",
          "rds:DescribeDBInstances",
          "rds:ModifyDBInstance",
          "rds:AddTagsToResource",
          "rds:ListTagsForResource",
          "rds:RemoveTagsFromResource",
          "rds:CreateDBSubnetGroup",
          "rds:DeleteDBSubnetGroup",
          "rds:DescribeDBSubnetGroups",
          "rds:ModifyDBSubnetGroup"
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "ec2:DescribeSecurityGroups",
          "ec2:DescribeSubnets",
          "ec2:DescribeVpcs"
        ]
        Resource = "*"
      }
    ]
  })
}

# IAM role for wp-k8s-service (to access AWS services)
module "wp_k8s_service_irsa" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.0"

  role_name = "${var.cluster_name}-wp-k8s-service"

  role_policy_arns = {
    policy = aws_iam_policy.wp_k8s_service.arn
  }

  oidc_providers = {
    main = {
      provider_arn = module.eks.oidc_provider_arn
      namespace_service_accounts = [
        "wordpress-staging:wp-k8s-service",
        "wordpress-production:wp-k8s-service"
      ]
    }
  }

  tags = {
    Name = "${var.cluster_name}-wp-k8s-service"
  }
}

# IAM policy for wp-k8s-service
resource "aws_iam_policy" "wp_k8s_service" {
  name_prefix = "${var.cluster_name}-wp-k8s-"
  description = "IAM policy for wp-k8s-service to manage Kubernetes resources"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "ecr:GetAuthorizationToken",
          "ecr:BatchCheckLayerAvailability",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage"
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue"
        ]
        Resource = "arn:aws:secretsmanager:${var.aws_region}:*:secret:wordpress/*"
      }
    ]
  })
}

# IAM role for AWS Load Balancer Controller
module "aws_lb_controller_irsa" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.0"

  role_name = "${var.cluster_name}-aws-lb-controller"

  attach_load_balancer_controller_policy = true

  oidc_providers = {
    main = {
      provider_arn               = module.eks.oidc_provider_arn
      namespace_service_accounts = ["kube-system:aws-load-balancer-controller"]
    }
  }

  tags = {
    Name = "${var.cluster_name}-aws-lb-controller"
  }
}

# IAM role for Cluster Autoscaler
module "cluster_autoscaler_irsa" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.0"

  role_name = "${var.cluster_name}-cluster-autoscaler"

  attach_cluster_autoscaler_policy = true
  cluster_autoscaler_cluster_names = [var.cluster_name]

  oidc_providers = {
    main = {
      provider_arn               = module.eks.oidc_provider_arn
      namespace_service_accounts = ["kube-system:cluster-autoscaler"]
    }
  }

  tags = {
    Name = "${var.cluster_name}-cluster-autoscaler"
  }
}
