"""Turning user-supplied metrics and configs into plain JSON values."""

from __future__ import annotations

import dataclasses
import enum
import math
import numbers
import sys
from collections.abc import Mapping
from pathlib import PurePath
from typing import Any

# Returned by to_number() for values that are not numbers at all.
NOT_A_NUMBER = object()


def to_number(value: Any) -> int | float | None | object:
    """Coerce a metric value to int/float, ``None`` for non-finite, or NOT_A_NUMBER.

    Accepts Python numbers, bools (as 0/1), and anything with a scalar ``.item()``
    (numpy scalars, 0-d torch tensors) without importing those libraries.
    """
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, numbers.Integral):
        return int(value)
    if isinstance(value, numbers.Real):
        return to_number(float(value))
    item = getattr(value, "item", None)
    if callable(item) and not isinstance(value, (str, bytes)):
        try:
            scalar = item()
        except Exception:  # multi-element tensors/arrays raise here
            return NOT_A_NUMBER
        if scalar is not value and isinstance(scalar, (bool, int, float, numbers.Real)):
            return to_number(scalar)
    return NOT_A_NUMBER


def flatten(data: Mapping[str, Any], prefix: str = "", sep: str = "/") -> dict[str, Any]:
    """``{"train": {"loss": 1}}`` -> ``{"train/loss": 1}``."""
    out: dict[str, Any] = {}
    for key, value in data.items():
        name = f"{prefix}{sep}{key}" if prefix else str(key)
        if isinstance(value, Mapping):
            out.update(flatten(value, name, sep))
        else:
            out[name] = value
    return out


def config_to_dict(config: Any) -> dict[str, Any]:
    """Accept a dict, argparse.Namespace, dataclass or any object with ``__dict__``."""
    if config is None:
        return {}
    if isinstance(config, Mapping):
        raw: Any = dict(config)
    elif dataclasses.is_dataclass(config) and not isinstance(config, type):
        raw = dataclasses.asdict(config)
    elif hasattr(config, "__dict__"):
        raw = {k: v for k, v in vars(config).items() if not k.startswith("_")}
    else:
        raise TypeError(f"config must be a dict-like object, got {type(config).__name__}")
    sanitized = to_json(raw)
    assert isinstance(sanitized, dict)
    return sanitized


def to_json(value: Any, _depth: int = 0) -> Any:
    """Best-effort conversion of ``value`` into something ``json.dumps`` accepts."""
    if _depth > 20:
        return repr(value)
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, Mapping):
        return {str(k): to_json(v, _depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        items = sorted(value, key=repr) if isinstance(value, (set, frozenset)) else value
        return [to_json(v, _depth + 1) for v in items]
    if isinstance(value, enum.Enum):
        return to_json(value.value, _depth + 1)
    if isinstance(value, PurePath):
        return str(value)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return to_json(dataclasses.asdict(value), _depth + 1)
    number = to_number(value)
    if number is not NOT_A_NUMBER:
        return number
    tolist = getattr(value, "tolist", None)  # small numpy arrays / tensors
    if callable(tolist):
        try:
            return to_json(tolist(), _depth + 1)
        except Exception:
            pass
    return str(value)


class Warner:
    """Prints each distinct warning to stderr once."""

    def __init__(self) -> None:
        self._seen: set[str] = set()

    def once(self, key: str, message: str) -> None:
        if key not in self._seen:
            self._seen.add(key)
            print(f"lossline: {message}", file=sys.stderr)
