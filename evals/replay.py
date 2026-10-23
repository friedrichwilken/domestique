"""Replay eval: walk a season day by day with the future hidden, predict, score, report.

Run: python evals/replay.py [--source fixture|db] [--loop on|off] [--out DIR]
(``just eval`` runs the fixture season with the loop on). The logic lives in
``domestique.replay``; see ``domestique/replay/run.py`` for the options.
"""

from __future__ import annotations

from pathlib import Path

from domestique.replay.run import main

if __name__ == "__main__":
    main(repo=Path(__file__).resolve().parents[1])
