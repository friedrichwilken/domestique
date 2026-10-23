# Spec Delta

## Purpose
Turn each prescription into something the system can be wrong about, so the athlete model converges on the person instead of the textbook.

## ADDED Requirements

### Requirement: Predictions cite claims
Before a planned session, the system SHALL record predictions for watts at target heart rate, peak heart rate, next-morning HRV and sleep hours, each with a range and the ids of the claims it derives from.

#### Scenario: No applicable claim
- **WHEN** no active claim informs a metric
- **THEN** no prediction is recorded for that metric and the gap is reported

### Requirement: Outcomes score predictions
After the data for a session and the following morning exists, the system SHALL record the actual value and the signed error for each prediction.

#### Scenario: Scored once
- **WHEN** the scoring job runs twice for the same session
- **THEN** each prediction has exactly one outcome

### Requirement: Confidence moves by a documented rule
A hit (actual inside the range) SHALL raise each cited claim's confidence by 0.1, capped by its layer; a miss SHALL lower it by 0.15, floored at 0.05. The rule SHALL be documented where it is implemented.

#### Scenario: Miss lowers confidence
- **WHEN** a prediction citing a claim at 0.5 misses
- **THEN** the claim is at 0.35 with a history row naming the prediction

### Requirement: Misses that look like intent become questions
When a miss co-occurs with a plan-vs-execution overshoot flag for the same session, the system SHALL draft a question for the athlete instead of adjusting physiology claims.

#### Scenario: Overshoot miss
- **WHEN** peak heart rate missed high and the session is flagged as an overshoot
- **THEN** a question for the athlete is created and the cited claims' confidence is unchanged
