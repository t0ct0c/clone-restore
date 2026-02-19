# Capability: Observability

The system SHALL provide centralized logging and monitoring for all migration components.

## ADDED Requirements

### Requirement: Centralized Logging
The system SHALL aggregate logs from all Docker containers into a central Loki instance.

#### Scenario: Logs shipped to Loki
- **WHEN** a container produces a log line
- **THEN** it is automatically sent to the Loki server via the Docker logging driver.

### Requirement: Log Visualization
The system SHALL provide a Grafana interface to query and visualize logs.

#### Scenario: Query logs in Grafana
- **WHEN** a user accesses the Grafana UI
- **THEN** they can search logs by container name, customer ID, or error level.
