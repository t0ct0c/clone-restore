## 1. POC Design & Spec
- [ ] 1.1 Clarify source/target assumptions (same DB server vs separate, same filesystem vs remote).
- [ ] 1.2 Decide trigger mechanism for automation (WP-CLI command, cron, or HTTP endpoint) for export.
- [ ] 1.3 Decide how the target instance obtains the archive (shared disk path, HTTP download, or push).
- [ ] 1.4 Draft `wp-clone-automation` capability spec (requirements + scenarios) for automated export/import.

## 2. Export Automation
- [ ] 2.1 Add spec requirement for a non-interactive export trigger that uses existing `ai1wm_export` pipeline.
- [ ] 2.2 Add spec requirement for configuring export options (e.g., full site, optional exclusions) via automation.
- [ ] 2.3 Add spec requirement for storing the resulting `.wpress` file in a deterministic location for the POC.

## 3. Import Automation
- [ ] 3.1 Add spec requirement for a non-interactive import trigger that uses the `ai1wm_import` pipeline.
- [ ] 3.2 Add spec requirement for pointing the import at a specific `.wpress` archive path/URL without UI.
- [ ] 3.3 Add spec requirement describing how the system handles destructive actions (overwriting target DB/files) in automated mode.

## 4. Orchestration & Safety
- [ ] 4.1 Add spec requirement for a high-level "clone" operation that sequences export → transfer → import.
- [ ] 4.2 Add spec requirement for basic status/progress reporting that can be consumed programmatically.
- [ ] 4.3 Add spec requirement for guardrails in the POC (e.g., restrict to non-production, explicit opt-in).

## 5. Validation & Docs
- [ ] 5.1 Define validation scenarios for a successful automated clone (same content, URLs adjusted as per existing import logic).
- [ ] 5.2 Define failure scenarios (export failure, transfer failure, import failure) and expected behavior.
- [ ] 5.3 Update project docs/spec references to include `wp-clone-automation` capability and how to use it.
