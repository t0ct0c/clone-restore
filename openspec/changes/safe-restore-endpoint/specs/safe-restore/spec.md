# Spec: Safe Restore Capability

## Overview
Enable restoration of WordPress content from backups/staging while preserving production plugin and theme updates.

## ADDED Requirements

### REQ-SR-001: Plugin Preservation During Restore
**Priority**: Critical  
**Category**: Data Safety

The system MUST preserve target site plugins by default during restoration operations to prevent accidental downgrades.

#### Scenario: Plugin update is preserved when restoring old content
**Given** a production WordPress site has plugin X version 1.5  
**And** a backup was taken when plugin X was version 1.0  
**When** the backup is restored to production with default settings  
**Then** plugin X remains at version 1.5  
**And** the database content is from the backup  
**And** the restore report indicates plugins were preserved

#### Scenario: User can force plugin overwrite if needed
**Given** a backup contains plugin X version 1.0  
**And** production has plugin X version 1.5  
**When** the backup is restored with `preserve_plugins=false`  
**Then** plugin X is downgraded to version 1.0  
**And** the restore report indicates plugins were overwritten

---

### REQ-SR-002: Theme Restoration During Restore
**Priority**: Critical  
**Category**: Core Functionality

The system MUST restore theme files from staging by default to deploy design changes to production.

#### Scenario: Theme changes from staging are deployed to production
**Given** staging WordPress has theme Y with custom modifications  
**And** production has unmodified theme Y  
**When** staging is restored to production with default settings  
**Then** theme Y files are copied from staging to production  
**And** theme customizations (colors, layouts in database) are also applied

#### Scenario: User can preserve production theme if needed
**Given** production has theme Y version 2.3  
**And** staging has theme Y version 2.0  
**When** staging is restored with `preserve_themes=true`  
**Then** production theme Y remains at version 2.3  
**And** theme settings from staging database are still applied

---

### REQ-SR-003: Dedicated Restore Endpoint
**Priority**: High  
**Category**: API Design

The system MUST provide a `/restore` REST API endpoint separate from `/clone` with different default preservation settings.

#### Scenario: Restore endpoint uses safe defaults for staging→production workflow
**Given** a restore request is made without specifying preservation options  
**When** the `/restore` endpoint is called  
**Then** `preserve_plugins` defaults to `true` (keep production plugin updates)  
**And** `preserve_themes` defaults to `false` (deploy theme changes from staging)  
**And** `preserve_uploads` defaults to `false` (uploads are restored)

#### Scenario: Restore endpoint accepts target credentials
**Given** a production site with admin credentials  
**And** a staging site with content to restore  
**When** a restore request is made with both source and target credentials  
**Then** the system authenticates to both sites  
**And** exports from source  
**And** imports to target with preservation logic

---

### REQ-SR-004: Pre-Restore Plugin Backup
**Priority**: High  
**Category**: Data Safety

The system MUST create temporary backups of plugins before restoration begins.

#### Scenario: Plugins are backed up before import
**Given** a restore operation is initiated  
**When** the import process starts  
**Then** all files in `wp-content/plugins/` are copied to a temporary directory  
**And** the temporary directory path includes a timestamp for uniqueness

#### Scenario: Backup is used to restore preserved plugins
**Given** plugins have been backed up  
**And** database import has completed  
**And** `preserve_plugins=true`  
**When** the file restoration phase executes  
**Then** backed up plugins are restored over any imported plugin files

---

### REQ-SR-005: Integrity Verification
**Priority**: Medium  
**Category**: Data Consistency

The system MUST verify database and filesystem consistency after restoration and report warnings.

#### Scenario: Missing plugin is detected
**Given** the restored database references plugin Z in `active_plugins` option  
**And** plugin Z does not exist in the target filesystem  
**When** integrity verification runs  
**Then** a warning is added to the restore report: "Active plugin not found: plugin-z/plugin-z.php"

#### Scenario: Missing theme is detected
**Given** the restored database specifies theme "custom-theme" as active  
**And** theme "custom-theme" does not exist in the target filesystem  
**When** integrity verification runs  
**Then** a warning is added to the restore report: "Active theme not found: custom-theme"

#### Scenario: All plugins and themes are valid
**Given** the restored database references only plugins and themes that exist  
**When** integrity verification runs  
**Then** the integrity status is "healthy"  
**And** no warnings are returned

---

### REQ-SR-006: Detailed Restore Reporting
**Priority**: Medium  
**Category**: User Experience

The system MUST return a detailed report of restoration operations including what was preserved vs restored.

#### Scenario: Report includes plugin preservation details
**Given** a restore operation completes successfully  
**When** the response is returned  
**Then** the report includes a list of preserved plugins with names and versions  
**And** the report indicates the preservation status ("preserved" or "restored")

#### Scenario: Report includes database import statistics
**Given** a restore operation completes successfully  
**When** the response is returned  
**Then** the report includes number of database tables imported  
**And** the report includes total rows affected

#### Scenario: Report includes integrity check results
**Given** integrity verification completed with warnings  
**When** the response is returned  
**Then** the report includes integrity status ("healthy" or "warnings")  
**And** the report includes array of warning messages

---

### REQ-SR-007: Temporary Backup Cleanup
**Priority**: Medium  
**Category**: Resource Management

The system MUST clean up temporary backup directories after successful restoration.

#### Scenario: Backup directory is deleted after successful restore
**Given** a restore operation completes successfully  
**And** temporary backups were created in `/tmp/wp-restore-backup-{timestamp}/`  
**When** the cleanup phase executes  
**Then** the temporary backup directory is deleted  
**And** disk space is freed

#### Scenario: Backup directory is preserved on failure
**Given** a restore operation fails during import  
**And** temporary backups exist  
**When** the error is handled  
**Then** the temporary backup directory is NOT deleted  
**And** the error message includes the backup path for manual recovery

---

### REQ-SR-008: Database Content Restoration
**Priority**: Critical  
**Category**: Core Functionality

The system MUST restore the complete database from the source snapshot, including all WordPress core tables and custom tables.

#### Scenario: All database content is restored
**Given** a backup contains posts, pages, comments, and plugin settings  
**When** the restore operation executes  
**Then** all posts are restored with correct content and metadata  
**And** all pages are restored  
**And** all comments are restored  
**And** plugin settings from the backup are applied (wp_options)

#### Scenario: URL replacement is performed
**Given** the source site URL is "https://staging.bonnel.ai"  
**And** the target site URL is "https://bonnel.ai"  
**When** the database is restored  
**Then** all occurrences of the source URL are replaced with the target URL  
**And** serialized data is handled correctly

---

### REQ-SR-009: Media Files Restoration
**Priority**: High  
**Category**: Core Functionality

The system MUST restore media files from the source uploads directory to the target.

#### Scenario: Uploads directory is merged with target
**Given** the backup contains files in `wp-content/uploads/`  
**When** the restore operation executes  
**Then** all files from the backup are copied to the target uploads directory  
**And** existing files with the same name are overwritten  
**And** files not in the backup are preserved

---

### REQ-SR-010: Custom Migrator Plugin Preservation
**Priority**: Critical  
**Category**: System Stability

The system MUST always preserve the custom-migrator plugin itself to prevent breaking the restore mechanism.

#### Scenario: Custom migrator plugin is never overwritten
**Given** a restore operation is in progress  
**And** the backup contains an older version of custom-migrator plugin  
**When** plugin restoration logic executes  
**Then** the custom-migrator plugin in the target is NOT overwritten  
**And** the restore can complete successfully

---

## Integration Points

### Related Capabilities
- `wp-clone-automation`: Clone endpoint continues to use full replacement for test environments
- `plugin-sync`: Plugin injection happens before restore operations

### Modified Components
- `class-importer.php`: Core restoration logic
- `class-api.php`: REST API parameter handling
- `main.py`: New /restore endpoint

### Backward Compatibility
- Existing `/clone` endpoint behavior unchanged
- Existing `/import` endpoint continues to work with full replacement as default
- New `preserve_*` parameters are optional and backward compatible

## Non-Functional Requirements

### Performance
- Backup operation should complete within 30 seconds for typical plugin/theme sizes
- Temporary backups should use minimal disk space (typically < 100MB)

### Security
- Temporary backup directories must have restricted permissions (0700)
- Backup cleanup must be guaranteed to prevent disk space leaks
- Credentials must not be logged in restore reports

### Reliability
- Failed restores must leave the site in a recoverable state
- Temporary backups must be preserved on failure for manual recovery
- Integrity checks must catch common consistency issues
