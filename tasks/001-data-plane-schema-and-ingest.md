# 001 — data plane: schema, migrations, ingestion from intervals.icu

**Depends on:** nothing. **Blocks:** 002, 003.

## Why

Everything downstream reasons over the data plane. It has to exist as
tables with tests before any model touches it.

## Deliverables

1. `migrations/0001_data_plane.sql` creating the tables in
   `docs/schema.md` (data plane section only), TimescaleDB hypertable for
   `activity_streams`.
2. `src/domestique/ingest/icu.py`: pull activities, intervals and wellness
   for a date range from intervals.icu into the tables. A thin httpx client over the public API. Idempotent on
   `external_id`.
3. `src/domestique/metrics/`: pure functions for efficiency factor,
   decoupling (first half vs second half W/HR), per-interval L/R balance,
   watts at a given HR band, hours-before-bed (needs a configured bedtime).
   Unit tests on fixture rides in `evals/fixtures/`.
4. `just ingest --from 2026-09-01` runs end to end against a local Postgres
   (docker compose file included).

## Not in scope

TrainingPeaks ingestion (002), streams beyond what the metrics need.
