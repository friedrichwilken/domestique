# weekly-review

Runs once a week over the last seven days. Summarises what the loop learned,
what is still open, and what needs a human. Written for the athlete and for
anyone they choose to share it with.

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
| Sessions planned, ridden, missed | `analysis.plan_vs_execution.plan_vs_execution` per day (`status` `paired` or `missed`) |
| Load: CTL/ATL per day, FTP in force | `wellness`, `ftp_history` (written by `domestique.ingest.icu`) |
| Outcomes of the week: hit or miss per prediction, official and shadow | `predictions` joined to `outcomes` (written by `loop.score.apply`) |
| Claim movement: confidence trajectory, promotions, retirements | `claim_history` rows; claims MCP `query_claims` for the current state |
| Calibration flags | `claims.uninformative`, `claims.overconfident` (rules in `claims/rules.py`) |
| Candidates waiting for review | claims MCP `query_claims(status="candidate")` |
| Open questions | `questions` rows with status open, `for` athlete or reviewer |
| Rails that triggered | `rails.registry.evaluate` results for each day of the week |
| Goals and constraints | `intent.loader.load_intent_from_config()` |

## Order of reasoning

1. Rails that triggered this week, each with its wording as returned. If a
   `stop_plan` rail is still in force, the review says so first and makes no
   training statement after it.
2. Execution: planned against ridden, missed sessions by date. A gap between
   prescription and ride is a question (from plan-vs-execution), not an error.
3. The loop: for each claim scored this week, hits/scored, confidence before
   and after, layer and horizon. Promotions and retirements by name.
   `week`-horizon claims cap lower; `season` claims are never promoted and are
   always voiced as "the literature says".
4. Flags: uninformative or overconfident claims, with the range fix they need.
   Only a human clears them (`clear_flags`).
5. Candidates for the athlete to confirm, edit or reject, each with horizon,
   hit rate and evidence rides.
6. Open questions, oldest first.

## Output shape

Markdown with the sections above, in that order. Every line carries its
layer label ("your data shows", "you told me", "the literature says").
Numbers come from the inputs; no new computation in prose.

Synthetic example line:

```
- (your data shows) "Next-morning HRV falls 5-10% after a hard session": 3 of 4 hits this week, confidence 0.50 -> 0.65, prior, day horizon.
```

## Claims it may propose

Through `propose_claim` only, as `candidate`, when the week's outcomes show
a consistent miss on one side for one metric and bucket. Never a `season`
claim outside `prior`. Confirmation is human: never call `confirm_or_retire`.
