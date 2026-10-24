# Tasks

## 1. Fixture season

- [x] 1.1 Generator with fixed seed for a 12-week synthetic season with the planted evening-intensity sleep effect, output committed under `evals/fixtures/season_a/`; test: regeneration is byte-identical

## 2. Harness

- [x] 2.1 Replay cursor view that refuses future dates; test: peek attempt returns nothing
- [x] 2.2 `evals/replay.py` producing per-week CSV and markdown with the headline last; test: headline-last scenario
- [x] 2.3 Loop on/off flag; test: sleep error shrinks only with the loop on
- [x] 2.4 `just eval` recipe
- [x] 2.5 Data-source switch (fixture season or the athlete's ingested history from the configured database) and the bootstrap review list output; test: bootstrap-review and no-season-claims scenarios against a fixture
