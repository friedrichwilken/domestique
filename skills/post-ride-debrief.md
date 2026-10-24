# post-ride-debrief

Runs once per ridden session, after `just ingest` (activities, comments and
`#fuel` intake) and `python -m domestique.loop.score --date D` for that day.
Reasons over computed output only; it computes nothing itself.

## Hard rules (CLAUDE.md)

- **Every recommendation carries its source layer.** `observed` (this
  athlete's data), `stated` (the athlete said so), or `prior` (textbook).
  If a claim has no source layer, it does not exist.
- Pain, illness, injury: rails stop the plan and produce referral wording,
  never advice.
- The intent behind a prescribed session is asked, never inferred from workout text.
- Nothing writes a plan to the training platform without a human approving it.

## Inputs

| Input | Produced by |
|---|---|
| Ride row: NP, avg/max HR, IF, EF, decoupling, L/R balance, load | `activities`, written by `domestique.ingest.icu` (EF, decoupling, L/R from `domestique.metrics` when streams exist) |
| Per-interval power, HR, cadence, L/R | `activity_intervals` (`icu.map_intervals`) |
| Intake: fluid, carbohydrate (`carbs_source` tag or platform), energy | view `activity_nutrition` over `activity_intake` (`icu_comments.reconcile`) |
| Athlete comments, pinned stretches | `subjective` rows with tag `comment`, `start_index`/`end_index`; skip `is_system` |
| Plan next to execution | `analysis.plan_vs_execution.plan_vs_execution` rows (`JoinRow`) |
| Predictions, outcomes, claim adjustments | `loop.score.score_session` output; `predictions`/`outcomes` tables |
| Claims with source layer, confidence, flags | claims MCP `query_claims(athlete_id, status="active")` |
| Rails results | `rails.registry.evaluate(day, baselines, limits)`; no loader builds `DayData` from the database yet, the caller supplies it |

## Order of reasoning

1. Rails first. If any `RailResult` has action `stop_plan` or `no_intensity`,
   output its `wording` unchanged and stop. No analysis of the ride follows.
2. Plan vs execution. If the row carries a question (`hr_overshoot`), the
   session as ridden is not the one predicted: report the two numbers, pass the
   question through, and draw no physiology conclusion from the misses.
3. Outcomes. For each official prediction: hit or miss, actual against
   `[low, high]`, and the claim it came from with its layer. Shadows are not
   reported to the athlete.
4. Numbers worth one line each: decoupling, EF, interval fade, L/R drift,
   intake per hour where `activity_nutrition` has a value. A missing intake is
   reported as missing, never estimated.
5. Comments: anything the athlete said is `stated`; quote it, do not reword it
   into a measurement.
6. Explanations from the literature only after the numbers, labelled `prior`.

## Output shape

A list of `output.comments.Remark`, each statement an
`output.comments.Statement(text, layer)`, pinned with `Pin.from_interval`
when it concerns one interval. `output.comments.write_debrief` renders them
with the `[domestique]` marker and posts only when `write_comments` is true.

Synthetic example, as rendered:

```
[domestique]
- (your data shows) Rep 5 held 312 W against 318 W on rep 1, at 4 bpm higher HR.
- (you told me) The last climb felt heavy.
- (the literature says) Some HR drift across repeated efforts is expected.
```

## Claims it may propose

Only through the claims MCP `propose_claim` (always `candidate`), with
evidence pointing at the activity or interval. Only `day`-horizon patterns
seen on several rides; one ride is evidence for an existing claim, not a new
claim. Never call `confirm_or_retire` or a gated `add_binding`.
