import asyncio
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from ..core.config import Settings
from ..core.errors import AppError
from ..models import ComponentCandidate, OpenPencilProfile


class ComponentSource:
    """Read immutable component libraries by path through the OpenPencil CLI."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._fingerprints: dict[Path, tuple[int, int, str]] = {}
        self.packed_media: dict[str, str] = {}

    async def discover(
        self,
        profile: OpenPencilProfile,
        requirements: list[dict[str, Any]] | None,
        knowledge: dict[str, Any] | None,
    ) -> list[ComponentCandidate]:
        source = self._source(profile.source_file)
        # Parse the .fig once, not once per candidate (large libraries take seconds
        # to load). Cache by file fingerprint so retry never repeats that work.
        cache = self.settings.design_data_dir / "cache" / self._fingerprint(source) / "catalog.json"
        if cache.is_file():
            summaries = json.loads(cache.read_text(encoding="utf-8"))
        else:
            summaries = self._items(
                await self._json("query", str(source), "//COMPONENT", "--limit", "100000", "--json")
            )
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(summaries, ensure_ascii=False), encoding="utf-8")
        actual = {str(item["id"]): item for item in summaries if item.get("id")}
        hints = list((knowledge or {}).get("matches", []))
        hints_by_id = {str(item.get("component_id", "")): item for item in hints}
        selected = {str(item.get("component_id")) for item in hints} & actual.keys()
        for requirement in requirements or []:
            words = set(
                re.findall(
                    r"[a-z0-9]+",
                    json.dumps(requirement, ensure_ascii=True).lower(),
                )
            )
            ranked = sorted(
                actual.values(),
                key=lambda item: (
                    -len(
                        words
                        & set(
                            re.findall(
                                r"[a-z0-9]+",
                                f"{item.get('page', '')} {item.get('name', '')}".lower(),
                            )
                        )
                    ),
                    str(item.get("name", "")),
                ),
            )
            selected.update(str(item["id"]) for item in ranked[:12])
        if not requirements:
            selected = set(actual)
        candidates = []
        for component_id in sorted(selected):
            summary = actual[component_id]
            hint = hints_by_id.get(component_id, {})
            name = str(summary.get("name") or component_id)
            page = str(summary.get("page") or hint.get("page") or "")
            candidates.append(
                ComponentCandidate(
                    component_id=component_id,
                    library_id=str(source),
                    name=name,
                    path=page,
                    canonical_path=str(hint.get("canonical_path") or f"{page}/{name}".strip("/")),
                    width=self._number(summary.get("width")),
                    height=self._number(summary.get("height")),
                    text_slots=list(hint.get("text_slots", [])),
                    variant_name=name if "=" in name else None,
                    knowledge_score=int(hint.get("knowledge_score", 0)),
                )
            )
        return candidates

    async def pack(self, source_file: str, component_ids: list[str]) -> list[tuple[str, str]]:
        source = self._source(source_file)
        ordered: list[tuple[str, str]] = []
        visited: set[str] = set()
        self.packed_media = {}

        async def collect(component_id: str) -> None:
            if component_id in visited:
                return
            visited.add(component_id)
            jsx = self._normalize_jsx((await self._jsx(source, component_id)).read_text(encoding="utf-8"))
            media_folder = self.settings.design_data_dir / "cache" / self._fingerprint(source) / "components"
            media_folder.mkdir(parents=True, exist_ok=True)
            media_path = media_folder / f"{self._safe(component_id)}.png"
            if not media_path.is_file() or not media_path.stat().st_size:
                try:
                    await self._run(
                        "export",
                        str(source),
                        "--format",
                        "png",
                        "--node",
                        component_id,
                        "--output",
                        str(media_path),
                    )
                except AppError:
                    # Components without raster media remain valid JSX components.
                    media_path = None
            if media_path and media_path.is_file() and media_path.stat().st_size:
                self.packed_media[component_id] = str(media_path)
            for dependency in re.findall(r'componentId=["{]([^"}]+)', jsx):
                await collect(dependency)
            ordered.append((component_id, jsx))

        for component_id in dict.fromkeys(component_ids):
            await collect(component_id)
        return ordered

    @staticmethod
    def _normalize_jsx(jsx: str) -> str:
        """Preserve zero-height Figma guides when OpenPencil JSX omits their height."""

        def line(match: re.Match[str]) -> str:
            attributes = match.group(1)
            if re.search(r"\bh\s*=", attributes):
                return match.group(0)
            return f"<Line{attributes} h={{0}} />"

        return re.sub(r"<Line\b([^>]*)/>", line, jsx)

    async def _jsx(self, source: Path, component_id: str) -> Path:
        folder = self.settings.design_data_dir / "cache" / self._fingerprint(source) / "components"
        folder.mkdir(parents=True, exist_ok=True)
        output = folder / f"{self._safe(component_id)}.jsx"
        if not output.is_file() or not output.stat().st_size:
            await self._run(
                "export",
                str(source),
                "--format",
                "jsx",
                "--node",
                component_id,
                "--output",
                str(output),
                "--style",
                "openpencil",
            )
        if not output.is_file() or not output.stat().st_size:
            raise AppError("COMPONENT_EXPORT_FAILED", "Component export failed", component_id, 502, True)
        return output

    async def _json(self, *arguments: str) -> Any:
        output = await self._run(*arguments)
        start = min((index for index in (output.find("["), output.find("{")) if index >= 0), default=-1)
        try:
            value, _ = json.JSONDecoder().raw_decode(output[start:] if start >= 0 else output)
            return value
        except json.JSONDecodeError as error:
            raise AppError(
                "COMPONENT_SOURCE_INVALID", "Component source returned invalid data", output[-500:], 502
            ) from error

    async def _run(self, *arguments: str) -> str:
        configured = Path(self.settings.openpencil_cli)
        script = configured if configured.suffix == ".ts" and configured.is_file() else None
        executable = shutil.which("bun" if script else self.settings.openpencil_cli)
        if not executable:
            raise AppError(
                "COMPONENT_CLI_MISSING",
                "OpenPencil CLI is unavailable",
                self.settings.openpencil_cli,
                409,
                action="Install or configure OPENPENCIL_CLI, then retry.",
            )
        args = [str(script), *arguments] if script else list(arguments)
        cwd = script.parents[3] if script else None

        try:
            try:
                async with asyncio.timeout(self.settings.mcp_timeout_seconds):
                    process = await asyncio.create_subprocess_exec(
                        executable,
                        *args,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        cwd=cwd,
                    )
                    stdout, stderr = await process.communicate()
                    returncode = process.returncode
            except NotImplementedError:
                # Windows event loop fallback (e.g. SelectorEventLoop where create_subprocess_exec is not supported)
                def _sync_exec() -> subprocess.CompletedProcess[bytes]:
                    return subprocess.run(
                        [executable, *args],
                        capture_output=True,
                        cwd=cwd,
                        timeout=self.settings.mcp_timeout_seconds,
                    )

                result = await asyncio.to_thread(_sync_exec)
                stdout, stderr = result.stdout, result.stderr
                returncode = result.returncode
        except (TimeoutError, subprocess.TimeoutExpired) as error:
            raise AppError(
                "COMPONENT_CLI_TIMEOUT",
                "Component inspection timed out",
                arguments[0] if arguments else "",
                504,
                True,
            ) from error

        if returncode:
            detail = stderr.decode(errors="replace") or stdout.decode(errors="replace")
            raise AppError("COMPONENT_CLI_FAILED", "Component inspection failed", detail[-1000:], 502, True)
        return stdout.decode(errors="replace")

    @staticmethod
    def _items(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if not isinstance(payload, dict):
            return []
        if isinstance(payload.get("node"), dict):
            return [payload["node"]]
        for key in ("nodes", "results", "components"):
            if isinstance(payload.get(key), list):
                return [item for item in payload[key] if isinstance(item, dict)]
        return [payload] if payload.get("id") else []

    def _source(self, value: str) -> Path:
        raw = value.strip().strip('"').strip("'")
        if not raw:
            raise AppError(
                "COMPONENT_SOURCE_MISSING",
                "Component source path is empty",
                raw,
                409,
                action="Choose an installed Design System or enter a .fig path in Settings.",
            )
        direct = Path(raw)
        if direct.is_file():
            return direct.resolve()

        design_dir = getattr(self.settings, "design_data_dir", None)
        if design_dir and Path(design_dir).is_dir():
            root = Path(design_dir)
            systems_dir = root / "design-systems"
            search_dirs = [systems_dir, root] if systems_dir.is_dir() else [root]
            for folder in search_dirs:
                if (folder / raw).is_file():
                    return (folder / raw).resolve()
                if (folder / f"{raw}.fig").is_file():
                    return (folder / f"{raw}.fig").resolve()

            norm_query = re.sub(r"[^a-z0-9]+", "", raw.lower())
            if norm_query:
                fig_files = list(root.rglob("*.fig"))
                # 1. Exact normalized match
                for fig in fig_files:
                    norm_name = re.sub(r"[^a-z0-9]+", "", fig.stem.lower())
                    if norm_query == norm_name:
                        return fig.resolve()
                # 2. Substring match
                for fig in fig_files:
                    norm_name = re.sub(r"[^a-z0-9]+", "", fig.stem.lower())
                    if norm_query in norm_name or norm_name in norm_query:
                        return fig.resolve()

        raise AppError(
            "COMPONENT_SOURCE_MISSING",
            "Component source was not found",
            str(direct),
            409,
            action="Choose an installed Design System or enter the full path to an existing .fig file in Settings.",
        )

    def _fingerprint(self, source: Path) -> str:
        stat = source.stat()
        cached = self._fingerprints.get(source)
        if cached and cached[:2] == (stat.st_mtime_ns, stat.st_size):
            return cached[2]
        digest = hashlib.sha256()
        with source.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        fingerprint = digest.hexdigest()
        self._fingerprints[source] = (stat.st_mtime_ns, stat.st_size, fingerprint)
        return fingerprint

    @staticmethod
    def _safe(value: str) -> str:
        return re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-") or "component"

    @staticmethod
    def _number(value: Any) -> float | None:
        return float(value) if isinstance(value, int | float) else None
