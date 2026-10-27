"""Kiwi binary codec (https://github.com/evanw/kiwi), the encoding inside Figma's .fig.

A .fig carries its own schema, so the codec is driven by a decoded ``Schema``:
``decode(schema, "Message", data)`` returns plain dicts/lists, ``encode`` is the inverse.
Enums decode to their names, byte arrays to ``bytes``, int64/uint64 to ``int``.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

KIND_ENUM, KIND_STRUCT, KIND_MESSAGE = 0, 1, 2
BUILTINS = {-1: "bool", -2: "byte", -3: "int", -4: "uint", -5: "float", -6: "string", -7: "int64", -8: "uint64"}
BUILTIN_IDS = {name: i for i, name in BUILTINS.items()}


@dataclass
class Field:
    name: str
    type: str
    is_array: bool
    value: int


@dataclass
class Definition:
    name: str
    kind: int
    fields: list[Field] = field(default_factory=list)
    by_value: dict[int, Field] = field(default_factory=dict)
    by_name: dict[str, Field] = field(default_factory=dict)


@dataclass
class Schema:
    definitions: list[Definition]
    by_name: dict[str, Definition]

    def __getitem__(self, name: str) -> Definition:
        return self.by_name[name]


class KiwiError(ValueError):
    pass


class Reader:
    __slots__ = ("data", "pos")

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0

    def byte(self) -> int:
        try:
            b = self.data[self.pos]
        except IndexError:
            raise KiwiError("unexpected end of data") from None
        self.pos += 1
        return b

    def bytes(self) -> bytes:
        n = self.var_uint()
        out = self.data[self.pos : self.pos + n]
        if len(out) != n:
            raise KiwiError("unexpected end of data")
        self.pos += n
        return out

    def var_uint(self) -> int:
        value = shift = 0
        while True:
            b = self.byte()
            value |= (b & 127) << shift
            shift += 7
            if not b & 128 or shift >= 35:
                return value & 0xFFFFFFFF

    def var_int(self) -> int:
        v = self.var_uint()
        return ~(v >> 1) if v & 1 else v >> 1

    def var_uint64(self) -> int:
        value = shift = 0
        while True:
            b = self.byte()
            if b & 128 and shift < 56:
                value |= (b & 127) << shift
                shift += 7
                continue
            return (value | (b << shift)) & 0xFFFFFFFFFFFFFFFF

    def var_int64(self) -> int:
        v = self.var_uint64()
        return ~(v >> 1) if v & 1 else v >> 1

    def var_float(self) -> float:
        first = self.byte()
        if first == 0:
            return 0.0
        if self.pos + 3 > len(self.data):
            raise KiwiError("unexpected end of data")
        bits = first | self.data[self.pos] << 8 | self.data[self.pos + 1] << 16 | self.data[self.pos + 2] << 24
        self.pos += 3
        bits = ((bits << 23) | (bits >> 9)) & 0xFFFFFFFF
        return struct.unpack("<f", struct.pack("<I", bits))[0]

    def string(self) -> str:
        end = self.data.find(b"\0", self.pos)
        if end < 0:
            raise KiwiError("unterminated string")
        out = self.data[self.pos : end].decode("utf-8", errors="surrogatepass")
        self.pos = end + 1
        return out


class Writer:
    __slots__ = ("buf",)

    def __init__(self) -> None:
        self.buf = bytearray()

    def byte(self, b: int) -> None:
        self.buf.append(b & 255)

    def bytes(self, b: bytes) -> None:
        self.var_uint(len(b))
        self.buf += b

    def var_uint(self, v: int) -> None:
        v &= 0xFFFFFFFF
        while True:
            b = v & 127
            v >>= 7
            if v:
                self.buf.append(b | 128)
            else:
                self.buf.append(b)
                return

    def var_int(self, v: int) -> None:
        self.var_uint(((v << 1) ^ (v >> 31)) & 0xFFFFFFFF)

    def var_uint64(self, v: int) -> None:
        v &= 0xFFFFFFFFFFFFFFFF
        for _ in range(8):
            b = v & 127
            v >>= 7
            if not v:
                self.buf.append(b)
                return
            self.buf.append(b | 128)
        self.buf.append(v & 255)

    def var_int64(self, v: int) -> None:
        self.var_uint64(((v << 1) ^ (v >> 63)) & 0xFFFFFFFFFFFFFFFF)

    def var_float(self, v: float) -> None:
        bits = struct.unpack("<I", struct.pack("<f", v))[0]
        bits = ((bits >> 23) | (bits << 9)) & 0xFFFFFFFF
        if bits & 255 == 0:
            self.buf.append(0)
            return
        self.buf += bits.to_bytes(4, "little")

    def string(self, s: str) -> None:
        self.buf += s.encode("utf-8", errors="surrogatepass")
        self.buf.append(0)


def decode_schema(data: bytes) -> Schema:
    r = Reader(data)
    raw = []
    for _ in range(r.var_uint()):
        name, kind = r.string(), r.byte()
        fields = []
        for _ in range(r.var_uint()):
            fname, ftype, is_array, value = r.string(), r.var_int(), bool(r.byte() & 1), r.var_uint()
            fields.append((fname, ftype, is_array, value))
        raw.append((name, kind, fields))
    definitions = []
    for name, kind, fields in raw:
        d = Definition(name, kind)
        for fname, ftype, is_array, value in fields:
            tname = BUILTINS[ftype] if ftype < 0 else raw[ftype][0]
            f = Field(fname, tname, is_array, value)
            d.fields.append(f)
            d.by_value[value] = f
            d.by_name[fname] = f
        definitions.append(d)
    return Schema(definitions, {d.name: d for d in definitions})


def encode_schema(schema: Schema) -> bytes:
    index = {d.name: i for i, d in enumerate(schema.definitions)}
    w = Writer()
    w.var_uint(len(schema.definitions))
    for d in schema.definitions:
        w.string(d.name)
        w.byte(d.kind)
        w.var_uint(len(d.fields))
        for f in d.fields:
            w.string(f.name)
            w.var_int(BUILTIN_IDS[f.type] if f.type in BUILTIN_IDS else index[f.type])
            w.byte(int(f.is_array))
            w.var_uint(f.value)
    return bytes(w.buf)


_READ = {
    "bool": lambda r: bool(r.byte()),
    "byte": Reader.byte,
    "int": Reader.var_int,
    "uint": Reader.var_uint,
    "float": Reader.var_float,
    "string": Reader.string,
    "int64": Reader.var_int64,
    "uint64": Reader.var_uint64,
}
_WRITE = {
    "bool": lambda w, v: w.byte(1 if v else 0),
    "byte": Writer.byte,
    "int": Writer.var_int,
    "uint": Writer.var_uint,
    "float": Writer.var_float,
    "string": Writer.string,
    "int64": Writer.var_int64,
    "uint64": Writer.var_uint64,
}


class Codec:
    """Schema-bound decoder/encoder. Builds one reader/writer per definition on first use."""

    def __init__(self, schema: Schema) -> None:
        self.schema = schema
        self._readers: dict[str, object] = {}
        self._writers: dict[str, object] = {}

    # ── decode ──
    def _value_reader(self, f: Field):
        if f.type == "byte" and f.is_array:
            return Reader.bytes
        one = _READ.get(f.type) or self._reader(f.type)
        if not f.is_array:
            return one
        return lambda r: [one(r) for _ in range(r.var_uint())]

    def _reader(self, name: str):
        if name in self._readers:
            return self._readers[name]
        d = self.schema[name]
        if d.kind == KIND_ENUM:
            names = {f.value: f.name for f in d.fields}

            def read_enum(r: Reader, names=names, d=d):
                v = r.var_uint()
                return names.get(v, v)

            self._readers[name] = read_enum
            return read_enum
        # Placeholder so recursive definitions resolve lazily.
        cell: dict[str, object] = {}
        self._readers[name] = lambda r: cell["fn"](r)
        if d.kind == KIND_STRUCT:
            parts = [(f.name, self._value_reader(f)) for f in d.fields]

            def read_struct(r: Reader, parts=parts):
                return {n: fn(r) for n, fn in parts}

            cell["fn"] = read_struct
        else:
            parts = {f.value: (f.name, self._value_reader(f)) for f in d.fields}

            def read_message(r: Reader, parts=parts, d=d):
                out = {}
                while True:
                    tag = r.var_uint()
                    if tag == 0:
                        return out
                    try:
                        n, fn = parts[tag]
                    except KeyError:
                        raise KiwiError(f"{d.name}: unknown field {tag} at {r.pos}") from None
                    out[n] = fn(r)

            cell["fn"] = read_message
        self._readers[name] = cell["fn"]
        return cell["fn"]

    def decode(self, name: str, data: bytes) -> dict:
        r = Reader(data)
        out = self._reader(name)(r)
        return out

    # ── encode ──
    def _value_writer(self, f: Field):
        if f.type == "byte" and f.is_array:
            return Writer.bytes
        one = _WRITE.get(f.type) or self._writer(f.type)
        if not f.is_array:
            return one

        def write_array(w: Writer, items, one=one):
            w.var_uint(len(items))
            for item in items:
                one(w, item)

        return write_array

    def _writer(self, name: str):
        if name in self._writers:
            return self._writers[name]
        d = self.schema[name]
        if d.kind == KIND_ENUM:
            values = {f.name: f.value for f in d.fields}

            def write_enum(w: Writer, v, values=values, d=d):
                if isinstance(v, str):
                    try:
                        v = values[v]
                    except KeyError:
                        raise KiwiError(f"{d.name}: unknown enum value {v!r}") from None
                w.var_uint(v)

            self._writers[name] = write_enum
            return write_enum
        cell: dict[str, object] = {}
        self._writers[name] = lambda w, v: cell["fn"](w, v)
        if d.kind == KIND_STRUCT:
            parts = [(f.name, self._value_writer(f)) for f in d.fields]

            def write_struct(w: Writer, v, parts=parts, d=d):
                for n, fn in parts:
                    if n not in v:
                        raise KiwiError(f"{d.name}: missing struct field {n!r}")
                    fn(w, v[n])

            cell["fn"] = write_struct
        else:
            # Message fields are tagged, so any order is valid; dict order keeps a
            # decoded message byte-identical when re-encoded.
            parts = {f.name: (f.value, self._value_writer(f)) for f in d.fields}

            def write_message(w: Writer, v, parts=parts, d=d):
                for n, item in v.items():
                    if item is None:
                        continue
                    try:
                        tag, fn = parts[n]
                    except KeyError:
                        raise KiwiError(f"{d.name}: unknown field {n!r}") from None
                    w.var_uint(tag)
                    fn(w, item)
                w.var_uint(0)

            cell["fn"] = write_message
        self._writers[name] = cell["fn"]
        return cell["fn"]

    def encode(self, name: str, value: dict) -> bytes:
        w = Writer()
        self._writer(name)(w, value)
        return bytes(w.buf)
