import asyncio
import base64
from types import SimpleNamespace

from app.core.llm import build_structured_content
from app.openpencil.gateway import OpenPencilGateway


def test_structured_content_includes_real_image_part() -> None:
    content = build_structured_content("Inspect this screen", "{}", image_bytes=b"jpeg", image_mime_type="image/jpeg")

    assert content.parts is not None
    assert len(content.parts) == 2
    assert content.parts[1].inline_data is not None
    assert content.parts[1].inline_data.data == b"jpeg"
    assert content.parts[1].inline_data.mime_type == "image/jpeg"


def test_preview_export_is_scoped_to_requested_document_and_page() -> None:
    async def scenario() -> None:
        calls: list[dict[str, object]] = []

        class Gateway:
            async def _call(self, *_args: object, **_kwargs: object) -> dict[str, str]:
                return {"ok": "true"}

        class Session:
            async def call_tool(self, _name: str, *, arguments: dict[str, object]) -> object:
                calls.append(arguments)
                return SimpleNamespace(content=[SimpleNamespace(data=base64.b64encode(b"jpeg").decode())])

        preview = await OpenPencilGateway._capture_preview(Gateway(), Session(), "doc-4", "page-2", "root-9", scale=1)

        assert preview == (b"jpeg", "jpg")
        assert calls[0]["document_id"] == "doc-4"
        assert calls[0]["page_id"] == "page-2"
        assert calls[0]["ids"] == ["root-9"]

    asyncio.run(scenario())
