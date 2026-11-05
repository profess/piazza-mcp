from pathlib import Path

import pytest

import piazza_mcp.config.env as config_env


@pytest.fixture(autouse=True)
def isolate_from_checkout_credentials(monkeypatch, tmp_path: Path):
    """Keep any test from loading real credentials and reaching Piazza."""
    monkeypatch.setattr(config_env, "PROJECT_ENV_PATH", tmp_path / "absent.env")
    for name in ("PIAZZA_EMAIL", "PIAZZA_PASSWORD", "PIAZZA_COURSES"):
        monkeypatch.delenv(name, raising=False)
