# Spec Delta

## Purpose
Fuelling and fluid per ride are recorded as facts, from the platform where it has them and from a tagged comment where it does not.

## ADDED Requirements

### Requirement: Platform nutrition fields are ingested
The system SHALL store per activity the platform's energy expended, carbohydrate used and carbohydrate ingested, and per day its energy consumed, carbohydrate, protein, fat, hydration volume and hydration rating, leaving absent values null.

#### Scenario: Ride without logged intake
- **WHEN** an activity has energy expended and carbohydrate used but no carbohydrate ingested upstream
- **THEN** the first two are stored and carbohydrate ingested is null, not zero

### Requirement: A fuelling tag in a comment is parsed deterministically
The system SHALL recognise a comment line beginning with `#fuel` followed by any of `<n>ml`, `<n>l`, `<n>g`, `<n>kcal` in any order, SHALL store the parsed fluid in millilitres, carbohydrate in grams and energy in kilocalories against the activity, and SHALL leave anything else in the comment untouched as free text.

#### Scenario: Full tag
- **WHEN** a comment on an activity contains the line `#fuel 1.5l 240g 1100kcal`
- **THEN** the activity's intake is recorded as 1500 ml, 240 g, 1100 kcal

#### Scenario: Partial tag
- **WHEN** a comment contains `#fuel 2 bottles 90g`
- **THEN** carbohydrate is recorded as 90 g, fluid and energy stay null, and the words "2 bottles" remain in the comment text

#### Scenario: No tag
- **WHEN** a comment has no `#fuel` line
- **THEN** no intake is recorded and the comment is stored as free text only

#### Scenario: Later tag wins
- **WHEN** two comments on one activity both carry a `#fuel` line
- **THEN** the values from the later comment replace the earlier ones

### Requirement: Platform carbohydrate and tag carbohydrate are reconciled
When both the platform field and a tag give carbohydrate ingested for the same activity, the system SHALL keep the tag value and record that the platform value differed.

#### Scenario: Disagreement
- **WHEN** the platform says 60 g and the tag says 90 g
- **THEN** 90 g is stored and the 60 g is retained as the platform's value for audit
