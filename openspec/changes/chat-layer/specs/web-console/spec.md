# Spec Delta

## ADDED Requirements

### Requirement: JSON routes for clients
The console SHALL serve the day view and the athlete's open questions as JSON, with rail wording and question text unchanged, so that a client reads them without HTML.

#### Scenario: Rail wording and question text in JSON
- **WHEN** a client reads `/day/{date}.json` for a day with a triggered rail and an open question
- **THEN** the rail's wording and the question's text appear verbatim in the JSON

#### Scenario: Open questions
- **WHEN** a client reads `/questions.json`
- **THEN** every open question of the athlete is listed with its text unchanged

### Requirement: Claim history is visible
The console SHALL show each claim's history under its row on the claims page and SHALL serve it as JSON, so that a decision made through the gate is visible afterwards.

#### Scenario: History after a decision
- **WHEN** a POST confirms or retires a candidate with the correct token and a reason
- **THEN** `/claims/{id}/history.json` carries a row with that reason and the deciding party `console`
