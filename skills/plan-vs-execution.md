# plan-vs-execution

Runs per day with planned sessions, after `just ingest` and plan ingestion
(`domestique.ingest.icu_plan`, which also pairs plans to activities). It
compares what was prescribed with what was ridden and turns any gap into a
question. It never decides that the athlete executed wrongly.

## Hard rules (CLAUDE.md)

- **Every recommendation carries its source layer.** `observed` (this
  athlete's data), `stated` (the athlete said so), or `prior` (textbook).
  If a claim has no source layer, it does not exist.
- The intent behind a prescribed session is asked, never inferred from workout text.
- Nothing writes a plan to the training platform without a human approving it.
- Pain, illness, injury: rails stop the plan and produce referral wording,
  never advice.

## Inputs

| Input | Produced by |
|---|---|
| Rows per planned session: title, description, parsed HR guidance, executed session, work-interval HR as % of max, `paired`/`missed` | `analysis.plan_vs_execution.plan_vs_execution(PgPlanStore(conn), athlete_id, day, hr_max)` |
| Drafted questions with both numbers in `context` | `JoinRow.questions` (`overshoot_question`, kind `plan_vs_execution.hr_overshoot`) |
| Pairing | `ingest.pairing.pair`, stored as `planned_sessions.paired_activity_id` |
| `hr_max` | `config.load().hr_max` |
| Stated intent for the session, when the athlete gave it | `subjective` comments on the activity, intent `overrides` via `intent.loader` |
| Rails results for the day | `rails.registry.evaluate` |

## Order of reasoning

1. Rails. A triggered `stop_plan` or `no_intensity` rail: output its wording
   unchanged; the comparison is not a training question that day.
2. For each row: `missed` sessions are listed by date and title, without
   judgement or a guessed reason.
3. `paired` rows: prescribed guidance as written (`HrGuidance.text`) next to
   the work-interval HR as ridden. Both numbers, `observed` for the ride.
4. Where a row carries a question, pass its text through unchanged. Do not
   add a reading of the description; descriptions are often boilerplate.
5. Where the athlete already stated the intent (comment or override), quote
   it as `stated` and drop the question it answers.
6. Rows without parsed guidance: report the ride numbers only.

## Output shape

One block per planned session: date, title, status, the two numbers, then
the question if any. Questions are stored with `save_questions(conn,
questions)` as open items in the `questions` table.

Synthetic example:

```
2026-09-09 "Endurance 2h" (paired)
- (your data shows) Work intervals averaged 84% of max against guidance of 70-75%.
- Question: Did the session as ridden match what you intended for it?
```

## Claims it may propose

None. A gap here is about intent, not physiology. The scorer
(`loop.score`) skips claim adjustments on a flagged session; this skill
does not override that.
