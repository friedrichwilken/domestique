# domestique tasks
default:
    @just --list

# run the unit tests
test:
    .venv/bin/pytest

# start local Postgres/TimescaleDB, migrate, ingest intervals.icu: just ingest --from 2026-09-01
# needs ICU_API_KEY (or ~/.icu_api_key) and ICU_ATHLETE_ID in the environment
ingest *args:
    docker compose up -d --wait
    .venv/bin/python -m domestique.ingest.icu {{args}}
