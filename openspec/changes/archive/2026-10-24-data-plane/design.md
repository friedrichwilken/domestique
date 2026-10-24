# Design

## Context

See proposal.md. Nothing exists yet beyond the repo scaffold. The intervals.icu client is a thin httpx wrapper over the public API. Schema in `docs/schema.md`.

## Goals / Non-Goals

**Goals:**
- Tables and metrics that every later change can trust without reading code.
- A test suite that runs with no network and no Postgres for the metric layer.

**Non-Goals:**
- Full stream retention. Only what the metrics need (watts, hr, cadence, lr, temp at 1 Hz).
- Any derived *interpretation* (zones, "durability intact"). Those are claims.

## Decisions

- **Postgres + TimescaleDB over DuckDB/Parquet.** A team deployment and the claims store need a server; the hypertable keeps streams cheap. Alternative: DuckDB for single-athlete. Rejected to avoid a migration later.
- **Metrics as pure functions over plain Python data, no numpy.** Keeps them trivially testable and importable from the MCP servers. Alternative: SQL views only. Kept as an option for cheap metrics, but the contract is the Python function.
- **Upsert on (source, external_id).** Idempotency is a property of the key, not of the job.
- **FTP stored on the activity row.** A stale athlete-level FTP silently mis-scores every ride; the number must travel with the ride.
- **Decoupling split by moving time, not by elapsed time.** Pauses otherwise bias the halves.

## Risks / Trade-offs

- intervals.icu field names drift. Mitigation: the ingest layer maps a named subset and stores the raw payload as jsonb.
- Docker may be unavailable on the dev machine. The migration is still written and the metric tests do not need it; the ingest tests use an in-memory repository.
