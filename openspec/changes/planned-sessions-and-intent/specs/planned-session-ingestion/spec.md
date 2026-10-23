# Spec Delta

## Purpose
Prescribed sessions are stored separately from executed ones and paired to them, so that plan-versus-execution is a join.

## ADDED Requirements

### Requirement: Planned sessions are ingested with their structure
The system SHALL ingest planned sessions from the intervals.icu events API with date, title, description, structured steps, planned load and planned intensity, keyed by source and external id, idempotently.

#### Scenario: Two sessions on one day
- **WHEN** a day has two planned sessions with the same title
- **THEN** both are stored as distinct rows with their own external ids

### Requirement: Planned and executed are paired
The system SHALL pair each planned session to at most one executed activity on the same local date and sport, preferring the closest start time, and record the pairing.

#### Scenario: Double day
- **WHEN** two planned sessions and two executed rides exist on one day
- **THEN** each planned session is paired to a different ride by start-time proximity

#### Scenario: Unpaired plan
- **WHEN** a planned session has no executed activity that day
- **THEN** it remains unpaired and is reported as missed, not deleted
