from typing import Any


def small_instances(node: Any) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    if not isinstance(node, dict):
        return values
    if node.get("type") == "INSTANCE":
        width = node.get("width", node.get("w", 0))
        height = node.get("height", node.get("h", 0))
        if isinstance(width, int | float) and isinstance(height, int | float) and (width < 44 or height < 44):
            values.append({"id": node.get("id"), "width": width, "height": height})
    for child in node.get("children", []):
        values.extend(small_instances(child))
    return values
