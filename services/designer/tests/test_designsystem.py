import struct

from app.designsystem.importer import import_fig
from app.figio.writer import FigBuilder, solid


def _path_blob() -> bytes:
    # M0 0 L10 0 L10 10 Z
    return (
        bytes([1]) + struct.pack("<2f", 0, 0) + bytes([2]) + struct.pack("<2f", 10, 0)
        + bytes([2]) + struct.pack("<2f", 10, 10) + bytes([0])
    )


def _fig() -> bytes:
    b = FigBuilder("ds")
    styles = b.add(b._internal, "ROUNDED_RECTANGLE", "brand / primary", styleType="FILL", isPublishable=True,
                   fillPaints=[solid("#4f46e5")], size={"x": 10, "y": 10})
    text_style = b.add(b._internal, "TEXT", "label / md", styleType="TEXT", isPublishable=True, fontSize=14.0,
                       fontName={"family": "Inter", "style": "Semi Bold", "postscript": ""},
                       lineHeight={"value": 20.0, "units": "PIXELS"}, textData={"characters": "Ag", "lines": []})
    page = b.page("Components")
    group = b.frame(page, "Button", 0, 0, 300, 100, isStateGroup=True)
    for i, (variant, fill) in enumerate((("Primary", True), ("Outline", False))):
        sym = b.add(
            group, "SYMBOL", f"Variant={variant}, Size=md", size={"x": 120.0, "y": 40.0},
            transform={"m00": 1.0, "m01": 0.0, "m02": 0.0, "m10": 0.0, "m11": 1.0, "m12": 50.0 * i},
            fillPaints=[solid("#4f46e5")] if fill else [], styleIdForFill={"guid": styles} if fill else None,
            strokePaints=[] if fill else [solid("#e5e7eb")], strokeWeight=1.0, cornerRadius=8.0,
            stackMode="HORIZONTAL", stackSpacing=8.0, stackHorizontalPadding=16.0, stackPaddingRight=16.0,
            stackVerticalPadding=10.0, stackPaddingBottom=10.0, stackPrimaryAlignItems="CENTER",
            stackCounterAlignItems="CENTER", stackPrimarySizing="RESIZE_TO_FIT", stackCounterSizing="RESIZE_TO_FIT",
        )
        b.add(sym, "VECTOR", "icon", size={"x": 10.0, "y": 10.0}, fillPaints=[solid("#ffffff")],
              fillGeometry=[{"windingRule": "NONZERO", "commandsBlob": 0, "styleID": 0}])
        b.text(sym, "Lưu", 0, 0, 30, 20, size=14, style="Semi Bold", fill="#ffffff", auto_resize="WIDTH_AND_HEIGHT",
               styleIdForText={"guid": text_style})
    b.add(page, "SYMBOL", "_private helper", size={"x": 10.0, "y": 10.0})
    fig = b.to_fig()
    fig.message["blobs"] = [{"bytes": _path_blob()}]
    from app.figio.container import write_fig

    return write_fig(fig)


def test_import_extracts_tokens_components_and_html():
    ds = import_fig(_fig(), "Test DS")
    assert ds.tokens.colors["brand-primary"] == "#4f46e5"
    assert ds.tokens.semantic["primary"] == "brand-primary"
    assert ds.tokens.texts["label-md"]["weight"] == 600
    assert "--color-brand-primary: #4f46e5;" in ds.theme_css
    assert "--color-primary: var(--color-brand-primary);" in ds.theme_css
    assert "--text-label-md--line-height: 20px;" in ds.theme_css

    assert [c["name"] for c in ds.components] == ["Button"]  # "_private helper" is skipped
    button = ds.components[0]
    assert button["props"] == {"Variant": ["Primary", "Outline"], "Size": ["md"]}
    html = {v.id: v.html for v in ds.variants}
    primary = html["button--primary-md"]
    assert primary.startswith('<button class="flex') and 'data-component="Button"' in primary
    for cls in ("gap-[8px]", "px-[16px]", "py-[10px]", "justify-center", "items-center", "bg-brand-primary",
                "rounded-[8px]", "text-label-md"):
        assert cls in primary, cls
    assert '<path d="M0 0L10 0L10 10Z" fill="#ffffff"/>' in primary
    assert ">Lưu</span>" in primary
    outline = html["button--outline-md"]
    assert "border border-[#e5e7eb]" in outline and "bg-" not in outline.split(">")[0].replace("bg-[", "")
