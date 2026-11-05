from collections.abc import Awaitable, Callable
import logging
from typing import Any

from fastmcp.exceptions import ToolError
import jsonschema

from piazza_mcp.config import PiazzaConfigError
from piazza_mcp.services.piazza import (
    PiazzaClientError,
    PiazzaValidationError,
)


logger = logging.getLogger(__name__)

_INVALID_OUTPUT_MESSAGE = "Piazza returned an unexpected response shape"
_UNEXPECTED_FAILURE_MESSAGE = "Piazza request failed"


async def run_tool(
    tool_name: str,
    output_schema: dict[str, Any],
    call: Callable[[], Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    """Run a tool call so clients and logs see only messages known to be safe.

    FastMCP sends output to clients without validating it and logs a full
    traceback for any exception other than ``ToolError``. Unexpected exceptions
    can carry Piazza content, so only their type is logged here.
    """
    try:
        result = await call()
        jsonschema.validate(result, output_schema)
    except (
        PiazzaClientError,
        PiazzaConfigError,
        PiazzaValidationError,
    ) as error:
        raise ToolError(str(error)) from None
    except jsonschema.ValidationError:
        logger.error("Tool %s produced invalid output", tool_name)
        raise ToolError(_INVALID_OUTPUT_MESSAGE) from None
    except Exception as error:
        logger.error("Tool %s failed: %s", tool_name, type(error).__name__)
        raise ToolError(_UNEXPECTED_FAILURE_MESSAGE) from None
    return result
