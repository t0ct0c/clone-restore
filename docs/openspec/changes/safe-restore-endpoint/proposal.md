# Change: Safe Restore Endpoint with Plugin/Theme Preservation

## Why

Production sites need to restore content from staging/backups without accidentally downgrading plugins or themes that have been updated on production. The boss's concern: "Export bonnel.ai to staging → Update plugin on live → Restore staging to live" should NOT revert the plugin update.

Current behavior: The import process completely replaces `wp-content/plugins/` and `wp-content/themes/`, causing production plugin updates to be lost when restoring from older snapshots.

## What Changes

- Add a new `/restore` REST API endpoint that performs selective restoration
- Modify the importer (`class-importer.php`) to support selective preservation of plugins
- Implement pre-restore backup of target plugins to temporary storage
- Restore database, uploads, and themes from staging, preserving only production plugins
- Add integrity verification to detect database/filesystem mismatches after restore
- Provide detailed restoration report showing what was preserved vs restored

## Impact

**Affected specs**: 
- `safe-restore` (new capability)
- `wp-clone-automation` (modified - restore uses different preservation strategy than clone)

**Affected code**:
- `custom-wp-migrator-poc/wp-setup-service/app/main.py` - New `/restore` endpoint
- `custom-wp-migrator-poc/plugin/includes/class-importer.php` - Preservation logic
- `custom-wp-migrator-poc/plugin/includes/class-api.php` - Import API parameter handling

**Benefits**:
- Prevents accidental plugin/theme downgrades on production
- Allows safe content restoration from staging environments
- Maintains plugin updates while restoring design/content changes
- Provides transparency through detailed restoration reports

**Constraints**:
- Requires temporary disk space for plugin backups during restore
- Database schema conflicts possible if plugins were significantly updated
- Assumes themes are primarily modified on staging, not production
- Production plugin updates must not have database schema dependencies on old plugin versions
