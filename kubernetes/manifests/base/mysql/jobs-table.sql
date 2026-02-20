-- Jobs table for async clone/restore operations
-- Task 1.2: Create jobs database table

CREATE TABLE IF NOT EXISTS jobs (
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
