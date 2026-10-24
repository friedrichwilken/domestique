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

# evaluate every safety rail for one day: just rails --date YYYY-MM-DD
rails *args:
    .venv/bin/python -m domestique.rails {{args}}

# plan vs execution for one day: just pve --date YYYY-MM-DD [--save]
pve *args:
    .venv/bin/python -m domestique.analysis {{args}}
