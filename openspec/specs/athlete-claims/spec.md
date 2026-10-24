# athlete-claims Specification

## Purpose
A versioned store of what the system believes about one athlete, where every belief says where it came from and how sure it is.

## Requirements

### Requirement: Every claim has a source layer
A claim SHALL carry exactly one source layer from `observed`, `stated`, `prior`, and the store SHALL reject a claim without one.

#### Scenario: Missing layer
- **WHEN** a claim is proposed without a source layer
- **THEN** the store rejects it with an error naming the field

### Requirement: Claim history is append-only
Every change to a claim's confidence or status SHALL append a history row; history rows SHALL NOT be updated or deleted.

#### Scenario: Attempted edit
- **WHEN** an update or delete is attempted on a history row
- **THEN** the database rejects it

### Requirement: Confidence is bounded by layer
The store SHALL cap confidence by source layer: `observed` at 0.95, `stated` at 0.8, `prior` at 0.6.

#### Scenario: Prior at the cap
- **WHEN** a prior claim at 0.6 receives a confirming outcome
- **THEN** its confidence stays at 0.6 unless it is promoted

### Requirement: Every claim has a feedback horizon
A claim SHALL carry exactly one horizon from `day`, `week`, `season`, describing how long until its predictions can be scored, and the store SHALL reject a claim without one.

#### Scenario: Missing horizon
- **WHEN** a claim is proposed without a horizon
- **THEN** the store rejects it with an error naming the field

### Requirement: Confidence and promotion are bounded by horizon
Beyond the layer caps, the store SHALL cap `week` claims at 0.7 and `season` claims at 0.5, and SHALL never promote a `season` claim out of `prior`.

#### Scenario: Season claim with many hits
- **WHEN** a `season`-horizon prior records five consecutive hits
- **THEN** it remains `prior`, its confidence does not exceed 0.5, and a history row records the refused promotion

#### Scenario: Week claim promoted
- **WHEN** a `week`-horizon prior records five consecutive hits
- **THEN** it becomes `observed` with confidence no higher than 0.7

### Requirement: Promotion and retirement
A `prior` with five consecutive confirming outcomes on this athlete SHALL become `observed`; any claim whose confidence falls below 0.1 SHALL be retired; retired claims SHALL NOT feed predictions.

#### Scenario: Promotion
- **WHEN** a prior records its fifth consecutive hit
- **THEN** its source layer becomes `observed` and a history row records the promotion

#### Scenario: Retired claim ignored
- **WHEN** a retired claim would otherwise inform a prediction
- **THEN** the prediction is made without it

### Requirement: Proposals are candidates until a human confirms
Claims proposed by the system SHALL enter as `candidate`; moving to `active` or `retired` SHALL require a human token, and the MCP tool SHALL refuse without it.

#### Scenario: Confirm without token
- **WHEN** confirm_or_retire is called without a valid human token
- **THEN** the call is refused and the claim is unchanged

### Requirement: Precedence on conflict
When two active claims on the same subject conflict, the store SHALL return the one with the higher source layer (`observed` > `stated` > `prior`) and report the conflict.

#### Scenario: Observed vs prior
- **WHEN** an observed claim and a prior claim disagree on the same metric
- **THEN** the observed claim is returned and the prior is listed as conflicting
