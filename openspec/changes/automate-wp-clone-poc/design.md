## Context
We already have robust export/import pipelines via All-in-One WP Migration, including WP-CLI integration and AJAX-driven multi-step flows. The missing piece is an orchestrated, non-interactive clone that takes a known source WordPress and reproducibly applies its state to a target instance.

## Goals / Non-Goals
- Goals:
  - Enable an end-to-end automated clone of a single WordPress instance to another using existing export/import primitives.
  - Keep the POC simple: same network, same plugin version, no multi-site specifics unless trivial.
  - Make the automation invocable from the command line or a single HTTP call.
- Non-Goals:
  - General-purpose multi-tenant migration orchestration.
  - UI changes for end users.
  - Cross-cloud, cross-network archive transport.

## Decisions
- Decision: Use WP-CLI as the primary trigger for the POC clone operation, since the plugin already includes WP-CLI support and it naturally supports non-interactive automation.
- Decision: Assume a shared filesystem path (e.g., NFS or local disk in Docker) to move `.wpress` archives from source to target for the POC, and leave remote transport to future extensions.
- Decision: Represent clone behavior as a new capability `wp-clone-automation` in OpenSpec to keep requirements decoupled from existing generic export/import specs.

## Risks / Trade-offs
- Risk: Automated imports are destructive (they overwrite DB/files); mitigated by explicit opt-in and limiting to non-production environments in the POC.
- Risk: Long-running exports/imports may hit timeouts; mitigated by relying on existing chunked HTTP/WP-CLI behavior and recommending proper PHP/timeouts in docs.

## Migration Plan
- Add the `wp-clone-automation` spec and validate via OpenSpec.
- Implement a WP-CLI-driven flow that uses existing export/import commands to perform a clone between two instances that share plugin versions and filesystem access.
- Add basic docs for how to run the clone and verify results.

## Open Questions
- Should the POC also support a pure-HTTP flow (source pushing archive to target) or is WP-CLI-only acceptable for now?
- Do we need to support multi-site network cloning in this iteration, or can we constrain to single-site?
