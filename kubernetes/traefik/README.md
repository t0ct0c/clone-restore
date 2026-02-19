# Traefik for WordPress Clones

## Architecture

```
Internet → NLB (TLS termination) → Traefik → IngressRoute → WordPress Clone Service
```

## Components

- **Traefik v3.6.8**: 2 replicas, handles unlimited subdomain routing
- **NLB**: AWS Network Load Balancer with ACM certificate
- **IngressRoute**: Traefik CRD for subdomain-based routing

## DNS Configuration

Wildcard record required:
```
*.clones.betaweb.ai → k8s-traefiks-traefik-*.elb.us-east-1.amazonaws.com
```

## Testing

```bash
# Test Traefik routing
kubectl port-forward -n traefik-system svc/traefik 8080:8000
# Open: http://localhost:8080/dashboard/

# Test clone creation
curl -X POST https://clones.betaweb.ai/api/clone -H "Content-Type: application/json" \
  -d '{"source":{"url":"https://betaweb.ai","username":"...","password":"..."},"auto_provision":true}'

# Verify IngressRoute
kubectl get ingressroute -n wordpress-staging
```

## Scaling

- Supports 5000+ concurrent clones
- No routing limits (unlike ALB's 100-rule limit)
- Cost: ~$6-8/month (NLB) vs $16-22/month (ALB)
