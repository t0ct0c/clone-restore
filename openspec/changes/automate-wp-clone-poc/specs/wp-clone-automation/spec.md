## ADDED Requirements

### Requirement: Automated WP clone POC
The system SHALL provide a way to perform a non-interactive clone of a single WordPress instance to another instance using the existing All-in-One WP Migration export/import pipelines.

#### Scenario: Trigger clone via WP-CLI
- **WHEN** an operator invokes a dedicated WP-CLI command on the source instance with parameters for target location and basic options
- **THEN** the system SHALL run a full export via the `ai1wm_export` pipeline and store a `.wpress` archive at a deterministic, configurable location
- **AND** the system SHALL expose enough information (e.g., archive path) for the target instance to consume it.

#### Scenario: Trigger import via WP-CLI on target
- **WHEN** an operator invokes a dedicated WP-CLI command on the target instance pointing at a specific `.wpress` archive path
- **THEN** the system SHALL run a full import via the `ai1wm_import` pipeline using that archive
- **AND** the system SHALL apply the same validations and prompts as the existing manual import flow, with options to auto-confirm destructive actions for POC use.

#### Scenario: End-to-end clone using shared storage
- **WHEN** the source instance completes an automated export to a shared storage path accessible to the target
- **AND** the operator (or script) invokes the target-side WP-CLI import using that path
- **THEN** the target SHALL be updated to match the source site’s content and configuration subject to existing import semantics (e.g., URL replacement)
- **AND** the system SHALL log success or failure in a way that can be inspected programmatically (e.g., via log files or WP-CLI exit codes).

### Requirement: Safety constraints for automated clone
The system SHALL make it explicit that automated clone operations are potentially destructive and SHOULD be used in controlled environments for the POC.

#### Scenario: Explicit opt-in
- **WHEN** an operator attempts to run the automated clone commands without an explicit opt-in flag or configuration
- **THEN** the system SHALL refuse to proceed and explain that the operation is destructive and intended for non-production use unless explicitly confirmed.

#### Scenario: Version compatibility check
- **WHEN** the automated clone is initiated between source and target instances
- **THEN** the system SHOULD check that the All-in-One WP Migration plugin version is compatible on both sides and warn if not.

## MODIFIED Requirements

## REMOVED Requirements
