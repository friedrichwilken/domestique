# Proposal

## Why

Fuelling and fluid per ride are facts the claims need (a fuelled and an unfuelled long ride are different experiments), but intervals.icu only stores carbohydrate per activity and fluid per day. Comments on the activity are the athlete's existing input channel, in both directions: what they ate and drank, how it felt, and later the system's reading of the session. Serves cornerstone 1 (data plane) and the interfaces section of DESIGN.md.

## What Changes

- Ingest per-activity `calories`, `carbs_used`, `carbs_ingested` and the daily nutrition and hydration fields from intervals.icu.
- Ingest activity comments into the subjective table, keyed to the activity and, where present, to the stretch of the ride they point at.
- Parse a small fuelling tag inside comments deterministically into fluid, carbohydrate and energy intake per ride.
- Write the nightly debrief as a comment on the activity, pinned to the interval it refers to, behind a per-athlete config switch that defaults to off.

Out of scope: a chat bot; any write to the activity description or the plan; model-based extraction of free text.

## Capabilities

### New Capabilities
- `ride-nutrition`: fuelling and fluid per ride enter the data plane from platform fields and from a tagged comment.
- `activity-comments`: comments are read as the athlete's input channel and, when enabled, written as the system's output channel, pinned to the ride.

### Modified Capabilities
- none (the `activity-ingestion` delta in change `data-plane` is extended here rather than modified, because that change is not yet archived)

## Impact

`src/domestique/ingest/icu.py` (new fields, comments), new `src/domestique/ingest/fuel_tag.py`, new `src/domestique/output/comments.py`, config switch `write_comments`, schema additions in `docs/schema.md`.
