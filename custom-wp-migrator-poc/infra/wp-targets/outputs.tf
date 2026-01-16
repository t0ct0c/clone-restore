output "alb_dns_name" {
  description = "DNS name of the Application Load Balancer"
  value       = aws_lb.wp_targets.dns_name
}

output "ssh_private_key_pem" {
  description = "Private key for EC2 instances (use as /app/ssh/wp-targets-key.pem in setup service)"
  value       = tls_private_key.wp_targets.private_key_pem
  sensitive   = true
}
