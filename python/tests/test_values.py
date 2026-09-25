from __future__ import annotations

import argparse
import dataclasses
import math
from pathlib import Path

from lossline.values import NOT_A_NUMBER, config_to_dict, flatten, to_json, to_number


class Scalar:
    """Duck-types a numpy scalar / 0-d torch tensor."""

    def __init__(self, value):
        self.value = value

    def item(self):
        return self.value


class Vector:
    def item(self):
        raise ValueError("only one element tensors can be converted to Python scalars")


def test_to_number_basic_types():
    assert to_number(3) == 3 and isinstance(to_number(3), int)
    assert to_number(2.5) == 2.5
    assert to_number(True) == 1 and to_number(False) == 0
    assert to_number(float("nan")) is None
    assert to_number(float("inf")) is None
    assert to_number(-math.inf) is None


def test_to_number_duck_typed_scalars():
    assert to_number(Scalar(1.5)) == 1.5
    assert to_number(Scalar(True)) == 1
    assert to_number(Scalar(float("nan"))) is None
    assert to_number(Vector()) is NOT_A_NUMBER


def test_to_number_rejects_non_numbers():
    for value in ("1.0", None, [1], {"a": 1}, b"1", object()):
        assert to_number(value) is NOT_A_NUMBER


def test_flatten():
    assert flatten({"train": {"loss": 1, "acc": {"top1": 0.5}}, "lr": 3}) == {
        "train/loss": 1, "train/acc/top1": 0.5, "lr": 3,
    }


@dataclasses.dataclass
class Inner:
    depth: int = 4


@dataclasses.dataclass
class Cfg:
    lr: float = 3e-4
    path: Path = Path("/data")
    inner: Inner = dataclasses.field(default_factory=Inner)
    tags: tuple = ("a", "b")


def test_config_sources():
    ns = argparse.Namespace(lr=1e-3, layers=[1, 2], bad=float("nan"))
    assert config_to_dict(ns) == {"lr": 1e-3, "layers": [1, 2], "bad": None}
    assert config_to_dict(Cfg()) == {
        "lr": 3e-4, "path": "/data", "inner": {"depth": 4}, "tags": ["a", "b"],
    }

    class Plain:
        def __init__(self):
            self.width = 512
            self._private = 1

    assert config_to_dict(Plain()) == {"width": 512}
    assert config_to_dict(None) == {}
    assert config_to_dict({"a": {"b": Scalar(2)}, 3: True}) == {"a": {"b": 2}, "3": True}


def test_to_json_fallback_is_string():
    assert to_json(object).startswith("<class")
    assert to_json({1, 2}) == [1, 2]


def test_bucket_resolution(monkeypatch):
    from lossline import defaults

    monkeypatch.setattr(defaults, "default_bucket", lambda: "someone/lossline")
    monkeypatch.delenv("LOSSLINE_BUCKET", raising=False)
    assert defaults.resolve_bucket(None) == "someone/lossline"
    assert defaults.resolve_bucket("me/logs") == "me/logs"
    assert defaults.resolve_bucket(False) is None
    monkeypatch.setenv("LOSSLINE_BUCKET", "env/bucket")
    assert defaults.resolve_bucket(None) == "env/bucket"
    monkeypatch.setenv("LOSSLINE_BUCKET", "none")
    assert defaults.resolve_bucket(None) is None
