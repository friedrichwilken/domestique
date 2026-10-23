"""Load and validate the intent files; append overrides.

Invalid intent refuses to load: the error names the file, the entry and the
field. Files that do not exist load as empty lists. Only ``overrides.yaml``
is ever written, and only by appending text, so existing entries and
comments stay byte-for-byte as the human left them.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError

from domestique import config
from domestique.intent.schemas import Constraint, Goal, Override, Rail

FILES: dict[str, type[BaseModel]] = {
    "goals.yaml": Goal,
    "constraints.yaml": Constraint,
    "overrides.yaml": Override,
    "rails.yaml": Rail,
}


class IntentError(ValueError):
    """Intent that fails validation. The system refuses to run on it."""


@dataclass(frozen=True)
class Intent:
    goals: tuple[Goal, ...]
    constraints: tuple[Constraint, ...]
    overrides: tuple[Override, ...]
    rails: tuple[Rail, ...]


def _field_path(loc: tuple[int | str, ...]) -> str:
    return ".".join(str(part) for part in loc) or "<entry>"


def _read_entries(path: Path) -> list[Any]:
    """The YAML list in ``path``; raw YAML is the external boundary, hence ``Any``."""
    if not path.exists():
        return []
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise IntentError(f"{path.name}: not valid YAML: {exc}") from exc
    if data is None:
        return []
    if not isinstance(data, list):
        raise IntentError(f"{path.name}: expected a list of entries")
    return data


def _validate[M: BaseModel](path: Path, model: type[M]) -> tuple[M, ...]:
    out: list[M] = []
    for i, entry in enumerate(_read_entries(path)):
        label = entry.get("id", f"#{i}") if isinstance(entry, dict) else f"#{i}"
        try:
            out.append(model.model_validate(entry))
        except ValidationError as exc:
            first = exc.errors()[0]
            raise IntentError(
                f"{path.name}: entry {label}: field '{_field_path(first['loc'])}': {first['msg']}"
            ) from exc
    return tuple(out)


def load_intent(intent_dir: Path) -> Intent:
    """Load all four intent files from ``intent_dir``; raises IntentError if any is invalid."""
    return Intent(
        goals=_validate(intent_dir / "goals.yaml", Goal),
        constraints=_validate(intent_dir / "constraints.yaml", Constraint),
        overrides=_validate(intent_dir / "overrides.yaml", Override),
        rails=_validate(intent_dir / "rails.yaml", Rail),
    )


def load_intent_from_config(env: Mapping[str, str] | None = None) -> Intent:
    """Load intent from the directory configured in ``$DOMESTIQUE_HOME/config.yaml``."""
    return load_intent(config.load(env).intent_dir)


def append_override(intent_dir: Path, override: Override) -> None:
    """Append one override entry to ``overrides.yaml``; existing text is left untouched."""
    path = intent_dir / "overrides.yaml"
    _validate(path, Override)  # never append to a file that is already invalid
    existing = path.read_text() if path.exists() else ""
    if existing and not existing.endswith("\n"):
        existing += "\n"
    entry = yaml.safe_dump(
        [override.model_dump(exclude_defaults=False)], sort_keys=False, allow_unicode=True
    )
    path.write_text(existing + entry)
