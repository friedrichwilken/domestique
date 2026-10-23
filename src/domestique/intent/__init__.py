"""Intent layer: goals, constraints, overrides and rails decided by humans.

Loaded read-only from ``$DOMESTIQUE_HOME/intent/*.yaml``; the system only ever
appends to ``overrides.yaml``.
"""

from domestique.intent.loader import (
    FILES,
    Intent,
    IntentError,
    append_override,
    load_intent,
    load_intent_from_config,
)
from domestique.intent.schemas import Constraint, Goal, Override, Rail, RailAction

__all__ = [
    "FILES",
    "Constraint",
    "Goal",
    "Intent",
    "IntentError",
    "Override",
    "Rail",
    "RailAction",
    "append_override",
    "load_intent",
    "load_intent_from_config",
]
