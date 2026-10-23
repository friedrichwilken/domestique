# Spec Delta

## Purpose
Executed sessions and daily wellness enter the data plane from external sources so that every downstream layer reasons over the same normalised facts.

## ADDED Requirements

### Requirement: Idempotent activity ingestion
The system SHALL ingest executed activities for a date range from intervals.icu into the data plane, keyed by source and external id, such that re-running ingestion for the same range changes nothing.

#### Scenario: Re-run is a no-op
- **WHEN** ingestion runs twice for the same date range with unchanged upstream data
- **THEN** the row count and contents of activities, intervals and wellness are identical after the second run

#### Scenario: Upstream edit updates the row
- **WHEN** an activity's name or FTP changes upstream and ingestion re-runs
- **THEN** the existing row is updated in place and no duplicate row is created

### Requirement: FTP at ride time is stored per activity
Each ingested activity SHALL carry the FTP it was scored against at ingestion time, independent of the athlete's current FTP.

#### Scenario: FTP changes later
- **WHEN** the athlete's FTP changes after an activity was ingested
- **THEN** the stored activity still reports the FTP in force when it was ridden

### Requirement: Intervals are stored per activity
The system SHALL store each activity's intervals with kind, start, duration, average power, average and max heart rate, cadence and L/R balance.

#### Scenario: Interval session
- **WHEN** an activity with six work intervals is ingested
- **THEN** six interval rows of kind `work` exist for it, in order, each with its own averages

### Requirement: Wellness is stored per day with its source
The system SHALL store HRV, resting heart rate, sleep seconds, sleep score, weight, CTL and ATL per athlete per day, recording the source.

#### Scenario: Missing field
- **WHEN** a day has HRV but no sleep data upstream
- **THEN** the row stores HRV and leaves sleep fields null rather than zero

### Requirement: No live calls in tests
Automated tests SHALL run against fixtures only and SHALL NOT contact intervals.icu or any external service.

#### Scenario: Offline test run
- **WHEN** the test suite runs with no network and no API key
- **THEN** all ingestion tests pass
