"""Scene graph over a decoded .fig message: nodes by guid, ordered children, geometry blobs."""

from __future__ import annotations

import re
import struct
import unicodedata
from collections import defaultdict
from typing import Any, Iterator

Node = dict[str, Any]
Key = tuple[int, int]

# Figma path blobs: command byte, then little-endian float32 coordinates.
_PATH_ARGS = {0: 0, 1: 2, 2: 2, 3: 4, 4: 6}
_PATH_CMD = {0: "Z", 1: "M", 2: "L", 3: "Q", 4: "C"}


def key(guid: dict[str, int] | None) -> Key | None:
    return (guid["sessionID"], guid["localID"]) if guid else None


def slug(value: str, fallback: str = "x") -> str:
    text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")[:60] or fallback


def hex_color(color: dict[str, float], opacity: float = 1.0) -> str:
    r, g, b = (round(color[c] * 255) for c in "rgb")
    a = round(color.get("a", 1.0) * opacity * 255)
    return f"#{r:02x}{g:02x}{b:02x}" + ("" if a >= 255 else f"{a:02x}")


class Scene:
    def __init__(self, message: dict[str, Any]) -> None:
        self.blobs: list[bytes] = [b.get("bytes", b"") for b in message.get("blobs", [])]
        self.nodes: dict[Key, Node] = {}
        children: dict[Key, list[tuple[str, Node]]] = defaultdict(list)
        for node in message.get("nodeChanges", []):
            if node.get("phase") == "REMOVED":
                continue
            self.nodes[key(node["guid"])] = node
            parent = node.get("parentIndex")
            if parent:
                children[key(parent["guid"])].append((parent.get("position", ""), node))
        self._children = {k: [n for _, n in sorted(v, key=lambda item: item[0])] for k, v in children.items()}

    def children(self, node: Node) -> list[Node]:
        return self._children.get(key(node["guid"]), [])

    def parent(self, node: Node) -> Node | None:
        parent = node.get("parentIndex")
        return self.nodes.get(key(parent["guid"])) if parent else None

    def page(self, node: Node) -> Node | None:
        current: Node | None = node
        while current is not None and current.get("type") != "CANVAS":
            current = self.parent(current)
        return current

    def walk(self, node: Node) -> Iterator[Node]:
        yield node
        for child in self.children(node):
            yield from self.walk(child)

    def of_type(self, *types: str) -> Iterator[Node]:
        return (n for n in self.nodes.values() if n.get("type") in types)

    def path_data(self, blob_index: int) -> str:
        data = self.blobs[blob_index] if 0 <= blob_index < len(self.blobs) else b""
        out, i = [], 0
        while i < len(data):
            cmd = data[i]
            i += 1
            count = _PATH_ARGS.get(cmd)
            if count is None or i + 4 * count > len(data):
                break
            values = struct.unpack_from(f"<{count}f", data, i)
            i += 4 * count
            out.append(_PATH_CMD[cmd] + " ".join(f"{v:.2f}".rstrip("0").rstrip(".") for v in values))
        return "".join(out)
