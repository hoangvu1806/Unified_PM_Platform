"""The .fig container: a zip with ``canvas.fig``, ``meta.json``, ``thumbnail.png`` and ``images/<sha1>``.

``canvas.fig`` = ``b"fig-kiwi"`` + uint32 version + length-prefixed chunks:
chunk 0 is the Kiwi schema (raw deflate), chunk 1 the ``Message`` (zstd in files
Figma writes today, raw deflate in older ones).
"""

from __future__ import annotations

import io
import json
import struct
import zipfile
import zlib
from dataclasses import dataclass, field

import zstandard

from .kiwi import Codec, KiwiError, Schema, decode_schema, encode_schema

MAGIC = b"fig-kiwi"
ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"


@dataclass
class FigFile:
    version: int
    schema: Schema
    message: dict
    meta: dict = field(default_factory=dict)
    thumbnail: bytes | None = None
    images: dict[str, bytes] = field(default_factory=dict)  # sha1 hex -> bytes

    @property
    def codec(self) -> Codec:
        return Codec(self.schema)


def _inflate(data: bytes) -> bytes:
    if data[:4] == ZSTD_MAGIC:
        return zstandard.ZstdDecompressor().stream_reader(io.BytesIO(data)).read()
    return zlib.decompress(data, -15)


def _deflate(data: bytes) -> bytes:
    c = zlib.compressobj(9, zlib.DEFLATED, -15)
    return c.compress(data) + c.flush()


def split_canvas(canvas: bytes) -> tuple[int, list[bytes]]:
    if canvas[:8] != MAGIC:
        raise KiwiError("not a fig-kiwi canvas")
    version = struct.unpack("<I", canvas[8:12])[0]
    chunks, off = [], 12
    while off < len(canvas):
        n = struct.unpack("<I", canvas[off : off + 4])[0]
        chunks.append(canvas[off + 4 : off + 4 + n])
        off += 4 + n
    return version, chunks


def read_canvas(canvas: bytes) -> tuple[int, Schema, dict]:
    version, chunks = split_canvas(canvas)
    schema = decode_schema(_inflate(chunks[0]))
    message = Codec(schema).decode("Message", _inflate(chunks[1]))
    return version, schema, message


def write_canvas(version: int, schema: Schema, message: dict) -> bytes:
    schema_chunk = _deflate(encode_schema(schema))
    data_chunk = zstandard.ZstdCompressor(level=6).compress(Codec(schema).encode("Message", message))
    out = bytearray(MAGIC + struct.pack("<I", version))
    for chunk in (schema_chunk, data_chunk):
        out += struct.pack("<I", len(chunk)) + chunk
    return bytes(out)


def read_fig(data: bytes) -> FigFile:
    if data[:8] == MAGIC:  # bare canvas, no zip
        version, schema, message = read_canvas(data)
        return FigFile(version, schema, message)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = set(z.namelist())
        version, schema, message = read_canvas(z.read("canvas.fig"))
        meta = json.loads(z.read("meta.json")) if "meta.json" in names else {}
        thumb = z.read("thumbnail.png") if "thumbnail.png" in names else None
        images = {n.split("/", 1)[1]: z.read(n) for n in names if n.startswith("images/") and not n.endswith("/")}
    return FigFile(version, schema, message, meta, thumb, images)


def write_fig(fig: FigFile) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("canvas.fig", write_canvas(fig.version, fig.schema, fig.message), zipfile.ZIP_STORED)
        if fig.thumbnail:
            z.writestr("thumbnail.png", fig.thumbnail, zipfile.ZIP_STORED)
        z.writestr("meta.json", json.dumps(fig.meta), zipfile.ZIP_DEFLATED)
        for sha, blob in fig.images.items():
            z.writestr(f"images/{sha}", blob, zipfile.ZIP_STORED)
    return buf.getvalue()
