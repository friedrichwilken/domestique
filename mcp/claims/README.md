# claims MCP server — task 003

Stdio MCP server over the claims store (`src/domestique/claims/store.py`).

## Tools

| Tool | Notes |
|---|---|
| `query_claims(athlete_id?, source_layer?, status?, text_contains?)` | read-only |
| `propose_claim(athlete_id, text, source_layer, horizon, evidence[])` | always creates status `candidate` |
| `attach_evidence(claim_id, kind, ref, note?)` | kinds: activity, interval, wellness, statement, reference, query |
| `confirm_or_retire(claim_id, status, reason, human_token)` | human-gated, see below |

## Human gate

`confirm_or_retire` refuses unless `human_token` equals the
`DOMESTIQUE_HUMAN_TOKEN` environment variable of the **server process**.
If the variable is unset, the tool is disabled entirely. The token is
compared in constant time. Agents are launched without this variable's value
in their prompt; the human exports it for the server and supplies the token
when confirming. The model never promotes a candidate to `active` by itself.

## Environment

- `DOMESTIQUE_DATABASE_URL` — Postgres 16 with `migrations/0002_claims.sql` applied.
- `DOMESTIQUE_HUMAN_TOKEN` — shared secret for `confirm_or_retire`.

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
