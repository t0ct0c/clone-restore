# WordPress Clone Image with MySQL Sidecar

Optimized WordPress image for fast clone provisioning with pre-installed custom-migrator plugin.

## Features

- WordPress 6.4 with Apache
- MySQL client for health checks
- Custom-migrator plugin pre-installed
- Warm pool mode support (skip initialization)
- MySQL sidecar compatibility (localhost:3306)

## Building

```bash
docker build -t <account>.dkr.ecr.us-east-1.amazonaws.com/wp-k8s-service-clone:optimized .
docker push <account>.dkr.ecr.us-east-1.amazonaws.com/wp-k8s-service-clone:optimized
```

## Usage

### Normal Clone Pod

```yaml
env:
- name: WORDPRESS_DB_HOST
  value: "127.0.0.1:3306"
- name: WORDPRESS_DB_NAME
  value: "wordpress"
- name: WORDPRESS_DB_USER
  value: "wordpress"
- name: WORDPRESS_DB_PASSWORD
  valueFrom:
    secretKeyRef:
      name: credentials
      key: db-password
```

### Warm Pool Pod

```yaml
env:
- name: WARM_POOL_MODE
  value: "true"
```

## Entrypoint Logic

1. Wait for MySQL sidecar to be ready (localhost:3306)
2. If WARM_POOL_MODE=true: skip WordPress setup, just start Apache
3. If normal mode: proceed with standard WordPress initialization

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| WORDPRESS_DB_HOST | Yes | Database host (127.0.0.1 for sidecar) |
| WORDPRESS_DB_NAME | Yes | Database name |
| WORDPRESS_DB_USER | Yes | Database user |
| WORDPRESS_DB_PASSWORD | Yes | Database password |
| WARM_POOL_MODE | No | Set to "true" for warm pool pods |
| WP_ADMIN_USER | No | WordPress admin username |
| WP_ADMIN_PASSWORD | No | WordPress admin password |
| WP_ADMIN_EMAIL | No | WordPress admin email |
| WP_SITE_URL | No | WordPress site URL |
