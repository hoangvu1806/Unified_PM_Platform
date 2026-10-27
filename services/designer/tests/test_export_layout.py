"""build_fig: frames per screen in rows on one page, or one page per screen."""

from app.export.figma import GAP, CapturedScreen, build_fig
from app.figio.container import read_fig


def _shot(name: str, group: str, w: float, h: float) -> CapturedScreen:
    return CapturedScreen(name, {"kind": "box", "x": 0, "y": 0, "w": w, "h": h, "box": {}, "children": []}, {}, group)


SCREENS = [
    _shot("Đăng nhập", "login", 390, 800),
    _shot("Đăng nhập · error", "login", 390, 900),
    _shot("Trang chủ", "home", 1440, 1000),
]


def _layout(data: bytes) -> dict[str, list[tuple[str, float, float]]]:
    """Page name -> [(frame name, x, y)] for the top-level frames of each page."""
    nodes = read_fig(data).message["nodeChanges"]
    key = lambda guid: (guid["sessionID"], guid["localID"])  # noqa: E731
    pages = {key(n["guid"]): n["name"] for n in nodes if n["type"] == "CANVAS" and not n.get("internalOnly")}
    out: dict[str, list[tuple[str, float, float]]] = {name: [] for name in pages.values()}
    for n in nodes:
        parent = key(n["parentIndex"]["guid"]) if n.get("parentIndex") else None
        if n["type"] == "FRAME" and parent in pages:
            out[pages[parent]].append((n["name"], n["transform"]["m02"], n["transform"]["m12"]))
    return out


def test_rows_put_each_screen_on_its_own_row_of_one_page() -> None:
    assert _layout(build_fig(SCREENS, "LMS", "rows")) == {"Screens": [
        ("Đăng nhập", 0, 0),
        ("Đăng nhập · error", 390 + GAP, 0),
        ("Trang chủ", 0, 900 + GAP),  # below the tallest frame of the first row
    ]}


def test_pages_put_each_screen_on_its_own_page() -> None:
    assert _layout(build_fig(SCREENS, "LMS", "pages")) == {
        "Đăng nhập": [("Đăng nhập", 0, 0), ("Đăng nhập · error", 390 + GAP, 0)],
        "Trang chủ": [("Trang chủ", 0, 0)],
    }
