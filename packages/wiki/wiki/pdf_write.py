from __future__ import annotations

from pathlib import Path


def write_pdf(path: Path, pages: list[list[str]], *, font_size: int = 11) -> None:
    """Multi-page Helvetica PDF (ASCII). Extractable by pypdf; no paraphrase."""

    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    def stream_for(lines: list[str]) -> bytes:
        cmds = ["BT", f"/F1 {font_size} Tf", "48 740 Td"]
        for i, line in enumerate(lines):
            if i:
                cmds.append("0 -13 Td")
            cmds.append(f"({esc(line[:98])}) Tj")
        cmds.append("ET")
        return "\n".join(cmds).encode("latin-1", errors="replace")

    if not pages:
        raise ValueError("PDF needs at least one page")

    streams = [stream_for(lines) for lines in pages]
    n = len(pages)
    font_id = 3 + 2 * n
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(n))
    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode("ascii"),
        font_id: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }
    for i, stream in enumerate(streams):
        page_id = 3 + 2 * i
        content_id = 4 + 2 * i
        objects[page_id] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Contents {content_id} 0 R "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> >>"
        ).encode("ascii")
        objects[content_id] = (
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"
        )

    out = bytearray(b"%PDF-1.4\n")
    offsets = {0: 0}
    for obj_id in range(1, font_id + 1):
        offsets[obj_id] = len(out)
        out.extend(f"{obj_id} 0 obj\n".encode("ascii"))
        out.extend(objects[obj_id])
        out.extend(b"\nendobj\n")
    xref = len(out)
    out.extend(f"xref\n0 {font_id + 1}\n".encode("ascii"))
    out.extend(b"0000000000 65535 f \n")
    for obj_id in range(1, font_id + 1):
        out.extend(f"{offsets[obj_id]:010d} 00000 n \n".encode("ascii"))
    out.extend(
        (
            f"trailer << /Size {font_id + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n"
        ).encode("ascii")
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(out))


def write_simple_pdf(path: Path, lines: list[str]) -> None:
    write_pdf(path, [lines])
