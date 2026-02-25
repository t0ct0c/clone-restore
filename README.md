# WordPress Clone & Restore API

Simple API for cloning WordPress sites and restoring them to production.

## Quick Start

### 1. Create a Clone

```bash
curl -X POST https://clones.betaweb.ai/api/v2/clone \
  -H "Content-Type: application/json" \
  -d '{
    "source_url": "https://betaweb.ai",
    "source_username": "Charles@toctoc.com.au",
    "source_password": "6(4b`Nde1i_D",
    "customer_id": "my-clone-123",
    "ttl_minutes": 60
  }'
```

**Response:**
```json
{
  "job_id": "abc-123-xyz",
  "type": "clone",
  "status": "pending"
}
```

### 2. Check Clone Status

```bash
curl https://clones.betaweb.ai/api/v2/job-status/abc-123-xyz
```

Keep polling until `status: "completed"` (~60-75 seconds)

**Response when complete:**
```json
{
  "status": "completed",
  "progress": 100,
  "result": {
    "public_url": "https://my-clone-123.clones.betaweb.ai",
    "wordpress_username": "admin",
    "wordpress_password": "generated-password"
  }
}
```

### 3. Make Changes

Open the clone URL in your browser and make your changes:
- URL: `https://my-clone-123.clones.betaweb.ai/wp-admin`
- Username: `admin`
- Password: `generated-password` (from step 2)

### 4. Restore to Production

```bash
curl -X POST https://clones.betaweb.ai/api/v2/restore \
  -H "Content-Type: application/json" \
  -d '{
    "source_url": "https://my-clone-123.clones.betaweb.ai/",
    "source_username": "admin",
    "source_password": "generated-password",
    "target_url": "https://betaweb.ai/",
    "target_username": "Charles@toctoc.com.au",
    "target_password": "6(4b`Nde1i_D",
    "preserve_plugins": true,
    "preserve_themes": false,
    "customer_id": "restore-123"
  }'
```

**Response:**
```json
{
  "job_id": "def-456-xyz",
  "type": "restore",
  "status": "pending"
}
```

### 5. Check Restore Status

```bash
curl https://clones.betaweb.ai/api/v2/job-status/def-456-xyz
```

Keep polling until `status: "completed"` (~60 seconds)

**Done!** Your changes are now live on `https://betaweb.ai`

## Timing

- Clone creation: 60-75 seconds
- Restore: 60 seconds
- Poll job status every 5-10 seconds

## API Reference

All endpoints return JSON with a `job_id` for async operations.

### POST /api/v2/clone
Create a WordPress clone

### POST /api/v2/restore
Restore a clone to production

### GET /api/v2/job-status/{job_id}
Check status of any job

## Additional Documentation

See `/docs` folder for architecture and implementation details.
