from __future__ import annotations

import pytest

import lossline.logger


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """Keep tests local and independent of the caller's lossline settings."""
    for var in ("LOSSLINE_DIR", "LOSSLINE_PROJECT", "LOSSLINE_FLUSH_INTERVAL"):
        monkeypatch.delenv(var, raising=False)
    # without this, a logged-in machine would default to the real <user>/lossline bucket
    monkeypatch.setenv("LOSSLINE_BUCKET", "none")
    monkeypatch.chdir(tmp_path)
    yield
    if lossline.logger.current() is not None:
        lossline.logger.current().finish()
