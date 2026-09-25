"""Where runs go when nothing says otherwise: one private bucket per user, ``<user>/lossline``."""

from __future__ import annotations

import os
from functools import lru_cache

DEFAULT_BUCKET_NAME = "lossline"
OFF = {"none", "off", "local", "false", "0"}


@lru_cache(maxsize=1)
def default_bucket() -> str | None:
    """``<hf user>/lossline`` when logged in to Hugging Face (``HF_TOKEN`` or ``hf auth login``),
    otherwise None. Costs one API call, once per process."""
    try:
        from huggingface_hub import HfApi, get_token

        token = get_token()
        if not token:
            return None
        user = HfApi().whoami(token=token)["name"]
    except Exception:
        return None
    return f"{user}/{DEFAULT_BUCKET_NAME}"


def resolve_bucket(bucket: str | bool | None) -> str | None:
    """The bucket a run writes to: the argument, then ``LOSSLINE_BUCKET``, then the
    user's default bucket. ``False`` or ``"none"`` means local files only."""
    if bucket is False:
        return None
    value = bucket if isinstance(bucket, str) and bucket else os.environ.get("LOSSLINE_BUCKET")
    if value:
        return None if value.strip().lower() in OFF else value.strip()
    return default_bucket()
