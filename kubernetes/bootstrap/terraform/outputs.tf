# Terraform outputs for EKS cluster

output "cluster_name" {
  description = "EKS cluster name"
  value       = module.eks.cluster_name
}

output "cluster_endpoint" {
  description = "EKS cluster endpoint"
  value       = module.eks.cluster_endpoint
}

output "cluster_certificate_authority_data" {
  description = "EKS cluster certificate authority data"
  value       = module.eks.cluster_certificate_authority_data
  sensitive   = true
}

output "cluster_security_group_id" {
  description = "Security group ID attached to the EKS cluster"
  value       = module.eks.cluster_security_group_id
}

output "node_security_group_id" {
  description = "Security group ID attached to the EKS nodes"
  value       = module.eks.node_security_group_id
}

output "oidc_provider_arn" {
  description = "ARN of the OIDC provider for IRSA"
  value       = module.eks.oidc_provider_arn
}

output "vpc_id" {
  description = "VPC ID"
  value       = module.vpc.vpc_id
}

output "private_subnets" {
  description = "Private subnet IDs"
  value       = module.vpc.private_subnets
}

output "public_subnets" {
  description = "Public subnet IDs"
  value       = module.vpc.public_subnets
}

output "rds_security_group_id" {
  description = "Security group ID for RDS instances"
  value       = aws_security_group.rds.id
}

output "rds_subnet_group_name" {
  description = "RDS subnet group name"
  value       = aws_db_subnet_group.wordpress.name
}

output "ack_rds_controller_role_arn" {
  description = "IAM role ARN for ACK RDS controller"
  value       = module.ack_rds_irsa.iam_role_arn
}

output "wp_k8s_service_role_arn" {
  description = "IAM role ARN for wp-k8s-service"
  value       = module.wp_k8s_service_irsa.iam_role_arn
}

output "aws_lb_controller_role_arn" {
  description = "IAM role ARN for AWS Load Balancer Controller"
  value       = module.aws_lb_controller_irsa.iam_role_arn
}

output "cluster_autoscaler_role_arn" {
  description = "IAM role ARN for Cluster Autoscaler"
  value       = module.cluster_autoscaler_irsa.iam_role_arn
}

output "karpenter_role_arn" {
  description = "IAM role ARN for Karpenter"
  value       = module.karpenter_irsa.iam_role_arn
}

output "karpenter_instance_profile" {
  description = "Instance profile for Karpenter nodes"
  value       = aws_iam_instance_profile.karpenter_node.name
}

output "karpenter_sqs_queue_name" {
  description = "SQS queue name for Karpenter interruption handling"
  value       = aws_sqs_queue.karpenter.name
}

output "configure_kubectl" {
  description = "Command to configure kubectl"
  value       = "aws eks update-kubeconfig --region ${var.aws_region} --name ${module.eks.cluster_name}"
}
