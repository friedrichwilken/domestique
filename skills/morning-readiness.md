# morning-readiness

Runs each morning after wellness for the day is ingested, before the day's
session. It reads the night and today's plan and says what the data shows.
It does not change the plan.

## Hard rules (CLAUDE.md)

- **Every recommendation carries its source layer.** `observed` (this
  athlete's data), `stated` (the athlete said so), or `prior` (textbook).
  If a claim has no source layer, it does not exist.
- Pain, illness, injury: rails stop the plan and produce referral wording,
  never advice.
- Nothing writes a plan to the training platform without a human approving it.
- The intent behind a prescribed session is asked, never inferred from workout text.

## Inputs

| Input | Produced by |
|---|---|
| Last night: HRV, resting HR, sleep duration and score, CTL/ATL | `wellness`, written by `domestique.ingest.icu` (`map_wellness`) |
| Baselines (HRV and others), bedtime, `hr_max` | `config.load()` from `$DOMESTIQUE_HOME/config.yaml` |
| Rails results for today | `rails.registry.evaluate(day, baselines, limits)` with `limits_from_intent(intent.rails)`; `DayData` from `rails.load.load_day` |
| Intent: goals, constraints, overrides | `intent.loader.load_intent_from_config()` |
| Today's planned sessions | `ingest.plan_store.PgPlanStore.planned_on(athlete_id, day)` |
| Predictions already registered for today | `predictions` rows from `python -m domestique.loop.predict --date D` |
| Active claims with layer and confidence | claims MCP `query_claims(athlete_id, status="active")` |

## Order of reasoning

1. Rails. Any triggered rail's `wording` goes out first and verbatim.
   `stop_plan` and `no_intensity` end the brief there, apart from the plain
   wellness numbers. `downgrade_day` and `refuse_additional_load` are stated
   as what the rail did, not argued with.
2. The night as numbers: HRV against baseline (ratio), sleep against bedtime
   and the recent median. Label `observed`. A missing value stays missing.
3. Today's predictions, as registered: metric, expected, range, the claim
   and its layer. Do not re-predict; the loop already pre-registered them.
4. Constraints that touch today, quoted from the intent files (`stated`).
5. If the plan's purpose is unclear, write a question; do not guess what the
   session is for.

## Output shape

Short markdown brief, one statement per line, each prefixed with the layer
label from `output.comments.LAYER_LABEL`: "your data shows", "you told me",
"the literature says". Rail wording is printed as the rail returned it.

Synthetic example:

```
- (your data shows) HRV 71 against a baseline of 82 (87%), sleep 6.9 h against a 7.4 h median.
- (your data shows) Predicted for today: peak HR 171 [167, 175], from a prior with confidence 0.5.
- (you told me) No intensity after 19:00 on work days.
```

## Claims it may propose

None by default. A repeated morning pattern (for example HRV after a
specific kind of day) is left to the post-ride debrief and weekly review,
which see the outcomes. Questions for the athlete are written as
`analysis.plan_vs_execution.Question` rows through `save_questions`.
