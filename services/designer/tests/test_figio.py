from app.figio.container import read_canvas, read_fig, write_canvas, write_fig
from app.figio.kiwi import Codec, decode_schema, encode_schema
from app.figio.writer import SCHEMA_FILE, FigBuilder, _inflate, _position, drop_shadow


def _sample() -> bytes:
    b = FigBuilder("test")
    page = b.page("Page 1")
    screen = b.frame(page, "Screen", 0, 0, 390, 844, fill="#ffffff",
                     layout={"mode": "VERTICAL", "gap": 12, "padding": (24, 16, 24, 16)})
    b.text(screen, "Tiêu đề\nhai dòng", 0, 0, 358, 48, size=20, style="Bold")
    b.rect(screen, "Card", 0, 0, 358, 120, fill="#eef2ff", radius=12, effects=[drop_shadow("#0000001a", 0, 4, 12)])
    return b.to_bytes()


def test_schema_roundtrip():
    raw = _inflate(SCHEMA_FILE.read_bytes())
    assert encode_schema(decode_schema(raw)) == raw


def test_builder_output_reads_back():
    fig = read_fig(_sample())
    nodes = fig.message["nodeChanges"]
    by_type = {}
    for n in nodes:
        by_type.setdefault(n["type"], []).append(n)
    assert len(by_type["DOCUMENT"]) == 1 and len(by_type["CANVAS"]) == 2
    text = by_type["TEXT"][0]
    assert text["textData"]["characters"] == "Tiêu đề\nhai dòng"
    assert len(text["textData"]["lines"]) == 2
    frame = by_type["FRAME"][0]
    assert frame["stackMode"] == "VERTICAL" and frame["stackPaddingRight"] == 16.0
    assert by_type["ROUNDED_RECTANGLE"][0]["effects"][0]["type"] == "DROP_SHADOW"
    assert fig.meta["file_name"] == "test"


def test_message_reencodes_byte_identical():
    fig = read_fig(_sample())
    canvas = write_canvas(fig.version, fig.schema, fig.message)
    version, schema, message = read_canvas(canvas)
    codec = Codec(schema)
    assert codec.encode("Message", message) == codec.encode("Message", fig.message)
    assert read_fig(write_fig(fig)).message == fig.message


def test_child_positions_sort_in_insertion_order():
    keys = [_position(i) for i in range(400)]
    assert keys == sorted(keys) and len(set(keys)) == len(keys)
