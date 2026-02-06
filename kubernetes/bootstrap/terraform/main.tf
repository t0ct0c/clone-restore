# EKS Cluster Configuration
# Main cluster definition using terraform-aws-modules/eks

module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 19.0"

  cluster_name    = var.cluster_name
  cluster_version = var.cluster_version

  vpc_id                         = module.vpc.vpc_id
  subnet_ids                     = module.vpc.private_subnets
  cluster_endpoint_public_access = true

  # OIDC Provider for IRSA (IAM Roles for Service Accounts)
  enable_irsa = true

  # Cluster addons
  cluster_addons = {
    coredns = {
      most_recent = true
    }
    kube-proxy = {
      most_recent = true
    }
    vpc-cni = {
      most_recent = true
    }
  }

  # EKS Managed Node Groups
  eks_managed_node_groups = {
    ng1 = {
      name = "${var.cluster_name}-ng1"

      instance_types = var.instance_types
      capacity_type  = var.enable_spot_instances ? "SPOT" : "ON_DEMAND"

      min_size     = var.min_nodes
      max_size     = var.max_nodes
      desired_size = var.desired_nodes

      labels = {
        role = "general"
      }

      tags = {
        Name = "${var.cluster_name}-general-node"
      }
    }

    ng2 = {
      name = "${var.cluster_name}-ng2"

      instance_types = ["t3.small"]
      capacity_type  = var.enable_spot_instances ? "SPOT" : "ON_DEMAND"

      min_size     = 1
      max_size     = 1
      desired_size = 1

      labels = {
        role = "general"
      }

      tags = {
        Name = "${var.cluster_name}-small-node"
      }
    }
  }

  # Cluster security group rules
  cluster_security_group_additional_rules = {
    ingress_nodes_ephemeral_ports_tcp = {
      description                = "Nodes on ephemeral ports"
      protocol                   = "tcp"
      from_port                  = 1025
      to_port                    = 65535
      type                       = "ingress"
      source_node_security_group = true
    }
  }

  # Node security group rules
  node_security_group_additional_rules = {
    ingress_self_all = {
      description = "Node to node all ports/protocols"
      protocol    = "-1"
      from_port   = 0
      to_port     = 0
      type        = "ingress"
      self        = true
    }
    ingress_cluster_all = {
      description                   = "Cluster to node all ports/protocols"
      protocol                      = "-1"
      from_port                     = 0
      to_port                       = 0
      type                          = "ingress"
      source_cluster_security_group = true
    }
    egress_all = {
      description = "Node all egress"
      protocol    = "-1"
      from_port   = 0
      to_port     = 0
      type        = "egress"
      cidr_blocks = ["0.0.0.0/0"]
    }
  }

  # Add Karpenter discovery tag to node security group
  node_security_group_tags = {
    "karpenter.sh/discovery" = var.cluster_name
  }

  tags = {
    Name                         = var.cluster_name
    "karpenter.sh/discovery"     = var.cluster_name
  }
}

# Kubernetes namespaces for staging and production
resource "kubernetes_namespace" "wordpress_staging" {
  metadata {
    name = "wordpress-staging"
    labels = {
      environment = "staging"
      managed-by  = "terraform"
    }
  }

  depends_on = [module.eks]
}

resource "kubernetes_namespace" "wordpress_production" {
  metadata {
    name = "wordpress-production"
    labels = {
      environment = "production"
      managed-by  = "terraform"
    }
  }

  depends_on = [module.eks]
}

# Resource quotas for staging namespace
resource "kubernetes_resource_quota" "staging" {
  metadata {
    name      = "staging-quota"
    namespace = kubernetes_namespace.wordpress_staging.metadata[0].name
  }

  spec {
    hard = {
      "requests.cpu"    = "4"
      "requests.memory" = "8Gi"
      "limits.cpu"      = "8"
      "limits.memory"   = "16Gi"
      "pods"            = "20"
    }
  }
}

# Resource quotas for production namespace
resource "kubernetes_resource_quota" "production" {
  metadata {
    name      = "production-quota"
    namespace = kubernetes_namespace.wordpress_production.metadata[0].name
  }

  spec {
    hard = {
      "requests.cpu"    = "16"
      "requests.memory" = "32Gi"
      "limits.cpu"      = "32"
      "limits.memory"   = "64Gi"
      "pods"            = "100"
    }
  }
}

# ConfigMap for storing cluster configuration
resource "kubernetes_config_map" "cluster_info" {
  metadata {
    name      = "cluster-info"
    namespace = "kube-system"
  }

  data = {
    cluster_name         = var.cluster_name
    aws_region           = var.aws_region
    rds_security_group   = aws_security_group.rds.id
    rds_subnet_group     = aws_db_subnet_group.wordpress.name
    vpc_id               = module.vpc.vpc_id
  }

  depends_on = [module.eks]
}
