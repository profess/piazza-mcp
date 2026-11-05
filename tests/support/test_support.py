import os
from pathlib import Path
import sys

import fastmcp  # noqa: F401 - loads the settings module inspected below
import pytest

import piazza_mcp.config.env as config_env
from tests.support import assert_sensitive_value_absent


def test_test_suite_cannot_reach_the_checkout_env_file():
    checkout = Path(__file__).resolve().parents[2]

    assert not config_env.PROJECT_ENV_PATH.is_relative_to(checkout)


def test_fastmcp_in_the_test_process_cannot_load_a_dotenv_file():
    assert sys.modules["fastmcp.settings"].ENV_FILE == os.devnull


def test_sensitive_value_check_inspects_string_and_repr():
    sentinel = "UNIQUE_PRIVATE_SENTINEL"

    class LeakyString:
        def __str__(self):
            return sentinel

        def __repr__(self):
            return "redacted"

    with pytest.raises(AssertionError):
        assert_sensitive_value_absent(LeakyString(), sentinel)
