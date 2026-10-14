"""BA agent logger facade.

Agent code calls ``logging.info(...)``, ``logging.agent(...)`` and friends
(``from utils import logging``). Everything is forwarded to the standard
``logging`` module under the ``ba.agent`` logger, so it reaches the platform
handlers (console, ``logs/ba-api/``, per-project logs in storage) with the
request's user / project / request id attached.
"""

import logging as std_logging

# Silence noisy OpenTelemetry context detach warnings (caused by GeneratorExit inside async generators)
std_logging.getLogger("opentelemetry.context").setLevel(std_logging.CRITICAL)

_logger = std_logging.getLogger("ba.agent")


class logging:
    """Facade kept for the existing call sites; levels map to std logging."""

    def log(self, level: str, message: str) -> None:
        levelno = std_logging.getLevelName(level.upper())
        _logger.log(levelno if isinstance(levelno, int) else std_logging.INFO, message)

    def agent(self, content: str, end: str = "\n") -> None:
        _logger.info("AGENT: %s", content, extra={"kind": "agent"})

    def user(self, content: str, end: str = "\n") -> None:
        _logger.info("USER: %s", content, extra={"kind": "user"})

    def tool(self, content: str, end: str = "\n") -> None:
        _logger.info("TOOL: %s", content, extra={"kind": "tool"})

    def debug(self, message: str) -> None:
        _logger.debug(message)

    def info(self, message: str) -> None:
        _logger.info(message)

    def warning(self, message: str) -> None:
        _logger.warning(message)

    def error(self, message: str) -> None:
        _logger.error(message)
