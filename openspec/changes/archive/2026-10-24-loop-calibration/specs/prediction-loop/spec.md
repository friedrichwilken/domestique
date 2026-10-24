# Spec Delta

## REMOVED Requirements

### Requirement: Ranges that always hit are flagged
**Reason**: Replaced by range calibration; hit rate alone no longer flags a claim.

## ADDED Requirements

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
