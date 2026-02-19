# Tasks: Safe Restore Implementation

## Prerequisites
- [x] Review existing importer logic in `class-importer.php`
- [x] Confirm backup directory location and permissions
- [x] Verify WP-CLI availability for integrity checks

## Phase 1: Core Preservation Logic (Backend)
- [x] **Task 1.1**: Add `backup_plugins_directory()` method to `class-importer.php`
  - Creates timestamped backup in `/tmp/wp-restore-backup-{timestamp}/`
  - Copies `wp-content/plugins/` to backup
  - Returns backup directory path
  - **Validation**: Backup created, size matches source

- [x] **Task 1.2**: Modify `restore_files()` to accept preservation options
  - Add `$options` parameter with `preserve_plugins` flag (default: true)
  - Add `preserve_themes` flag (default: false - allow theme restoration)
  - Skip plugin restore if `preserve_plugins=true`
  - Always restore themes by default (staging→production workflow)
  - Always restore uploads (existing behavior)
  - **Validation**: Plugins NOT overwritten when preserve_plugins=true, themes ARE restored

- [x] **Task 1.3**: Add `restore_preserved_plugins()` method
  - After database import, restore backed-up plugins over imported ones
  - Preserve our own `custom-migrator` plugin (existing logic)
  - **Validation**: Target plugins remain after restore, themes updated

- [x] **Task 1.4**: Add cleanup logic for temporary backups
  - Delete backup directory after successful restore
  - Keep backup on failure for debugging
  - **Validation**: No leftover /tmp directories after success

## Phase 2: Integrity Verification
- [x] **Task 2.1**: Add `verify_integrity()` method to `class-importer.php`
  - Check `active_plugins` option against filesystem
  - Check `template` (active theme) exists
  - Detect missing plugins referenced in database
  - Return warnings array
  - **Validation**: Correctly identifies missing plugins/themes

- [ ] **Task 2.2**: Add plugin version cataloging
  - Before restore, catalog target plugin versions using WP-CLI or file headers
  - After restore, compare versions
  - Include in detailed report
  - **Validation**: Version comparison accurate

## Phase 3: REST API Endpoint
- [x] **Task 3.1**: Update `class-api.php` to accept preservation options
  - Add `preserve_plugins` parameter to `/import` endpoint (default: true)
  - Add `preserve_themes` parameter to `/import` endpoint (default: false)
  - Pass options through to importer
  - **Validation**: Parameters correctly passed to importer

- [x] **Task 3.2**: Create `/restore` endpoint in `main.py`
  - Similar to `/clone` but for existing targets (no auto-provision)
  - Default `preserve_plugins=true` and `preserve_themes=false`
  - Call importer with preservation options
  - Return detailed restoration report
  - **Validation**: Endpoint callable, returns expected structure

- [x] **Task 3.3**: Add detailed reporting to response
  - Include database import stats
  - Include preserved plugin list with versions
  - Include restored theme list
  - Include integrity check results
  - Include warnings array
  - **Validation**: Response contains all expected fields

## Phase 4: Testing & Validation
- [ ] **Task 4.1**: Test Case - Plugin Update Preservation
  - Export site with plugin v1.0
  - Update plugin to v1.5 on target
  - Restore from export with preserve_plugins=true, preserve_themes=false
  - Assert plugin is v1.5, theme changes from staging applied, content is from export
  - **Pass criteria**: Plugin not downgraded, theme updated

- [ ] **Task 4.2**: Test Case - New Plugin Preservation
  - Export site
  - Install new plugin on target
  - Restore from export with preserve_plugins=true
  - Assert new plugin still exists
  - **Pass criteria**: New plugin not removed

- [ ] **Task 4.3**: Test Case - Integrity Detection
  - Restore with database referencing missing plugin
  - Assert integrity check warns about missing plugin
  - **Pass criteria**: Warning appears in response

- [ ] **Task 4.4**: Test Case - Force Overwrite Mode
  - Restore with preserve_plugins=false
  - Assert plugins are from export (downgrades happen)
  - **Pass criteria**: Plugins match export snapshot

- [ ] **Task 4.5**: Test boss's scenario
  - Export bonnel.ai to staging
  - Update plugin on bonnel.ai production
  - Restore staging to production
  - Verify plugin update preserved, content restored
  - **Pass criteria**: Boss's test passes

## Phase 5: Documentation & Polish
- [x] **Task 5.1**: Update API documentation
  - Document `/restore` endpoint parameters
  - Document response format
  - Add examples for common use cases
  - **Validation**: Documentation reviewed

- [x] **Task 5.2**: Add logging for restore operations
  - Log preservation decisions
  - Log backup creation/restoration
  - Log integrity check results
  - **Validation**: Logs visible in Loki/container logs

- [ ] **Task 5.3**: Consider UI updates (optional)
  - Add "Restore" button to wp-setup-service UI
  - Show preservation options as checkboxes
  - Display detailed results after restore
  - **Validation**: UI functional if implemented

## Dependencies
- Task 1.2 depends on 1.1 (needs backup to restore from)
- Task 1.3 depends on 1.2 (restoration logic needs options support)
- Task 2.1 can be developed in parallel with Phase 1
- Task 3.1 depends on 1.2 (API needs importer options support)
- Task 3.2 depends on 3.1 (endpoint uses API)
- Phase 4 depends on Phases 1-3 (testing needs implementation)

## Parallel Work Opportunities
- Phase 2 (Integrity) can be developed alongside Phase 1
- Documentation (5.1) can be drafted before implementation completes
- UI design (5.3) can be mocked up early

## Rollback Plan
If restoration causes issues:
1. Keep `/clone` endpoint unchanged as safe fallback
2. Add `force_overwrite` flag to revert to old behavior
3. Preserve backup directories on failure for manual recovery
4. Log all operations for post-mortem analysis
