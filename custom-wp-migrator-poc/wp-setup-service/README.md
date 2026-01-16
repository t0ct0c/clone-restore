# WordPress Setup Service

Automated WordPress plugin installation and cloning service with REST API.

## Quick Start

### Build and Run

```bash
# Build image
cd wp-setup-service
docker build -t wp-setup-service .

# Run with docker-compose (mounts plugin ZIP)
docker compose up -d

# Service available at http://localhost:5000
```

### API Endpoints

**Health Check**
```bash
curl http://localhost:5000/health
```

**Clone WordPress** (source → target)
```bash
curl -X POST http://localhost:5000/clone \
  -H "Content-Type: application/json" \
  -d '{
    "source": {
      "url": "https://source-site.com",
      "username": "admin",
      "password": "source_pass"
    },
    "target": {
      "url": "http://localhost:8081",
      "username": "admin",
      "password": "target_pass"
    }
  }'
```

**Restore WordPress** (local → production)
```bash
curl -X POST http://localhost:5000/restore \
  -H "Content-Type: application/json" \
  -d '{
    "source": {
      "url": "http://localhost:8081",
      "username": "admin",
      "password": "local_pass"
    },
    "target": {
      "url": "https://production.com",
      "username": "admin",
      "password": "prod_pass"
    }
  }'
```

**Setup Only** (install plugin + get API key)
```bash
curl -X POST http://localhost:5000/setup \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com",
    "username": "admin",
    "password": "password",
    "role": "target"
  }'
```

## API Documentation

Interactive API docs available at:
- Swagger UI: http://localhost:5000/docs
- ReDoc: http://localhost:5000/redoc

## Error Codes

- `AUTH_FAILED` - Invalid credentials or user not administrator
- `NOT_ADMIN` - User lacks administrator role
- `PLUGIN_UPLOAD_FAILED` - Plugin ZIP upload rejected
- `PLUGIN_ACTIVATION_FAILED` - Plugin activation failed
- `API_KEY_NOT_FOUND` - API key not generated after activation
- `EXPORT_FAILED` - Source export operation failed
- `IMPORT_FAILED` - Target import operation failed
- `NETWORK_ERROR` - Connection timeout or DNS failure

## Environment Variables

- `PLUGIN_ZIP_PATH` - Path to plugin ZIP file (default: `/app/plugin.zip`)
- `TIMEOUT` - Operation timeout in seconds (default: `120`)
- `LOG_LEVEL` - Logging level (default: `info`)

## ECS Deployment

Task definition:
- CPU: 512 (0.5 vCPU)
- Memory: 1024 MB
- Port: 8000
- Health check: `GET /health` (30s interval, 5s timeout)
