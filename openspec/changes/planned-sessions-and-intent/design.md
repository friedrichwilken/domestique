# Design

## Context

See proposal.md. Depends on change `data-plane`. The TrainingPeaks client is a thin wrapper over its API.

## Goals / Non-Goals

**Goals:** a trustworthy pairing and a rails module that is boringly testable.
**Non-Goals:** interpreting the intent behind a prescription; emitting plans.

## Decisions

- **Intent in YAML on the athlete's machine (`$DOMESTIQUE_HOME/intent/`), not in the repo or the database.** Humans edit it; the athlete may keep it in a private git repo of their own. The system appends to overrides only.
- **Rails as a registry of pure functions with a shared signature** `(day: DayData, baselines) -> RailResult | None`. Each rail has a triggering and a non-triggering fixture. Alternative: a rule DSL in YAML evaluated by code. Rejected for now: four rails do not need a DSL; `rails.yaml` stays documentation plus thresholds.
- **Overshoot margin configurable, default 10 percentage points of HRmax** on work intervals, not on the whole ride, so warm-ups do not dilute it.
- **Pairing by closest start time on the same local day and sport.** Simple and right for double days.

## Risks / Trade-offs

- TrainingPeaks descriptions are boilerplate; the join must not pretend they are intent. Mitigated by the question-not-conclusion requirement.
- Until the `questions` table exists, the join returns question objects in memory.
