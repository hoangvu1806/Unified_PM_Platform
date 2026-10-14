import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.models import OpenPencilProfile
from app.openpencil.components import ComponentSource
from app.openpencil.gateway import OpenPencilGateway
from app.openpencil.project_executor import _prepare_project_document


def settings(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        design_data_dir=tmp_path,
        openpencil_cli="openpencil",
        mcp_timeout_seconds=10,
        openpencil_mcp_auth_token="",
    )


def profile(source: Path, output: Path) -> OpenPencilProfile:
    return OpenPencilProfile(
        endpoint="http://127.0.0.1:7600/mcp",
        source_file=str(source),
        output_file=str(output),
    )


def test_catalog_reads_fig_from_disk_without_mcp(tmp_path: Path) -> None:
    async def scenario() -> None:
        source = tmp_path / "library.fig"
        source.write_bytes(b"fig")
        adapter = ComponentSource(settings(tmp_path))  # type: ignore[arg-type]
        adapter._json = AsyncMock(return_value=[{"id": "1:2", "name": "Button", "page": "Actions"}])  # type: ignore[method-assign]
        result = await adapter.discover(profile(source, tmp_path / "output.fig"), None, None)
        assert result[0].component_id == "1:2"
        assert result[0].canonical_path == "Actions/Button"
        arguments = adapter._json.await_args.args  # type: ignore[attr-defined]
        assert arguments[:2] == ("query", str(source.resolve()))
        assert "//COMPONENT" in arguments

    asyncio.run(scenario())


def test_component_pack_orders_dependencies_before_parent(tmp_path: Path) -> None:
    async def scenario() -> None:
        source = tmp_path / "library.fig"
        source.write_bytes(b"fig")
        dependency = tmp_path / "dependency.jsx"
        dependency.write_text('<Component name="Icon" />', encoding="utf-8")
        parent = tmp_path / "parent.jsx"
        parent.write_text(
            '<Component name="Button"><Instance componentId="icon:1" /></Component>',
            encoding="utf-8",
        )
        adapter = ComponentSource(settings(tmp_path))  # type: ignore[arg-type]

        async def exported(_: Path, component_id: str) -> Path:
            return dependency if component_id == "icon:1" else parent

        adapter._jsx = exported  # type: ignore[method-assign]
        result = await adapter.pack(str(source), ["button:1"])
        assert [component_id for component_id, _ in result] == ["icon:1", "button:1"]

    asyncio.run(scenario())


def test_component_pack_preserves_zero_height_layout_guides(tmp_path: Path) -> None:
    async def scenario() -> None:
        source = tmp_path / "library.fig"
        source.write_bytes(b"fig")
        component = tmp_path / "button.jsx"
        component.write_text(
            '<Component h={40}><Line name="Min Width" w={90} /><Text>Save</Text></Component>',
            encoding="utf-8",
        )
        adapter = ComponentSource(settings(tmp_path))
        adapter._jsx = AsyncMock(return_value=component)
        packed = await adapter.pack(str(source), ["button"])
        assert '<Line name="Min Width" w={90}  h={0} />' in packed[0][1]

    asyncio.run(scenario())


def test_output_materialization_never_opens_source_file(tmp_path: Path) -> None:
    async def scenario() -> None:
        source = tmp_path / "library.fig"
        output = tmp_path / "output.fig"
        source.write_bytes(b"fig")
        gateway = OpenPencilGateway(settings(tmp_path))  # type: ignore[arg-type]
        calls: list[tuple[str, dict[str, object]]] = []

        async def call(_: object, tool: str, arguments: dict[str, object]) -> dict[str, object]:
            calls.append((tool, arguments))
            responses = {
                "new_document": {"documentId": "doc-1"},
                "list_pages": {"pages": []},
                "create_page": {"id": "page-components"},
                "switch_page": {},
                "render": {"id": "local-component"},
                "save_file": {},
            }
            return responses[tool]

        gateway._call = call  # type: ignore[method-assign]
        document_id, mapping, *_ = await _prepare_project_document(
            gateway,
            object(),
            profile(source, output),
            [("source-component", '<Component name="Button" />')],
            {},
        )
        assert document_id == "doc-1"
        assert mapping == {"source-component": "local-component"}
        assert all(tool != "open_file" for tool, _ in calls)
        assert calls[0] == ("new_document", {"path": str(output)})

    asyncio.run(scenario())


def test_source_auto_resolves_fuzzy_name(tmp_path: Path) -> None:
    systems_dir = tmp_path / "design-systems"
    systems_dir.mkdir(parents=True)
    real_file = systems_dir / "TapTap Design System - Developers (Community).fig"
    real_file.write_bytes(b"fig")

    adapter = ComponentSource(settings(tmp_path))  # type: ignore[arg-type]

    # Test resolving by name with pipe or dash and no extension
    resolved = adapter._source("TapTap Design System | Developers (Community)")
    assert resolved == real_file.resolve()

    # Test resolving by short keyword
    resolved_short = adapter._source("taptap")
    assert resolved_short == real_file.resolve()


def test_partial_catalog_still_discovers_candidates_for_uncovered_requirements(tmp_path: Path) -> None:
    async def scenario() -> None:
        source = tmp_path / "library.fig"
        source.write_bytes(b"fig")
        adapter = ComponentSource(settings(tmp_path))
        adapter._json = AsyncMock(return_value=[{"id": "input", "name": "Input"}, {"id": "button", "name": "Button"}])
        result = await adapter.discover(
            profile(source, tmp_path / "output.fig"),
            [{"node_id": "save"}, {"node_id": "email"}],
            {"matches": [{"node_id": "save", "component_id": "button", "name": "Button"}]},
        )
        assert {item.component_id for item in result} == {"button", "input"}
        await adapter.discover(profile(source, tmp_path / "output.fig"), None, None)
        adapter._json.assert_awaited_once()  # retry reads the cached catalog

    asyncio.run(scenario())


def test_component_pack_has_no_project_wide_forty_component_cap(tmp_path: Path) -> None:
    async def scenario() -> None:
        source = tmp_path / "library.fig"
        source.write_bytes(b"fig")
        component = tmp_path / "component.jsx"
        component.write_text('<Component name="Control" />', encoding="utf-8")
        adapter = ComponentSource(settings(tmp_path))
        adapter._jsx = AsyncMock(return_value=component)
        assert len(await adapter.pack(str(source), [str(i) for i in range(60)])) == 60

    asyncio.run(scenario())
