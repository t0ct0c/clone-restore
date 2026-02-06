# VPC Configuration for EKS Cluster
# Creates a VPC with public and private subnets across 3 availability zones

data "aws_availability_zones" "available" {
  state = "available"
}

module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.0"

  name = "${var.cluster_name}-vpc"
  cidr = var.vpc_cidr

  azs             = slice(data.aws_availability_zones.available.names, 0, 3)
  private_subnets = [
    cidrsubnet(var.vpc_cidr, 4, 0), # 10.0.0.0/20
    cidrsubnet(var.vpc_cidr, 4, 1), # 10.0.16.0/20
    cidrsubnet(var.vpc_cidr, 4, 2), # 10.0.32.0/20
  ]
  public_subnets = [
    cidrsubnet(var.vpc_cidr, 4, 8),  # 10.0.128.0/20
    cidrsubnet(var.vpc_cidr, 4, 9),  # 10.0.144.0/20
    cidrsubnet(var.vpc_cidr, 4, 10), # 10.0.160.0/20
  ]

  enable_nat_gateway   = true
  single_nat_gateway   = true  # Single NAT for cost savings ($64/month savings)
  enable_dns_hostnames = true
  enable_dns_support   = true

  # Kubernetes tags for subnet discovery
  public_subnet_tags = {
    "kubernetes.io/role/elb"                              = "1"
    "kubernetes.io/cluster/${var.cluster_name}"           = "shared"
  }

  private_subnet_tags = {
    "kubernetes.io/role/internal-elb"                     = "1"
    "kubernetes.io/cluster/${var.cluster_name}"           = "shared"
    "karpenter.sh/discovery"                              = var.cluster_name
  }

  tags = {
    Name = "${var.cluster_name}-vpc"
  }
}

# Security group for RDS instances
resource "aws_security_group" "rds" {
  name_prefix = "${var.cluster_name}-rds-"
  description = "Security group for RDS MySQL instances"
  vpc_id      = module.vpc.vpc_id

  ingress {
    description     = "MySQL from EKS worker nodes"
    from_port       = 3306
    to_port         = 3306
    protocol        = "tcp"
    security_groups = [module.eks.node_security_group_id]
  }

  egress {
    description = "Allow all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.cluster_name}-rds-sg"
  }
}

# RDS subnet group for private subnets
resource "aws_db_subnet_group" "wordpress" {
  name       = "${var.cluster_name}-rds-subnet-group"
  subnet_ids = module.vpc.private_subnets

  tags = {
    Name = "${var.cluster_name}-rds-subnet-group"
  }
}
