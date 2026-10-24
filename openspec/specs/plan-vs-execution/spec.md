# plan-vs-execution Specification

## Purpose
Show what was prescribed next to what was ridden, and when they differ by more than a margin, ask the athlete instead of deciding why.

## Requirements

### Requirement: The join reports both sides
For a date, the system SHALL return each planned session with its prescribed intensity text and heart-rate guidance alongside the paired activity's normalised power, average and peak heart rate and intensity factor.

#### Scenario: Paired double day
- **WHEN** two planned sessions are paired to two rides
- **THEN** two rows are returned, each with both the prescription and the execution

### Requirement: Overshoot produces a question, never a conclusion
When executed intensity exceeds the prescribed intensity by more than a configured margin, the system SHALL emit a question addressed to the athlete that states the numbers and asks whether the execution matched the intent. It SHALL NOT label the session as an execution error.

#### Scenario: Sweet-spot text, VO2 execution
- **WHEN** the prescription says ~75% of max heart rate and the ride averaged 90% of max in the work intervals
- **THEN** a question for the athlete is produced containing both numbers and no judgement
