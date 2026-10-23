# Spec Delta

## Purpose
Activity comments are the athlete's input channel and, when the athlete allows it, the system's output channel, so that everything about a ride lives on the ride.

## ADDED Requirements

### Requirement: Comments are ingested as subjective input
The system SHALL ingest every comment on an activity into the subjective table with its author, timestamp, text, and the ride indices it is pinned to when present, idempotently by comment id.

#### Scenario: Pinned comment
- **WHEN** a comment carries a start and end index into the ride
- **THEN** the stored row carries both indices so it can be joined to the interval covering them

#### Scenario: Edited comment
- **WHEN** a comment's text changes upstream and ingestion re-runs
- **THEN** the stored row is updated and no duplicate is created

### Requirement: Debrief comments are written only when enabled
The system SHALL write a comment to an activity only if the athlete's configuration sets `write_comments: true`; the default SHALL be false, and with it false no write to the platform occurs.

#### Scenario: Default configuration
- **WHEN** `write_comments` is absent from the configuration
- **THEN** the debrief is produced locally and nothing is posted

### Requirement: Written comments carry their source layer
Every comment the system writes SHALL state, per statement, whether it comes from this athlete's data, from what the athlete said, or from the literature, and SHALL be pinned to the interval it refers to when it refers to one.

#### Scenario: Interval remark
- **WHEN** the debrief remarks on the sixth work interval
- **THEN** the comment is pinned to that interval's indices and the remark names its source layer

### Requirement: The system never edits or deletes comments it did not write
The system SHALL NOT update or delete comments authored by anyone else, and SHALL mark its own comments so they are distinguishable.

#### Scenario: Athlete comment present
- **WHEN** the athlete has commented on a ride and the system posts its debrief
- **THEN** the athlete's comment is unchanged and the system's comment is identifiable as the system's
