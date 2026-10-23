# Proposal

## Why

Every other cornerstone reasons over facts. Until executed rides, wellness and the FTP each ride was scored against exist as tables with tested derived metrics, no model may touch the data. This is cornerstone 1 (deterministic data plane) and the first change by build order. Mirrors `tasks/001-data-plane-schema-and-ingest.md`.

## What Changes

- New Postgres + TimescaleDB schema for activities, streams, intervals, wellness, FTP history, subjective inputs, context and tests.
- Idempotent ingestion of activities, intervals and wellness from intervals.icu.
- Derived metrics as pure, unit-tested functions: efficiency factor, decoupling, per-interval L/R balance, watts at a heart-rate band, hours before bedtime.
- Synthetic fixture rides so tests never need real athlete data or a live API.

Out of scope: planned sessions from TrainingPeaks (change `planned-sessions-and-intent`), full stream retention beyond what metrics need, any interpretation of the numbers.

## Capabilities

### New Capabilities
- `activity-ingestion`: executed sessions and wellness enter the data plane from external sources, idempotently, with the FTP in force at ride time.
- `derived-metrics`: deterministic metrics computed from executed-session data, defined as pure functions with stated formulas.

### Modified Capabilities
- none

## Impact

New package `src/domestique/ingest`, `src/domestique/metrics`; `migrations/0001_data_plane.sql`; `docker-compose.yml`; `evals/fixtures/`. Depends on an intervals.icu API key at run time only.
