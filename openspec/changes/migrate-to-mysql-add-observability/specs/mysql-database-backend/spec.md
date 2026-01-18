# Spec: MySQL Database Backend

## ADDED Requirements

### Requirement: Shared MySQL Container per Host

WordPress target hosts MUST run a single MySQL container accessible to all WordPress containers on that host.

#### Scenario: MySQL container starts on EC2 boot
**Given** a new EC2 instance launches from the Auto Scaling Group  
**When** the user-data script executes  
**Then** MySQL 8.0 container starts with persistent volume  
**And** MySQL is accessible at host.docker.internal:3306  
**And** root password is generated securely

#### Scenario: MySQL container survives restarts
**Given** MySQL container is running  
**When** the host restarts  
**Then** MySQL container starts automatically via Docker restart policy  
**And** all databases and users are preserved

### Requirement: Per-Customer Database Isolation

Each WordPress clone MUST have its own MySQL database with isolated credentials.

#### Scenario: Database created on provision
**Given** a clone request with customer_id "clone-20260116-095447"  
**When** the EC2Provisioner creates the WordPress container  
**Then** a database "wp_clone-20260116-095447" is created  
**And** a user "wp_clone-20260116-095447" is created with generated password  
**And** the user has ALL privileges on only that database

#### Scenario: Database dropped on TTL cleanup
**Given** a WordPress container reaches TTL expiration  
**When** the cleanup script runs  
**Then** the database "wp_{customer_id}" is dropped  
**And** the user "wp_{customer_id}" is dropped  
**And** the container is removed

### Requirement: WordPress MySQL Configuration

WordPress containers MUST connect to the shared MySQL instance via environment variables.

#### Scenario: WordPress connects to MySQL on startup
**Given** a WordPress container starts  
**When** WordPress initializes  
**Then** it connects using WORDPRESS_DB_HOST=host.docker.internal:3306  
**And** uses WORDPRESS_DB_NAME=wp_{customer_id}  
**And** uses WORDPRESS_DB_USER=wp_{customer_id}  
**And** uses WORDPRESS_DB_PASSWORD={generated_password}

#### Scenario: WordPress can write to database
**Given** WordPress is connected to MySQL  
**When** a user creates a post  
**Then** the post is saved to the database  
**And** no "readonly database" errors occur

## REMOVED Requirements

### Requirement: SQLite Database Integration (REMOVED)

The SQLite integration plugin is NO LONGER used for target WordPress instances.

#### Impact
- wordpress-target-image/Dockerfile removes SQLite plugin installation
- class-importer.php removes SQLite-specific truncate logic
- ec2-user-data.sh removes SQLite-specific configuration

## MODIFIED Requirements

### Requirement: Database Import Process

Import process now works with MySQL-to-MySQL instead of MySQL-to-SQLite.

#### Scenario: Import preserves MySQL compatibility
**Given** source site exports MySQL SQL dump  
**When** import runs on target  
**Then** SQL executes without translation  
**And** no SQLite-specific query modifications occur  
**And** import completes in <2 minutes for typical sites
