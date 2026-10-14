import logging
from logging.handlers import RotatingFileHandler
from typing import Any

from .config import PROJECT_DIR

LOGS_DIR = PROJECT_DIR / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

ERROR_LOG_FILE = LOGS_DIR / "agent_errors.log"
WORKFLOW_LOG_FILE = LOGS_DIR / "agent_workflow.log"

# Set up dedicated rotating file handler for all agent errors
error_file_handler = RotatingFileHandler(
    ERROR_LOG_FILE,
    maxBytes=5 * 1024 * 1024,  # 5MB per file
    backupCount=3,
    encoding="utf-8",
)
error_file_handler.setLevel(logging.WARNING)
error_file_formatter = logging.Formatter(
    "%(asctime)s [%(levelname)s] [%(name)s] %(message)s (%(filename)s:%(lineno)d)"
)
error_file_handler.setFormatter(error_file_formatter)

# Set up workflow file handler
workflow_file_handler = RotatingFileHandler(
    WORKFLOW_LOG_FILE,
    maxBytes=5 * 1024 * 1024,
    backupCount=3,
    encoding="utf-8",
)
workflow_file_handler.setLevel(logging.INFO)
workflow_file_formatter = logging.Formatter(
    "%(asctime)s [%(levelname)s] [%(name)s] %(message)s"
)
workflow_file_handler.setFormatter(workflow_file_formatter)


def setup_agent_logging() -> None:
    """Attach file handlers to the root 'designer_agent' logger."""
    root_logger = logging.getLogger("designer_agent")
    if error_file_handler not in root_logger.handlers:
        root_logger.addHandler(error_file_handler)
    if workflow_file_handler not in root_logger.handlers:
        root_logger.addHandler(workflow_file_handler)


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


# Automatically configure logging on module import
setup_agent_logging()

