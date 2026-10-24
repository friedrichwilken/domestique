# Design

## Context

See proposal.md. intervals.icu exposes `GET/POST /api/v1/activity/{id}/messages`; messages carry content, author, created, and optional `start_index`/`end_index`. Activities carry `calories`, `carbs_used`, `carbs_ingested`; wellness carries `kcalConsumed`, `carbohydrates`, `protein`, `fatTotal`, `hydrationVolume`, `hydration`. Depends on change `data-plane`.

## Goals / Non-Goals

**Goals:** a zero-infrastructure input channel (the athlete types on the ride) and an output channel that lands where the athlete already looks.
**Non-Goals:** natural-language extraction; a bot; writing to the plan or the description.

## Decisions

- **A tag, not a model, for intake.** `#fuel 1.5l 240g 1100kcal` is parsed by a small deterministic grammar. Alternative: let a model read free text. Rejected for v1: a wrong number in the data plane is worse than a null, and the tag costs the athlete five seconds.
- **Later comment wins.** Corrections are made by commenting again, which matches how people fix things on the platform.
- **Tag beats platform field, platform value retained.** The athlete's explicit statement outranks a synced estimate, but the audit trail keeps both.
- **Write switch defaults off.** Reading is harmless; writing to someone's account is not. The athlete opts in per config.
- **System comments are prefixed with a fixed marker** so they can be recognised, updated by the system, and never confused with the athlete's.
- **Source layer per statement, not per comment.** One debrief mixes observed numbers with a textbook explanation; each sentence says which it is.

## Risks / Trade-offs

- Comment ingestion is one request per activity. Fine at an athlete's volume; batch by date range if it ever matters.
- Athletes who never tag get null intake, and fuelling claims never gather evidence. That is correct behaviour, and the debrief can ask for the tag once.
