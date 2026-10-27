"""Build a .fig from scratch for Figma: document → pages → frames, rectangles and text.

The schema is the one Figma ships inside its own files (``schema.bin``, taken from a
Figma export); geometry is local to the parent, colors are hex strings. Derived data
(fill geometry, glyph layout) is left for Figma to compute on open.
"""

from __future__ import annotations

import hashlib
import struct
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .container import FigFile, _inflate, write_fig
from .kiwi import decode_schema

SCHEMA_FILE = Path(__file__).with_name("schema.bin")
SCHEMA_VERSION = 106
IDENTITY = {"m00": 1.0, "m01": 0.0, "m02": 0.0, "m10": 0.0, "m11": 1.0, "m12": 0.0}
_POSITION_DIGITS = [chr(c) for c in range(0x21, 0x7F)]  # fractional-index alphabet, '!'..'~'


def color(value: str, alpha: float = 1.0) -> dict[str, float]:
    h = value.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) == 8:
        alpha = int(h[6:8], 16) / 255
    return {"r": int(h[0:2], 16) / 255, "g": int(h[2:4], 16) / 255, "b": int(h[4:6], 16) / 255, "a": alpha}


def solid(value: str, opacity: float = 1.0) -> dict[str, Any]:
    return {"type": "SOLID", "color": color(value), "opacity": opacity, "visible": True, "blendMode": "NORMAL"}


def drop_shadow(value: str, x: float, y: float, blur: float, spread: float = 0.0) -> dict[str, Any]:
    return {
        "type": "DROP_SHADOW", "color": color(value), "offset": {"x": x, "y": y}, "radius": blur,
        "spread": spread, "visible": True, "blendMode": "NORMAL", "showShadowBehindNode": False,
    }


def _position(i: int) -> str:
    """Sortable index for the i-th child: '!', '"', … then two characters."""
    base = len(_POSITION_DIGITS)
    if i < base - 1:
        return _POSITION_DIGITS[i]
    i -= base - 1
    return _POSITION_DIGITS[-1] + _POSITION_DIGITS[i // base] + _POSITION_DIGITS[i % base]


def _png(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    raw = b"".join(b"\0" + bytes(rgb) * width for _ in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


class FigBuilder:
    def __init__(self, file_name: str = "Untitled") -> None:
        self.file_name = file_name
        self.schema = decode_schema(_inflate(SCHEMA_FILE.read_bytes()))
        self.nodes: list[dict[str, Any]] = []
        self.images: dict[str, bytes] = {}  # sha1 hex -> PNG/JPEG bytes (zip "images/")
        self._children: dict[tuple[int, int], int] = {}
        self._next_local = 2
        self.document = self._node(None, "DOCUMENT", "Document", guid={"sessionID": 0, "localID": 0},
                                   strokeWeight=0.0, strokeAlign="CENTER", strokeJoin="BEVEL")
        self._internal = self._node(self.document, "CANVAS", "Internal Only Canvas", guid={"sessionID": 0, "localID": 1},
                                    internalOnly=True, backgroundOpacity=1.0, backgroundEnabled=False,
                                    backgroundColor=color("#ffffff"))

    # ── low level ──
    def _guid(self) -> dict[str, int]:
        g = {"sessionID": 1, "localID": self._next_local}
        self._next_local += 1
        return g

    def _node(self, parent: dict | None, type_: str, name: str, *, guid: dict | None = None, **fields: Any) -> dict:
        node: dict[str, Any] = {"guid": guid or self._guid(), "phase": "CREATED"}
        if parent is not None:
            key = (parent["sessionID"], parent["localID"])
            i = self._children.get(key, 0)
            self._children[key] = i + 1
            node["parentIndex"] = {"guid": parent, "position": _position(i)}
        node.update(type=type_, name=name, visible=True, opacity=1.0)
        node.update({k: v for k, v in fields.items() if v is not None})
        node.setdefault("transform", dict(IDENTITY))
        self.nodes.append(node)
        return node["guid"]

    def add(self, parent: dict, type_: str, name: str, **fields: Any) -> dict:
        """Any NodeChange fields, for what the helpers below do not cover."""
        return self._node(parent, type_, name, **fields)

    # ── helpers ──
    def page(self, name: str, background: str = "#f5f5f5") -> dict:
        return self._node(self.document, "CANVAS", name, backgroundOpacity=1.0, backgroundEnabled=True,
                          backgroundColor=color(background), strokeWeight=0.0, strokeAlign="CENTER", strokeJoin="BEVEL")

    def _box(self, x: float, y: float, w: float, h: float, *, fills=None, stroke=None, stroke_weight=1.0,
             radius: float | None = None, effects=None, opacity: float = 1.0) -> dict[str, Any]:
        t = dict(IDENTITY, m02=float(x), m12=float(y))
        out: dict[str, Any] = {
            "size": {"x": float(w), "y": float(h)}, "transform": t, "opacity": opacity,
            "fillPaints": fills if fills is not None else [],
            "strokeWeight": float(stroke_weight), "strokeAlign": "INSIDE", "strokeJoin": "MITER",
        }
        if stroke:
            out["strokePaints"] = [solid(stroke)]
        if radius:
            out["cornerRadius"] = float(radius)
        if effects:
            out["effects"] = effects
        return out

    def frame(self, parent: dict, name: str, x: float, y: float, w: float, h: float, *, fill: str | None = None,
              stroke: str | None = None, radius: float | None = None, effects=None, clip: bool = True,
              layout: dict[str, Any] | None = None, **extra: Any) -> dict:
        """``layout``: {"mode": "VERTICAL"|"HORIZONTAL", "gap", "padding": (t, r, b, l),
        "align": MIN|CENTER|MAX|SPACE_BETWEEN, "cross": MIN|CENTER|MAX, "hug": bool}."""
        fields = self._box(x, y, w, h, fills=[solid(fill)] if fill else [], stroke=stroke, radius=radius, effects=effects)
        fields["frameMaskDisabled"] = not clip
        if layout:
            t, r, b, l = layout.get("padding", (0, 0, 0, 0))
            hug = layout.get("hug", False)
            fields.update(
                stackMode=layout["mode"], stackSpacing=float(layout.get("gap", 0)),
                stackVerticalPadding=float(t), stackPaddingRight=float(r),
                stackPaddingBottom=float(b), stackHorizontalPadding=float(l),
                stackPrimaryAlignItems=layout.get("align", "MIN"), stackCounterAlignItems=layout.get("cross", "MIN"),
                stackPrimarySizing="RESIZE_TO_FIT" if hug else "FIXED", stackCounterSizing="FIXED",
            )
        fields.update(extra)
        return self._node(parent, "FRAME", name, **fields)

    def rect(self, parent: dict, name: str, x: float, y: float, w: float, h: float, *, fill: str | None = None,
             stroke: str | None = None, radius: float | None = None, effects=None, **extra: Any) -> dict:
        fields = self._box(x, y, w, h, fills=[solid(fill)] if fill else [], stroke=stroke, radius=radius, effects=effects)
        fields.update(extra)
        return self._node(parent, "ROUNDED_RECTANGLE", name, **fields)

    def image_paint(self, data: bytes, width: int, height: int, scale_mode: str = "FILL") -> dict[str, Any]:
        """An IMAGE paint; the bytes go to the zip under their SHA-1 like Figma's own exports."""
        digest = hashlib.sha1(data).hexdigest()
        self.images[digest] = data
        ref = {"hash": bytes.fromhex(digest), "name": digest[:12]}
        return {
            "type": "IMAGE", "opacity": 1.0, "visible": True, "blendMode": "NORMAL", "transform": dict(IDENTITY),
            "image": ref, "imageThumbnail": dict(ref), "animationFrame": 0, "imageScaleMode": scale_mode,
            "imageShouldColorManage": False, "rotation": 0.0, "scale": 1.0,
            "originalImageWidth": int(width), "originalImageHeight": int(height),
        }

    def text(self, parent: dict, characters: str, x: float, y: float, w: float, h: float, *, size: float = 14,
             family: str = "Inter", style: str = "Regular", fill: str = "#111111", line_height: float | None = None,
             align: str = "LEFT", auto_resize: str = "HEIGHT", name: str | None = None, **extra: Any) -> dict:
        lines = [{"lineType": "PLAIN", "styleId": 0, "indentationLevel": 0, "sourceDirectionality": "AUTO",
                  "listStartOffset": 0, "isFirstLineOfList": False} for _ in characters.split("\n")]
        fields = self._box(x, y, w, h, fills=[solid(fill)])
        fields.update(
            fontSize=float(size), fontName={"family": family, "style": style, "postscript": ""},
            textData={"characters": characters, "lines": lines},
            textAlignHorizontal=align, textAlignVertical="TOP", textAutoResize=auto_resize,
            lineHeight={"value": float(line_height), "units": "PIXELS"} if line_height else {"value": 100.0, "units": "PERCENT"},
            letterSpacing={"value": 0.0, "units": "PERCENT"}, autoRename=False,
        )
        fields.update(extra)
        return self._node(parent, "TEXT", name or characters[:40], **fields)

    # ── output ──
    def to_fig(self) -> FigFile:
        message = {"type": "NODE_CHANGES", "sessionID": 0, "ackID": 0, "nodeChanges": self.nodes, "blobs": []}
        meta = {
            "client_meta": {
                "background_color": color("#f5f5f5"),
                "thumbnail_size": {"width": 400, "height": 300},
                "render_coordinates": {"x": 0, "y": 0, "width": 1440, "height": 1080},
            },
            "file_name": self.file_name,
            "developer_related_links": [],
            "exported_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + "000Z",
        }
        return FigFile(SCHEMA_VERSION, self.schema, message, meta, _png(400, 300, (245, 245, 245)), dict(self.images))

    def to_bytes(self) -> bytes:
        return write_fig(self.to_fig())
