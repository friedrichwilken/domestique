# Spec Delta

## Purpose
Deterministic metrics over executed-session data, so that "decoupling was 0.8%" is a fact the athlete model can cite rather than something a model estimates.

## ADDED Requirements

### Requirement: Efficiency factor
The system SHALL compute efficiency factor as normalised power divided by average heart rate for an activity or interval.

#### Scenario: Steady ride
- **WHEN** an activity has normalised power 168 W and average heart rate 137 bpm
- **THEN** efficiency factor is 1.23 (two decimals)

### Requirement: Decoupling
The system SHALL compute decoupling as (W/HR of the first half minus W/HR of the second half) divided by W/HR of the first half, as a percentage, over moving time.

#### Scenario: Flat heart rate
- **WHEN** power and heart rate are constant across the whole ride
- **THEN** decoupling is 0.0%

#### Scenario: Cardiac drift
- **WHEN** power is constant and heart rate in the second half is 5% higher than in the first half
- **THEN** decoupling is approximately 4.8%

### Requirement: Per-interval L/R balance
The system SHALL report L/R balance for each interval as the mean of the stream's balance samples within that interval.

#### Scenario: Balance shifts across reps
- **WHEN** a six-rep session's balance samples move from 63/37 in rep 1 to 59/41 in rep 6
- **THEN** the per-interval balances reflect that progression in order

### Requirement: Watts at a heart-rate band
The system SHALL compute mean power over all samples whose heart rate falls inside a given band.

#### Scenario: Band with no samples
- **WHEN** no sample falls inside the band
- **THEN** the result is null, not zero

### Requirement: Hours before bedtime
Given a configured bedtime, the system SHALL compute the hours between an activity's end and that bedtime on the same local day, negative if the activity ended after it.

#### Scenario: Late ride
- **WHEN** bedtime is 22:00 and an activity ends at 23:00 local
- **THEN** hours before bedtime is -1.0

### Requirement: Metrics are pure
Every metric SHALL be a function of its input data only: no database, no network, no clock.

#### Scenario: Same input twice
- **WHEN** a metric is called twice with the same input
- **THEN** it returns the same value
