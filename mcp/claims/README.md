# claims MCP server — task 003

Stdio MCP server over the claims store (`src/domestique/claims/store.py`).

## Tools

| Tool | Notes |
|---|---|
| `query_claims(athlete_id?, source_layer?, status?, text_contains?)` | read-only |
| `propose_claim(athlete_id, text, source_layer, horizon, evidence[])` | always creates status `candidate` |
| `attach_evidence(claim_id, kind, ref, note?)` | kinds: activity, interval, wellness, statement, reference, query |
| `add_binding(claim_id, metric, params, conditions?, human_token?)` | binds a claim to a predicted metric; gated unless the claim is a candidate, see below |
| `confirm_or_retire(claim_id, status, reason, human_token)` | human-gated, see below |
| `clear_flags(claim_id, reason, human_token)` | human-gated; clears the uninformative and overconfident flags, see below |

## Bindings

Claims are prose. A claim feeds a prediction only through a binding in
`claim_bindings` (`docs/schema.md`): one per claim and metric, replaced on a
second call.

- `metric`: `watts_at_hr`, `peak_hr`, `hrv_next_morning`, `sleep_hours`.
- `params`: `change_pct`, `offset`, `range_pct`, `range_abs`, and `rides`
  (watts at HR only: how many recent rides form the base). The rule is
  `expected = base * (1 + change_pct/100) + offset`, range
  `expected -/+ (expected * range_pct/100 + range_abs)`. A zero-width range
  is refused: it is not a prediction.
- `conditions` (all optional): `min_if`, `max_if` (planned intensity factor),
  `sports`, `start_hour_from`/`start_hour_to` (local hours, half-open, may
  wrap past midnight).

Unknown fields and wrong types are rejected before anything is written.
Binding a `candidate` claim needs no token: a candidate feeds no prediction
until a human confirms it. Binding an `active` or `retired` claim changes
what the athlete model predicts, so it needs the human token like
`confirm_or_retire`.

Example: "sleep falls about 40 min after evening intensity"

```json
{"claim_id": "…", "metric": "sleep_hours",
 "params": {"offset": -0.67, "range_abs": 0.33},
 "conditions": {"min_if": 0.85, "start_hour_from": 17, "start_hour_to": 23}}
```

## Calibration flags

The scorer flags a claim after at least ten scored predictions
(`src/domestique/claims/rules.py`):

- `uninformative`: mean absolute error under a third of the mean half-range.
  The range is too wide to mean anything; hits stop raising confidence and
  the claim is no longer the official source of a prediction (it is still
  scored as a shadow).
- `overconfident`: hit rate under 60%. The range is too narrow; every
  outcome while the hit rate stays under 60% costs an extra miss step.

Both stay until a human fixes the range (`add_binding`) and calls
`clear_flags`, which also starts a new calibration window.

## Human gate

`confirm_or_retire`, `clear_flags` (and `add_binding` on a claim that is not a candidate) refuse unless `human_token` equals the
`DOMESTIQUE_HUMAN_TOKEN` environment variable of the **server process**.
If the variable is unset, the tool is disabled entirely. The token is
compared in constant time. Agents are launched without this variable's value
in their prompt; the human exports it for the server and supplies the token
when confirming. The model never promotes a candidate to `active` by itself.

## Environment

- `DOMESTIQUE_DATABASE_URL` — Postgres 16 with the migrations applied (`0002_claims.sql` for
  claims, `0005_loop.sql` for `claim_bindings`, `0006_shadow_predictions.sql` for the
  calibration flags).
- `DOMESTIQUE_HUMAN_TOKEN` — shared secret for `confirm_or_retire`, `clear_flags` and gated
  `add_binding`.

## mcp.json example

```json
{
  "mcpServers": {
    "domestique-claims": {
      "command": ".venv/bin/python",
      "args": ["mcp/claims/server.py"],
      "env": {
        "DOMESTIQUE_DATABASE_URL": "postgresql://localhost/domestique",
        "DOMESTIQUE_HUMAN_TOKEN": "${DOMESTIQUE_HUMAN_TOKEN}"
      }
    }
  }
}
```
