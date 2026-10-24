# Tasks

## 1. Schema

- [x] 1.1 Write `migrations/0001_data_plane.sql` for all data-plane tables in `docs/schema.md`, `activity_streams` as a hypertable; test: migration applies cleanly on a fresh TimescaleDB container
- [x] 1.2 Add `docker-compose.yml` with a TimescaleDB service and a `just db-up` recipe

## 2. Fixtures

- [x] 2.1 Generate two synthetic fixture rides in `evals/fixtures/`: a 3 h steady ride with ~1% decoupling and a 6x5 min session whose balance moves 63/37 to 59/41; test: fixture loader round-trips both

## 3. Metrics

- [x] 3.1 Implement efficiency factor, decoupling, per-interval L/R balance, watts-at-HR-band, hours-before-bedtime in `src/domestique/metrics/`; test: one unit test per scenario in the `derived-metrics` spec

## 4. Ingestion

- [x] 4.1 Lift the intervals.icu client into `src/domestique/ingest/icu_client.py` with attribution; test: client builds auth from env or key file without a network call
- [x] 4.2 Implement activity, interval and wellness ingestion with upsert on (source, external_id) and FTP-at-ride; test: idempotent re-run and upstream-edit scenarios against an in-memory repository
- [x] 4.3 Add `just ingest --from <date>` and `just test`; test: `just test` runs pytest and ruff green
