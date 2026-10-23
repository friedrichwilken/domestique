# Spec Delta

## Purpose
Human decisions live in versioned files that the system reads and never rewrites on its own, and safety rails are code the model cannot override.

## ADDED Requirements

### Requirement: Intent files are validated on load
The system SHALL load goals, constraints, overrides and rails from `$DOMESTIQUE_HOME/intent/*.yaml` (never from the repository), reject a file that fails schema validation with a message naming the file and field, and refuse to run with invalid intent.

#### Scenario: Missing field
- **WHEN** a goal lacks `set_by`
- **THEN** loading fails naming `goals.yaml` and `set_by`

### Requirement: Rails are pure functions
Each rail SHALL be a pure function of one day's data-plane rows and the athlete's baselines, returning either no action or an action with referral wording.

#### Scenario: Joint pain stops the plan
- **WHEN** a subjective entry for the day carries the tag `joint-pain`
- **THEN** the joint-pain rail returns `stop_plan` with wording that refers to the physio or surgeon and gives no training advice

#### Scenario: HRV floor
- **WHEN** the day's HRV is below 65% of the configured baseline
- **THEN** the HRV rail returns `downgrade_day`

#### Scenario: Quiet day
- **WHEN** no trigger condition holds
- **THEN** every rail returns no action

### Requirement: Intent outranks every other layer
When a constraint and an athlete-model claim conflict, the constraint SHALL win until a human changes the file.

#### Scenario: Observed tolerance vs stated constraint
- **WHEN** a claim says evening intensity is well tolerated and a constraint says hard sessions end by 19:00
- **THEN** the constraint applies and the conflict is reported, not resolved

### Requirement: The system only appends overrides
The system SHALL append to `overrides.yaml` and SHALL NOT modify goals, constraints or rails files.

#### Scenario: Override recorded
- **WHEN** a human overrules a prediction
- **THEN** an override entry is appended with the prediction at the time and the existing entries are unchanged
