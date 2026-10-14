"""Designer agent logging helpers.

Files and per-project logs are written by the platform handlers
(platform_core.logs.setup_logging); this module only keeps the helper API.
"""

import logging
from typing import Any


def setup_agent_logging() -> None:
    """Kept for compatibility: platform logging is configured in app.main."""


def log_agent_error(
    category: str,
    message: str,
    error: Exception | None = None,
    context: dict[str, Any] | None = None,
) -> None:
    """Log an error or fallback event to the persistent error log file."""
    logger = logging.getLogger(f"designer_agent.{category}")
    err_detail = f" | Error: {error}" if error else ""
    ctx_detail = f" | Context: {context}" if context else ""
    logger.warning(f"[{category.upper()}] {message}{err_detail}{ctx_detail}", exc_info=bool(error))



