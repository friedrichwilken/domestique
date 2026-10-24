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

### Requirement: Conflicts are found through bindings and tags
A constraint MAY carry `tags` naming the subjects it governs as claim-binding metrics. The system SHALL report one conflict per pair of a tagged constraint and an active claim that has a binding whose metric is among those tags, SHALL NOT match claims to constraints by their text, and SHALL name the constraint as the one that applies and list the claim with its source layer and confidence, in factual wording.

#### Scenario: Observed work-HR tolerance vs a tagged stated constraint
- **WHEN** an active `observed` claim "tolerates work HR up to X" is bound to `peak_hr` and a constraint set by the athlete is tagged `peak_hr`
- **THEN** the report returns the constraint as applying and lists the claim as conflicting with source layer `observed` and its confidence

#### Scenario: Shared words without a shared binding
- **WHEN** a claim's text repeats a constraint's text but none of its bindings has a metric in the constraint's tags
- **THEN** no conflict is reported

### Requirement: The system only appends overrides
The system SHALL append to `overrides.yaml` and SHALL NOT modify goals, constraints or rails files.

#### Scenario: Override recorded
- **WHEN** a human overrules a prediction
- **THEN** an override entry is appended with the prediction at the time and the existing entries are unchanged
