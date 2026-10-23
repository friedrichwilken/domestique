# Spec Delta

## Purpose
Measure whether the athlete model learns, by replaying a season with no access to the future.

## ADDED Requirements

### Requirement: No future leakage
At each replayed day, predictions SHALL be made using only data dated on or before that day.

#### Scenario: Peek attempt
- **WHEN** the predictor requests wellness for a date after the replay cursor
- **THEN** the harness returns nothing for it

### Requirement: Error per metric over time
The harness SHALL emit, per metric, the signed error and hit rate per replayed week as CSV, and a markdown summary whose last line is the mean absolute error across metrics for the final four weeks.

#### Scenario: Headline last
- **WHEN** the replay completes
- **THEN** the final line of the summary is the headline number

### Requirement: A planted effect is discoverable
The fixture season SHALL contain a planted effect (evening intensity costs about one hour of sleep) and the harness SHALL show the sleep prediction error for evening-intensity days shrinking over the season when the loop runs.

#### Scenario: Loop on vs off
- **WHEN** the replay runs with confidence updates disabled
- **THEN** the sleep error on evening-intensity days does not shrink, and with updates enabled it does

### Requirement: The replay can bootstrap an athlete model from history
When run against the athlete's own ingested history with the loop enabled, the harness SHALL produce a review list of candidate claims, each with horizon, hit rate, confidence and evidence references, and SHALL write nothing to the claims store until a human confirms through the gated tool.

#### Scenario: Bootstrap review
- **WHEN** the replay runs over six months of ingested history with the loop on
- **THEN** a review list is produced and the claims store contains no new active claims

#### Scenario: No season claims from a backfill
- **WHEN** the review list is produced
- **THEN** it contains no claim with horizon `season` outside the `prior` layer
