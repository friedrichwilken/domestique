# prediction-loop Specification

## Purpose
Turn each prescription into something the system can be wrong about, so the athlete model converges on the person instead of the textbook.

## Requirements

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

### Requirement: Range calibration flags claims
When a claim has at least ten scored predictions and its mean absolute error is below one third of its mean half-range, the system SHALL flag the claim as uninformative and SHALL stop raising its confidence until the flag is cleared. When a claim has at least ten scored predictions and a hit rate below 60%, the system SHALL flag it as overconfident and SHALL lower its confidence by one miss step in addition to the normal scoring. Hit rate alone SHALL NOT flag a claim.

#### Scenario: Wide range
- **WHEN** a claim's ten scored predictions all hit and their errors average a tenth of the half-range
- **THEN** the claim is flagged uninformative and its confidence is unchanged by further hits

#### Scenario: Well-calibrated claim
- **WHEN** a claim's twelve scored predictions hit eleven times and their errors average half the half-range
- **THEN** the claim carries no flag

#### Scenario: Overconfident claim
- **WHEN** a claim's ten scored predictions hit five times
- **THEN** the claim is flagged overconfident and its confidence drops by an extra miss step

### Requirement: All applicable claims are scored
For each metric, the system SHALL record a prediction for every applicable claim, mark exactly one of them as the official prediction by the precedence rule, and SHALL score and adjust confidence for all of them when the outcome arrives.

#### Scenario: Rival takes over
- **WHEN** two claims apply to sleep hours, the official one misses four times in a row and the shadow one hits four times
- **THEN** after the fourth outcome the shadow claim has higher confidence and becomes the official source on the next prediction

#### Scenario: Reported prediction is the official one
- **WHEN** predictions are listed for a session
- **THEN** one prediction per metric is marked official and the shadows are marked as such
