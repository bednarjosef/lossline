"""Run names, run ids and path-safe slugs."""

from __future__ import annotations

import random
import re
import secrets
import string

MAX_SLUG = 64
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")

_ADJECTIVES = (
    "amber", "ancient", "autumn", "bold", "brave", "bright", "brisk", "calm", "clever",
    "cosmic", "crimson", "crisp", "dapper", "daring", "dawn", "deep", "eager", "early",
    "fancy", "fast", "fearless", "fresh", "gentle", "gilded", "glad", "golden", "grand",
    "hidden", "humble", "icy", "jolly", "keen", "kind", "lively", "lucky", "lunar",
    "mellow", "misty", "noble", "nimble", "polar", "proud", "quiet", "rapid", "royal",
    "rustic", "silent", "silver", "sleek", "solar", "spry", "stellar", "still", "sunny",
    "swift", "tidy", "vivid", "wandering", "warm", "wild", "wise", "young", "zesty",
)
_NOUNS = (
    "aurora", "badger", "bay", "birch", "brook", "canyon", "cedar", "cloud", "comet",
    "coral", "crane", "dune", "eagle", "ember", "falcon", "fern", "field", "finch",
    "fjord", "forest", "fox", "galaxy", "glade", "grove", "harbor", "hawk", "heron",
    "hill", "island", "lake", "lark", "leaf", "lynx", "maple", "meadow", "mesa", "moon",
    "moss", "nebula", "oak", "ocean", "orbit", "otter", "owl", "peak", "pine", "planet",
    "pond", "quartz", "rain", "raven", "reef", "river", "sparrow", "star", "stone",
    "sun", "thunder", "tide", "valley", "wave", "willow", "wind", "wolf",
)
_SUFFIX_CHARS = string.ascii_lowercase + string.digits


def random_name() -> str:
    """A two-word adjective-noun slug like ``bold-heron``."""
    return f"{random.choice(_ADJECTIVES)}-{random.choice(_NOUNS)}"


def slugify(text: str, max_len: int = MAX_SLUG) -> str:
    """Lowercase ``text`` and map it onto ``[a-z0-9][a-z0-9._-]*``.

    Returns an empty string if nothing usable is left.
    """
    slug = re.sub(r"[^a-z0-9._-]+", "-", text.strip().lower())
    slug = re.sub(r"-{2,}", "-", slug)
    slug = slug.lstrip("._-")[:max_len].rstrip("-")
    return slug


def is_slug(text: str) -> bool:
    return len(text) <= MAX_SLUG and bool(SLUG_RE.match(text))


def make_run_id(name: str) -> str:
    """``name`` slugified plus ``-`` and 4 random ``[a-z0-9]`` characters."""
    suffix = "".join(secrets.choice(_SUFFIX_CHARS) for _ in range(4))
    base = slugify(name, MAX_SLUG - 5) or "run"
    return f"{base}-{suffix}"
