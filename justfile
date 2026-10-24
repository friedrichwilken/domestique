default:
    @just --list

# install dev deps and git hooks
setup:
    python3 -m venv .venv
    .venv/bin/pip install -e '.[dev]'
    .venv/bin/pre-commit install

# everything CI runs
check: lint typecheck test

lint:
    .venv/bin/ruff check .
    .venv/bin/ruff format --check .

fix:
    .venv/bin/ruff check --fix .
    .venv/bin/ruff format .

typecheck:
    .venv/bin/mypy

test:
    .venv/bin/pytest -q

ingest *args:
    docker compose up -d --wait
    .venv/bin/python -m domestique.ingest.icu {{args}}

db-up:
    docker compose up -d --wait

# replay eval on the fixture season, loop on; the headline is the last line
eval *args:
    .venv/bin/python evals/replay.py {{args}}

# activity comments and #fuel intake only (just ingest already includes them)
comments *args:
    docker compose up -d --wait
    .venv/bin/python -m domestique.ingest.icu_comments {{args}}

# load a seed file into the claims store; claims stay candidates unless --activate
seed *args:
    docker compose up -d --wait
    .venv/bin/python -m domestique.claims.seed {{args}}

# evaluate every safety rail for one day: just rails --date YYYY-MM-DD
rails *args:
    .venv/bin/python -m domestique.rails {{args}}

# plan vs execution for one day: just pve --date YYYY-MM-DD [--save]
pve *args:
    .venv/bin/python -m domestique.analysis {{args}}

# web console (claims report) in a container beside the database, on localhost only
web:
    docker compose up -d --wait app
    @echo "web console: http://127.0.0.1:${DOMESTIQUE_WEB_PORT:-8000}/claims"
