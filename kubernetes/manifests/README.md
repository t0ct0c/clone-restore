# Kubernetes Manifests for WordPress Clone/Restore System

This directory contains Kubernetes manifests for deploying the WordPress Clone/Restore system to EKS.

## Directory Structure

```
kubernetes/manifests/
├── namespaces/           # Namespace definitions
├── wp-setup-service/     # Management service deployment
├── wordpress-clone/      # WordPress clone templates
├── databases/           # Database configurations
├── ingress/             # ALB ingress configurations
└── monitoring/          # Monitoring and observability
```

## Prerequisites

1. EKS cluster `wp-clone-restore` (version 1.35)
2. AWS Load Balancer Controller installed
3. EBS CSI driver installed
4. IAM roles for service accounts configured

## Deployment Order

1. **Namespaces**: `kubectl apply -f namespaces/`
2. **wp-setup-service**: `kubectl apply -f wp-setup-service/`
3. **Templates**: Copy templates to appropriate locations
4. **Monitoring**: `kubectl apply -f monitoring/`

## Templates

Templates use `{TIMESTAMP}` placeholders that should be replaced dynamically by `wp-setup-service` during clone creation.

## Configuration

See `KUBERNETES_IMPLEMENTATION_GUIDE.md` for detailed implementation instructions.

## Notes

- All manifests are designed for the `us-east-1` region
- Storage classes assume `gp2` is available
- Ingress configurations target existing ALB (`wp-targets-alb`)
- HTTPS is configured with ACM certificate for `clones.betaweb.ai`