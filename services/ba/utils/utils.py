"""Shared auxiliary utility functions for formatting, date/time, and JSON parsing."""

from pydantic import BaseModel
from datetime import datetime
from .log import logging

import json
import re

logger = logging()


def format_string(template: str, log_vars: bool = False, **kwargs) -> str:
    """Format a string template using double curly braces syntax {{variable}}.

    This function matches placeholder variables in the format {{variable}} and replaces
    them with corresponding values from the kwargs.

    ## Args:
        template: The string template containing placeholders to be replaced.
        log_vars: If True, logs the list of keys that were successfully formatted.
        **kwargs: Dynamic variables to substitute into the template.

    ## Returns:
        The formatted string with all matched placeholders replaced.
    """

    replaced_vars = {}

    def replace_placeholder(match):
        key = match.group(1).strip()
        val = kwargs.get(key, match.group(0))
        replaced_vars[key] = val
        return str(val)

    pattern = r"\{\{(.*?)\}\}"
    formatted_string = re.sub(pattern, replace_placeholder, template)

    if replaced_vars and log_vars:
        logger.info(
            f"✅ Formatted string template with vars: {list(replaced_vars.keys())}"
        )

    return formatted_string


def now() -> str:
    """Get the current local time formatted as a string.

    ## Returns:
        The current date and time string in 'YYYY-MM-DD HH:MM:SS' format.
    """
    # Convert current time to string
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def fetch_vietnamese_date() -> str:
    """Get the current date in standard Vietnamese format (e.g., 'Thứ Hai, ngày 12 tháng 5 năm 2026').

    ## Returns:
        A Vietnamese representation of the current weekday, day, month, and year.
    """
    weekdays = [
        "Thứ Hai",
        "Thứ Ba",
        "Thứ Tư",
        "Thứ Năm",
        "Thứ Sáu",
        "Thứ Bảy",
        "Chủ Nhật",
    ]

    dt = datetime.now()

    day = weekdays[dt.weekday()]
    return f"{day}, ngày {dt.day} tháng {dt.month} năm {dt.year}"


def parse_str_to_dict(text: str) -> dict:
    """Parse a potential JSON string into a Python dictionary.

    It attempts multiple extraction strategies in sequence:
    1. Direct JSON parsing of the clean string.
    2. Extracting and parsing from a markdown ```json ``` code block.
    3. Finding and parsing the first matching JSON object ({...}) structure.

    ## Args:
        text: The raw string potentially containing JSON data.

    ## Returns:
        The parsed dictionary, or an empty dictionary if parsing fails.
    """
    cleaned = (text or "").strip()
    if not cleaned:
        return {}

    # 1. Try direct parse
    try:
        loaded = json.loads(cleaned)
        return loaded if isinstance(loaded, dict) else {}
    except json.JSONDecodeError:
        pass

    # 2. Try extracting from markdown code block
    md_match = re.search(r"```json\s*(.*?)\s*```", cleaned, re.DOTALL)
    if md_match:
        try:
            loaded = json.loads(md_match.group(1).strip())
            return loaded if isinstance(loaded, dict) else {}
        except json.JSONDecodeError:
            pass

    # 3. Try finding JSON object in plain text
    obj_match = re.search(r"\{[\s\S]*\}", cleaned)
    if obj_match:
        try:
            loaded = json.loads(obj_match.group(0))
            return loaded if isinstance(loaded, dict) else {}
        except json.JSONDecodeError:
            pass

    return {}


def get_schema_class(
    schema_name: str | None = None,
    schema_module: str = "",
) -> type[BaseModel] | None:
    """Dynamically resolve Pydantic BaseModel class by name from schema module.

    Uses importlib + getattr — no manual dict needed since DMN returns
    the exact class name (e.g. "EditAction" → EditAction class).

    Args:
        schema_name: Schema identifier returned by DMN intent detector
                     (e.g. "EditAction", "ResolveAction").
        schema_module: Module path to look up schemas.

    Returns:
        The matching Pydantic model class, or None if not found.
    """
    import importlib
    from pydantic import BaseModel

    if not schema_name:
        return None

    try:
        module = importlib.import_module(schema_module)
    except ImportError:
        return None

    schema_cls = getattr(module, schema_name, None)

    if schema_cls is None or not (
        isinstance(schema_cls, type) and issubclass(schema_cls, BaseModel)
    ):
        return None

    return schema_cls


if __name__ == "__main__":
    template = "Hello, {{ name_aaa }}! Today is {{ day }}."
    formatted = format_string(template, name_aaa="Alice", day="Monday")
    print(formatted)  # Output: Hello, Alice! Today is Monday.
