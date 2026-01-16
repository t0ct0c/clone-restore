variable "region" {
  type    = string
  default = "us-east-1"
}

# CIDR allowed to SSH to EC2 (for now you can set "0.0.0.0/0" and rely on SSH keys)
variable "admin_cidr" {
  type        = string
  description = "CIDR block allowed for SSH (e.g. 0.0.0.0/0 or your-ip/32)"
  default     = "0.0.0.0/0"
}

variable "instance_type" {
  type        = string
  description = "EC2 instance type for target hosts"
  default     = "t3.medium"
}

variable "asg_min_size" {
  type        = number
  description = "Minimum number of EC2 instances"
  default     = 1
}

variable "asg_max_size" {
  type        = number
  description = "Maximum number of EC2 instances"
  default     = 5
}

variable "asg_desired_capacity" {
  type        = number
  description = "Desired number of EC2 instances"
  default     = 1
}
