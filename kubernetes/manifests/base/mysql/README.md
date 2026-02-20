# Jobs Database Table

**Created**: 2026-02-20  
**Task**: 1.2 - Create jobs database table in shared RDS  
**Status**: ✅ COMPLETED

---

## Table Schema

```sql
CREATE TABLE jobs (
    job_id VARCHAR(36) PRIMARY KEY,
    type ENUM('clone', 'restore', 'delete') NOT NULL,
    status ENUM('pending', 'running', 'completed', 'failed', 'cancelled') NOT NULL DEFAULT 'pending',
    progress INT DEFAULT 0,
    request_payload JSON NOT NULL,
    result JSON NULL,
    error TEXT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    completed_at TIMESTAMP NULL,
    ttl_expires_at TIMESTAMP NULL,
    
    INDEX idx_status (status),
    INDEX idx_type (type),
    INDEX idx_created_at (created_at),
    INDEX idx_ttl_expires_at (ttl_expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

---

## Column Descriptions

| Column | Type | Description |
|--------|------|-------------|
| `job_id` | VARCHAR(36) | UUID primary key |
| `type` | ENUM | Job type: clone, restore, or delete |
| `status` | ENUM | Current status: pending, running, completed, failed, cancelled |
| `progress` | INT | Progress percentage (0-100) |
| `request_payload` | JSON | Original request data |
| `result` | JSON | Job result data (if completed) |
| `error` | TEXT | Error message (if failed) |
| `created_at` | TIMESTAMP | Job creation time |
| `updated_at` | TIMESTAMP | Last update time |
| `completed_at` | TIMESTAMP | Completion time (if finished) |
| `ttl_expires_at` | TIMESTAMP | TTL expiration for cleanup |

---

## Indexes

- `idx_status`: Fast lookup by job status
- `idx_type`: Fast lookup by job type
- `idx_created_at`: Time-based queries
- `idx_ttl_expires_at`: TTL cleanup queries

---

## Connection Details

```
Host: wordpress-staging-shared.civ4qok4uck8.us-east-1.rds.amazonaws.com
Port: 3306
Database: wordpress
User: admin
Password: staging-db-password-change-me (stored in Secret: rds-password)
```

---

## Usage Examples

### Insert a new job
```sql
INSERT INTO jobs (job_id, type, status, request_payload)
VALUES ('550e8400-e29b-41d4-a716-446655440000', 'clone', 'pending', 
        '{"source_url": "https://example.com", "customer_id": "test123"}');
```

### Update job progress
```sql
UPDATE jobs SET status = 'running', progress = 50
WHERE job_id = '550e8400-e29b-41d4-a716-446655440000';
```

### Mark job as completed
```sql
UPDATE jobs SET status = 'completed', progress = 100, completed_at = NOW(),
result = '{"clone_url": "https://clone-550e8400.clones.betaweb.ai"}'
WHERE job_id = '550e8400-e29b-41d4-a716-446655440000';
```

### Query pending jobs
```sql
SELECT * FROM jobs WHERE status = 'pending' ORDER BY created_at ASC;
```

### TTL cleanup query
```sql
DELETE FROM jobs WHERE ttl_expires_at IS NOT NULL 
AND ttl_expires_at < NOW();
```

---

## SQL File Location

`kubernetes/manifests/base/mysql/jobs-table.sql`

---

## Next Steps

1. ✅ Task 1.0: Deploy observability stack - **DONE**
2. ✅ Task 1.1: Deploy Redis broker - **DONE**
3. ✅ Task 1.2: Create jobs database table - **DONE**
4. ⏸️ Task 1.3: Update requirements.txt with Dramatiq dependencies
5. ⏸️ Task 1.4: Create Dramatiq OTLP middleware for tracing
6. ⏸️ Task 1.5: Update wp-k8s-service deployment with Dramatiq sidecar
