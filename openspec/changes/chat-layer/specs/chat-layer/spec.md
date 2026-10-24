# Spec Delta

## ADDED Requirements

### Requirement: Modes come from the skill files
The chat SHALL load each mode's system prompt verbatim from its file under `skills/`, prefixed only with date, timezone and athlete id from configuration.

#### Scenario: Prompt equals file
- **WHEN** the post-ride debrief mode starts
- **THEN** its system prompt ends with the exact content of `skills/post-ride-debrief.md`

### Requirement: The model holds a short allow-list
The model SHALL receive exactly the console read routes and the ungated claims tools, and SHALL NOT receive `confirm_or_retire`, `add_binding` or `clear_flags`.

#### Scenario: Gated tools absent
- **WHEN** the tool list is built for any mode
- **THEN** none of the gated tool names is present

### Requirement: Every statement carries a source layer
The chat SHALL check each reply for the three layer labels before showing it, SHALL send unlabelled fragments back to the model once, and SHALL show fragments that remain unlabelled with a visible mark rather than drop or pass them.

#### Scenario: Unlabelled bullet
- **WHEN** a reply contains a bullet with no layer label
- **THEN** the model is asked once to label it, and if it stays unlabelled it is shown marked "unlabelled"

#### Scenario: Tool wording exempt
- **WHEN** a reply quotes a rail's wording or a question text returned by a tool
- **THEN** that text passes the check unchanged

### Requirement: No route from the model to the database
The chat service SHALL hold no database connection string and no human token in its environment.

#### Scenario: Compose environment
- **WHEN** the compose file is rendered
- **THEN** the chat service's environment contains neither a database URL nor the human token

### Requirement: Internet-facing image is not root
The chat image and the app image SHALL run as a non-root user set by a build argument.

#### Scenario: User in image
- **WHEN** either image is built with the default arguments
- **THEN** the process runs as uid 1000
