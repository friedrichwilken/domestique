# web-console Specification

## Purpose
A local web console over the claims store and the day: the calibration report, the day view of rails, plan versus execution and open questions, and the human gate as a form, so the athlete can read and decide without a shell.

## Requirements

### Requirement: One report input from two sources
The system SHALL build a `ReportData` value from the database and SHALL build the same type from a replay result, and the renderer SHALL accept either without knowing its origin.

#### Scenario: Fixture page
- **WHEN** the replay runs on the fixture season with an HTML output path
- **THEN** a claims report page is written whose claim count equals the seed's claim count

### Requirement: Claims table with calibration
The claims page SHALL list every claim with status, source layer, horizon, confidence, scored count, hit rate, mean absolute error as a share of the mean half-range, and the uninformative and overconfident flags.

#### Scenario: Flagged claim
- **WHEN** a claim is flagged uninformative
- **THEN** its row shows the flag and the error-to-range share that caused it

### Requirement: Calibration strip shows error, not only hits
For each claim the page SHALL render a strip in which every scored prediction appears as a range band with its observed value as a marker; misses SHALL be distinguishable without colour.

#### Scenario: Miss marker
- **WHEN** a prediction's observed value lies outside its range
- **THEN** the strip renders a hollow marker with a text label for that prediction

#### Scenario: Long history
- **WHEN** a claim has more than sixty scored predictions
- **THEN** the strip shows the most recent sixty and states how many are omitted

### Requirement: Confidence against observed hit rate
The page SHALL render one marker per claim with at least one scored prediction, placed by stated confidence and observed hit rate, sized by scored count, with the diagonal drawn; claims with fewer than ten scored predictions SHALL be labelled as early.

#### Scenario: Unscored claim
- **WHEN** a claim has no scored predictions
- **THEN** it does not appear in the chart and does appear in the table

### Requirement: Day view
The system SHALL render, for one date, the rails results, the plan-versus-execution rows and the open questions, and SHALL print rail wording and question text unchanged.

#### Scenario: Triggered rail
- **WHEN** the day has a reported joint-pain tag
- **THEN** the page shows the rail's wording verbatim and no analysis of the day's rides

### Requirement: Human gate by form
The system SHALL accept confirm, retire and clear-flags decisions only through POST requests carrying the human token in the body, SHALL reject a wrong token with status 403 without writing, and SHALL write the same history row as the MCP tool.

#### Scenario: Correct token
- **WHEN** a POST confirms a candidate claim with the correct token and a reason
- **THEN** the claim is active and its history carries the reason and the deciding party

#### Scenario: Wrong token
- **WHEN** a POST carries a wrong token
- **THEN** the response is 403 and the claim is unchanged

### Requirement: Service runs beside the database
The system SHALL run as one container next to the database, bound to the loopback interface, reading configuration from a read-only mount and secrets from the environment only.

#### Scenario: Compose configuration
- **WHEN** the compose file is rendered
- **THEN** the app service publishes its port on 127.0.0.1 only and mounts the config path read-only
